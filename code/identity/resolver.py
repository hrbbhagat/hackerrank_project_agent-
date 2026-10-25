
"""Identity resolution using current snapshots and historical audit events."""

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


IDENTIFIER_FIELDS = ("email", "email_hash", "phone")


def normalize(value):
    """Normalize identifiers for comparison without changing stored values."""
    return (value or "").strip().casefold()


def parse_timestamp(value):
    """Parse an ISO-8601 timestamp, including a trailing Z."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Timestamp cannot be empty")

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_csv(path):
    """Read a UTF-8 CSV file as a list of dictionaries."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class IdentityResolver:
    """Resolve current and historical identifiers at an audit cutoff."""

    def __init__(self, identities, audit_events):
        self.identities = {
            row["user_id"]: dict(row)
            for row in identities
        }
        self.audit_by_user = defaultdict(list)

        for event in audit_events:
            if event["user_id"] in self.identities:
                if event["field_name"] in IDENTIFIER_FIELDS:
                    self.audit_by_user[event["user_id"]].append(dict(event))

        for events in self.audit_by_user.values():
            events.sort(key=lambda event: parse_timestamp(event["event_time"]))

    @classmethod
    def from_directory(cls, data_dir="dataset"):
        """Load the two identity CSV files from a dataset directory."""
        data_dir = Path(data_dir)
        identities = read_csv(data_dir / "user_identities.csv")
        audit_events = read_csv(data_dir / "user_audit_log.csv")
        return cls(identities, audit_events)

    def _state_at_cutoff(self, user_id, cutoff):
        """Reverse later changes from the snapshot to estimate cutoff state."""
        snapshot = self.identities[user_id]
        state = {
            field: snapshot.get(field, "")
            for field in IDENTIFIER_FIELDS
        }

        events = self.audit_by_user.get(user_id, [])

        # Reverse changes after the cutoff, newest first.
        later_events = [
            event for event in events
            if parse_timestamp(event["event_time"]) > cutoff
        ]

        for event in reversed(later_events):
            field = event["field_name"]
            old_value = event["old_value"]
            new_value = event["new_value"]

            # Reverse only when the current reconstructed value matches
            # the event's recorded new value.
            if normalize(state[field]) == normalize(new_value):
                state[field] = old_value

        return state

    def identifiers_for_user(self, user_id, audit_at):
        """
        Return identifiers known by the cutoff, including older identifiers
        that may still exist in legacy systems.
        """
        if user_id not in self.identities:
            return {
                "user_id": user_id,
                "as_of": audit_at,
                "identifiers": {field: [] for field in IDENTIFIER_FIELDS},
            }

        cutoff = parse_timestamp(audit_at)
        state = self._state_at_cutoff(user_id, cutoff)
        values = {field: set() for field in IDENTIFIER_FIELDS}

        # Include the identifier state reconstructed at the cutoff.
        for field, value in state.items():
            if value and value.strip():
                values[field].add(value.strip())

        # Include identifiers recorded by historical events no later
        # than the cutoff, so older system records can also be searched.
        for event in self.audit_by_user.get(user_id, []):
            if parse_timestamp(event["event_time"]) <= cutoff:
                field = event["field_name"]
                for key in ("old_value", "new_value"):
                    value = (event.get(key) or "").strip()
                    if value:
                        values[field].add(value)

        return {
            "user_id": user_id,
            "as_of": audit_at,
            "identifiers": {
                field: sorted(values[field], key=str.casefold)
                for field in IDENTIFIER_FIELDS
            },
        }

    def resolve_email(self, email, audit_at):
        """
        Resolve an email to a user only when exactly one user has that
        identifier in their history by the requested cutoff.
        """
        target = normalize(email)
        if not target:
            return {
                "status": "UNRESOLVED",
                "user_id": None,
                "matches": [],
            }

        cutoff = parse_timestamp(audit_at)
        matches = []

        for user_id in self.identities:
            result = self.identifiers_for_user(user_id, audit_at)
            known_emails = {
                normalize(value)
                for value in result["identifiers"]["email"]
            }

            if target in known_emails:
                matches.append(user_id)

        matches.sort()

        if len(matches) == 1:
            return {
                "status": "RESOLVED",
                "user_id": matches[0],
                "matches": matches,
            }

        return {
            "status": "AMBIGUOUS" if matches else "UNRESOLVED",
            "user_id": None,
            "matches": matches,
        }



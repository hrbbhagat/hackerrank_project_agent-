"""Phase 6.6: Temporal Admissibility, Audit Cutoff, and Evidence Integrity.

Enforces the temporal contract for policy evaluation:
- Restricts decision inputs strictly to state and evidence admissible at or before `audit_at`.
- Reuses and honors Phase 5 timeline reconstruction without duplicate parsing.
- Enforces strict timezone normalization and UTC comparison semantics.
- Rejects temporal contradictions (event time > capture time, capture post-cutoff).
- Ensures evidence provenance is preserved without fabricated identifiers.
- Guarantees cutoff immutability: post-cutoff events cannot alter historical cutoff state.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union, Any
import re




# Valid participant-visible evidence ID prefixes
VALID_EVIDENCE_PREFIXES = ("evidence_", "activity_", "act_", "audit_", "file_")


def parse_iso_timestamp(value: Union[str, datetime, None]) -> Optional[datetime]:
    """
    Parse a timestamp string or datetime, normalizing to UTC.
    
    Preserves existing Phase 3B/Phase 5 timestamp semantics:
    - Parses ISO-8601 strings with trailing 'Z' or numeric offsets.
    - Naive datetimes are assigned UTC.
    - Aware datetimes are converted to UTC.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    
    val_str = str(value).strip()
    if not val_str:
        return None
    
    try:
        # Standardize Z to +00:00 for fromisoformat
        parsed = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def is_temporally_admissible(
    timestamp: Union[str, datetime, None],
    cutoff: Union[str, datetime, None],
) -> tuple[bool, Optional[str]]:
    """
    Determine if a timestamp is admissible at or before the cutoff.
    
    Returns:
        (is_admissible, exclusion_reason)
        If admissible: (True, None)
        If inadmissible: (False, reason_str)
    """
    parsed_cutoff = parse_iso_timestamp(cutoff)
    if parsed_cutoff is None:
        return False, "INVALID_OR_MISSING_CUTOFF"
    
    parsed_ts = parse_iso_timestamp(timestamp)
    if parsed_ts is None:
        return False, "MISSING_OR_MALFORMED_TIMESTAMP"
    
    # Exact match at cutoff is admissible
    if parsed_ts <= parsed_cutoff:
        return True, None
    else:
        return False, "EXCEEDS_AUDIT_CUTOFF"


def validate_evidence_temporal_integrity(
    event_time: Union[str, datetime, None],
    capture_time: Union[str, datetime, None],
    cutoff: Union[str, datetime, None],
) -> tuple[bool, Optional[str]]:
    """
    Validate the temporal admissibility and integrity of an evidence sighting.
    
    Enforces Phase 5 temporal rules:
    1. Cutoff enforcement: Neither capture_time nor event_time may exceed cutoff.
    2. Temporal consistency: Event time cannot be later than capture time.
    """
    parsed_cutoff = parse_iso_timestamp(cutoff)
    if parsed_cutoff is None:
        return False, "INVALID_OR_MISSING_CUTOFF"

    parsed_event_ts = parse_iso_timestamp(event_time)
    parsed_capture_ts = parse_iso_timestamp(capture_time)

    # At least one timestamp must be present
    if parsed_event_ts is None and parsed_capture_ts is None:
        return False, "MISSING_TIMESTAMP"

    # Capture time post cutoff excludes evidence regardless of event time
    if parsed_capture_ts is not None and parsed_capture_ts > parsed_cutoff:
        return False, "EXCLUDED_CAPTURE_POST_CUTOFF"

    # Event time post cutoff excludes event
    if parsed_event_ts is not None and parsed_event_ts > parsed_cutoff:
        return False, "EXCEEDS_AUDIT_CUTOFF"

    # Temporal contradiction: event recorded after it was supposedly captured
    if (
        parsed_event_ts is not None
        and parsed_capture_ts is not None
        and event_time is not None
        and capture_time is not None
        and parsed_event_ts > parsed_capture_ts
    ):
        return False, "EXCLUDED_TEMPORAL_CONTRADICTION"

    return True, None


def validate_evidence_id(evidence_id: Optional[str]) -> bool:
    """
    Verify that an evidence ID is either empty or traceable to participant-visible sources.
    
    Rejects fabricated or arbitrary strings.
    """
    if evidence_id is None or evidence_id == "":
        return True
    
    eid = str(evidence_id).strip().lower()
    return any(eid.startswith(prefix) for prefix in VALID_EVIDENCE_PREFIXES)


@dataclass(frozen=True)
class TemporalAuditValidation:
    """Audit verification result for a resource at a given cutoff."""
    is_valid: bool
    audit_at: Optional[datetime]
    resource_id: str
    observed_state: str
    evidence_id: str
    is_recreated_pre_cutoff: bool
    has_post_cutoff_recreation: bool
    replica_drift_detected: bool
    is_active_flow: bool
    is_restore_risk: bool
    contradictions: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def inspect_timeline_temporal_contract(
    timeline: Any,
    audit_at: Optional[Union[str, datetime]] = None,
) -> TemporalAuditValidation:
    """
    Verify that a Phase 5 ResourceTimeline satisfies the temporal contract.
    
    Ensures:
    1. Cutoff admissibility of all cited evidence.
    2. Segregation of post-cutoff events (cannot alter pre-cutoff state).
    3. Proper propagation of replica drift, active flows, and restore risks.
    4. Detection of temporal contradictions.
    """
    diagnostics = []
    contradictions = []

    resource_id = getattr(timeline, "resource_id", "unknown_resource")
    state_at_cutoff = getattr(timeline, "state_at_cutoff", "UNKNOWN")
    evidence_id = getattr(timeline, "latest_admissible_evidence_id", "")
    is_recreated = getattr(timeline, "is_recreated", False)
    is_active_flow = getattr(timeline, "is_active_flow", False)
    is_restore_risk = getattr(timeline, "is_restore_risk", False)
    replica_drift = getattr(timeline, "replica_drift", False)

    existing_contradictions = getattr(timeline, "contradictions", [])
    contradictions.extend(existing_contradictions)

    parsed_cutoff = parse_iso_timestamp(audit_at)

    # 1. Evidence ID verification
    if evidence_id and not validate_evidence_id(evidence_id):
        diagnostics.append(f"Unrecognized or potentially fabricated evidence_id '{evidence_id}'")

    # 2. Inspect post-cutoff events
    post_cutoff_events = getattr(timeline, "post_cutoff_events", [])
    has_post_cutoff_recreation = False
    for ev in post_cutoff_events:
        ev_cat = getattr(ev, "action_category", "")
        ev_type = getattr(ev, "event_type", "")
        if ev_cat == "ACTION_RECREATE" or ev_type in ("SYNC_RECORD", "INDEX_RECORD", "RESTORE_BACKUP"):
            has_post_cutoff_recreation = True

    # 3. Admissibility check on events
    admissible_events = getattr(timeline, "events", [])
    if parsed_cutoff is not None:
        for ev in admissible_events:
            ev_ts = getattr(ev, "timestamp", None)
            if ev_ts is not None and ev_ts > parsed_cutoff:
                contradictions.append(
                    f"Admissible event {getattr(ev, 'event_id', '')} timestamp {ev_ts.isoformat()} exceeds audit_at {parsed_cutoff.isoformat()}"
                )

    # 4. Replica drift check
    if replica_drift:
        diagnostics.append(f"Replica drift confirmed for {resource_id}: primary absent/deleted but replica retains record.")

    # 5. Check if evidence_id leaks from post-cutoff
    post_cutoff_evidence_ids = {getattr(ev, "evidence_id", "") for ev in post_cutoff_events if getattr(ev, "evidence_id", "")}
    admissible_evidence_ids = {getattr(ev, "evidence_id", "") for ev in admissible_events if getattr(ev, "evidence_id", "")}
    
    if evidence_id and evidence_id in post_cutoff_evidence_ids and evidence_id not in admissible_evidence_ids:
        contradictions.append(
            f"Evidence ID '{evidence_id}' cited as proof at cutoff, but only appears in post-cutoff events."
        )

    is_valid = len(contradictions) == 0

    return TemporalAuditValidation(
        is_valid=is_valid,
        audit_at=parsed_cutoff,
        resource_id=resource_id,
        observed_state=state_at_cutoff,
        evidence_id=evidence_id,
        is_recreated_pre_cutoff=is_recreated,
        has_post_cutoff_recreation=has_post_cutoff_recreation,
        replica_drift_detected=replica_drift,
        is_active_flow=is_active_flow,
        is_restore_risk=is_restore_risk,
        contradictions=contradictions,
        diagnostics=diagnostics,
    )

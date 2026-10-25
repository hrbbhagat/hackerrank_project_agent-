"""Phase 5: Core Timeline Reconstruction Engine.

Reconstructs the lifecycle state and event timeline for each resource
associated with a deletion request at its specific audit_at cutoff.
"""

from csv import DictReader
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import Optional

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
IDENTITY_DIR = CURRENT_DIR.parent / "identity"
EVIDENCE_DIR = CURRENT_DIR.parent / "evidence"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(IDENTITY_DIR))
if str(EVIDENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_DIR))

from resolver import IdentityResolver, parse_timestamp, normalize
from integration import EvidenceIntegrator, make_word_boundary_regex


# Category mapping by action
ACTION_CATEGORY_MAP = {
    "DELETE_RECORD": "ACTION_DELETE",
    "SYNC_RECORD": "ACTION_RECREATE",
    "INDEX_RECORD": "ACTION_RECREATE",
    "UPDATE_RECORD": "ACTION_UPDATE",
    "RESTORE_BACKUP": "ACTION_RECREATE",
    "CHECK_DATA_FLOW": "ACTION_FLOW_CHECK",
    "DISABLE_DATA_FLOW": "ACTION_FLOW_DISABLE",
    "CHECK_RESTORE_ACCESS": "ACTION_RESTORE_CHECK",
    "BLOCK_RESTORE": "ACTION_RESTORE_BLOCK",
    "REDACT_RECORD": "ACTION_POLICY_REDACT",
    "ANONYMIZE_RECORD": "ACTION_POLICY_ANON",
    "RETAIN_RECORD": "ACTION_POLICY_RETAIN",
    "LINK_RESOURCE_IDENTITY": "ACTION_LINK_IDENTITY",
    "DATABASE_RECORD": "ACTION_EVIDENCE_SIGHTING",
    "STRUCTURED_RECORD": "ACTION_EVIDENCE_SIGHTING",
    "SEARCH_HIT": "ACTION_EVIDENCE_SIGHTING",
    "LOG_EVENT": "ACTION_EVIDENCE_SIGHTING",
    "TEXT_ENTRY": "ACTION_EVIDENCE_SIGHTING",
    "DOCUMENT_ENTRY": "ACTION_EVIDENCE_SIGHTING",
    "IMAGE_OCR_ENTRY": "ACTION_EVIDENCE_SIGHTING",
}

# Known non-deletion request phrases
NON_DELETION_PATTERNS = [
    re.compile(r"do not (?:close|delete)", re.IGNORECASE),
    re.compile(r"don['’]t delete", re.IGNORECASE),
    re.compile(r"not asking for deletion", re.IGNORECASE),
    re.compile(r"leave (?:the )?account active", re.IGNORECASE),
    re.compile(r"keep (?:my |the )?account (?:active|open|as it is)", re.IGNORECASE),
    re.compile(r"subject access request", re.IGNORECASE),
    re.compile(r"opt[- ]?out of (?:marketing|promotional)", re.IGNORECASE),
    re.compile(r"marketing lists only", re.IGNORECASE),
    re.compile(r"rectification", re.IGNORECASE),
    re.compile(r"rectify", re.IGNORECASE),
    re.compile(r"data portability", re.IGNORECASE),
    re.compile(r"portable format", re.IGNORECASE),
    re.compile(r"copy of (?:.*)?invoices", re.IGNORECASE),
    re.compile(r"without removing", re.IGNORECASE),
    re.compile(r"not a request to erase", re.IGNORECASE),
    re.compile(r"leave (?:.*)?in place", re.IGNORECASE),
    re.compile(r"continue using the service", re.IGNORECASE),
    re.compile(r"information request", re.IGNORECASE),
]


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str                      # activity_id, audit_id, or evidence record locator
    timestamp: Optional[datetime]      # UTC-aware datetime or None
    source_type: str                   # "system_activity" | "evidence_record" | "user_audit"
    evidence_id: str                   # file_id (e.g. "evidence_54") or activity_id
    system_id: str                     # system name (e.g. "account_service", "search_service")
    resource_id: str                   # resource ID (e.g. "account_005", "data_flow_9522")
    event_type: str                    # Raw type: DELETE_RECORD, SYNC_RECORD, DATABASE_RECORD, etc.
    action_category: str               # High-level category: DELETE, RECREATE, FLOW_CHECK, RESTORE_CHECK, SIGHTING
    reported_result: str               # SUCCESS, FAILED, PARTIAL, PRESENT, ABSENT, etc.
    details: str                       # Context, error codes, raw descriptions
    matched_identifier: str            # user_id, email, phone, or hash
    is_admissible: bool                # True if timestamp <= audit_at
    exclusion_reason: Optional[str]    # None, "EXCEEDS_AUDIT_CUTOFF", "MISSING_EVENT_TIME", etc.
    raw_timestamp: Optional[str] = None # Original timestamp string for traceability


@dataclass
class ResourceTimeline:
    resource_id: str
    system_id: str
    resource_category: str             # USER_PROFILE, SEARCH_INDEX, DATA_FLOW, BACKUP_ARCHIVE, etc.
    events: list[TimelineEvent]        # Chronologically sorted admissible events
    post_cutoff_events: list[TimelineEvent] # Excluded future events
    state_at_cutoff: str               # ABSENT | PRESENT | REDACTED | ANONYMIZED | ACTIVE | BLOCKED | UNKNOWN
    latest_admissible_evidence_id: str # Evidence ID proving state at cutoff
    is_recreated: bool                 # True if recreation occurred before audit_at
    is_active_flow: bool               # True if data flow is actively copying
    is_restore_risk: bool              # True if backup archive can restore data
    contradictions: list[str]          # Discrepancies between activity claims and evidence
    evidence_provenance: list[str]     # All evidence_ids sighting this resource
    post_deletion_events: list[TimelineEvent] = field(default_factory=list) # Events after latest deletion attempt
    deletion_attempts: list[dict] = field(default_factory=list) # Logged deletion attempts and outcomes
    has_failed_deletion: bool = False  # True if any deletion attempt failed
    has_corroborated_deletion: bool = False # True if deletion claimed and negative evidence confirms absence
    replica_drift: bool = False        # True if primary deletion claimed but replica retains record


@dataclass
class TimelineReconstructionResult:
    case_id: str
    user_id: Optional[str]
    audit_at: Optional[datetime]
    is_non_deletion_request: bool      # True for cases 533-542
    resolution_status: str             # RESOLVED | AMBIGUOUS | UNRESOLVED
    resources: dict[str, ResourceTimeline] # Keyed by resource_id
    recreation_findings: list[dict]
    active_data_flows: list[dict]
    restore_risks: list[dict]
    unassociated_events: list[TimelineEvent]
    contradictions: list[str]
    errors: list[str]
    summary: dict                      # Aggregate counts (total_resources, absent, present, etc.)
    replica_drift_findings: list[dict] = field(default_factory=list) # Confirmed primary vs replica drifts
    failed_attempts: list[dict] = field(default_factory=list) # Failed deletion or restore attempts
    incomplete_chains: list[dict] = field(default_factory=list) # Incomplete sync or restoration chains


def categorize_resource_id(resource_id: str) -> str:
    """Infer the resource category from its standardized prefix."""
    rid = resource_id.lower().strip()
    if rid.startswith("account_"):
        return "USER_PROFILE"
    elif rid.startswith("search_"):
        return "SEARCH_INDEX_ENTRY"
    elif rid.startswith("analytics_"):
        return "ANALYTICS_PROFILE"
    elif rid.startswith("support_"):
        return "SUPPORT_MESSAGE"
    elif rid.startswith("data_flow_"):
        return "DATA_FLOW"
    elif rid.startswith("backup_"):
        return "BACKUP_ARCHIVE"
    elif rid.startswith("tombstone_"):
        return "ACCOUNT_TOMBSTONE"
    elif rid.startswith("audit_record_"):
        return "SECURITY_AUDIT_LOG"
    elif rid.startswith("export_"):
        return "USER_EXPORT"
    elif rid.startswith("email_"):
        return "EMAIL_DELIVERY_LOG"
    elif rid.startswith("cache_"):
        return "CACHE_ENTRY"
    elif rid.startswith("legal_"):
        return "LEGAL_HOLD_RECORD"
    elif rid.startswith("marketing_"):
        return "MARKETING_PROFILE"
    elif rid.startswith("object_"):
        return "SUPPORT_ATTACHMENT"
    return "OTHER"


def is_non_deletion_text(text: str) -> bool:
    """Detect whether request_text explicitly requests a non-deletion action."""
    if not text:
        return False
    for pat in NON_DELETION_PATTERNS:
        if pat.search(text):
            return True
    return False


class ActivityIndex:
    """Pre-indexed in-memory representation of dataset/system_activity.csv."""

    def __init__(self, activity_path: Optional[Path] = None):
        if activity_path is None:
            activity_path = ROOT_DIR / "dataset" / "system_activity.csv"
        self.activity_path = Path(activity_path).resolve()
        
        self.by_resource_id = {}
        self.by_user_id = {}
        self.link_identity_map = {}
        self.all_events = []
        
        self._load()

    def _load(self):
        if not self.activity_path.is_file():
            return
        
        with open(self.activity_path, "r", encoding="utf-8") as f:
            reader = DictReader(f)
            for row in reader:
                act_id = row.get("activity_id", "").strip()
                res_id = row.get("resource_id", "").strip()
                event_type = row.get("event_type", "").strip()
                details = row.get("details", "").strip()
                
                self.all_events.append(row)
                
                if res_id:
                    if res_id not in self.by_resource_id:
                        self.by_resource_id[res_id] = []
                    self.by_resource_id[res_id].append(row)
                
                # Check LINK_RESOURCE_IDENTITY mappings
                if event_type == "LINK_RESOURCE_IDENTITY":
                    for m in re.finditer(r"\buser_\d+\b", details):
                        self.link_identity_map.setdefault(m.group(0), set()).add(res_id)
                    for m in re.finditer(r"[\w\.-]+@[\w\.-]+\.\w+", details):
                        self.link_identity_map.setdefault(normalize(m.group(0)), set()).add(res_id)
                    for part in details.split(";"):
                        part = part.strip()
                        if part.startswith("user_id="):
                            uid = part.split("=", 1)[1].strip()
                            if uid:
                                self.link_identity_map.setdefault(uid, set()).add(res_id)
                        elif part.startswith("email="):
                            em = normalize(part.split("=", 1)[1].strip())
                            if em:
                                self.link_identity_map.setdefault(em, set()).add(res_id)


class TimelineReconstructor:
    """
    Phase 5 Core Timeline Reconstructor.
    
    Reconstructs chronological timelines for resources associated with
    a deletion request as of audit_at, detecting deletions, recreations,
    active data flows, and restoration risks.
    """

    def __init__(
        self,
        activity_index: Optional[ActivityIndex] = None,
        manifest_path: Optional[Path] = None,
        evidence_root: Optional[Path] = None,
    ):
        self.activity_index = activity_index or ActivityIndex()
        self.manifest_path = manifest_path or (ROOT_DIR / "dataset" / "evidence_files.csv")
        self.evidence_root = evidence_root or (ROOT_DIR / "dataset" / "evidence")

    def reconstruct_for_request(
        self,
        request: dict,
        resolver: IdentityResolver,
        integrator: EvidenceIntegrator,
    ) -> TimelineReconstructionResult:
        """
        Execute full Phase 5 timeline reconstruction for a single request.
        """
        case_id = str(request.get("case_id", "")).strip()
        email = str(request.get("email", "")).strip()
        audit_at_raw = str(request.get("audit_at", "")).strip()
        request_text = str(request.get("request_text", "")).strip()

        errors = []
        is_non_del = is_non_deletion_text(request_text)

        if not audit_at_raw:
            return TimelineReconstructionResult(
                case_id=case_id,
                user_id=None,
                audit_at=None,
                is_non_deletion_request=is_non_del,
                resolution_status="UNRESOLVED",
                resources={},
                recreation_findings=[],
                active_data_flows=[],
                restore_risks=[],
                unassociated_events=[],
                contradictions=[],
                errors=["Missing audit_at timestamp in request"],
                summary={"total_resources": 0},
            )

        try:
            audit_cutoff = parse_timestamp(audit_at_raw)
        except (ValueError, TypeError) as exc:
            return TimelineReconstructionResult(
                case_id=case_id,
                user_id=None,
                audit_at=None,
                is_non_deletion_request=is_non_del,
                resolution_status="UNRESOLVED",
                resources={},
                recreation_findings=[],
                active_data_flows=[],
                restore_risks=[],
                unassociated_events=[],
                contradictions=[],
                errors=[f"Invalid audit_at timestamp: {exc}"],
                summary={"total_resources": 0},
            )

        # 1. Identity Resolution
        res_info = resolver.resolve_email(email, audit_at_raw)
        res_status = res_info.get("status", "UNRESOLVED")
        user_id = res_info.get("user_id")

        if res_status != "RESOLVED" or not user_id:
            return TimelineReconstructionResult(
                case_id=case_id,
                user_id=None,
                audit_at=audit_cutoff,
                is_non_deletion_request=is_non_del,
                resolution_status=res_status,
                resources={},
                recreation_findings=[],
                active_data_flows=[],
                restore_risks=[],
                unassociated_events=[],
                contradictions=[],
                errors=[f"Identity is {res_status} for {email}"],
                summary={"total_resources": 0},
            )

        # 2. Get verified identifiers at cutoff
        cutoff_idents = resolver.identifiers_for_user(user_id, audit_at_raw)
        idents = cutoff_idents.get("identifiers", {})
        target_emails = {normalize(e) for e in idents.get("email", []) if e}
        target_hashes = {normalize(h) for h in idents.get("email_hash", []) if h}
        target_phones = {p.strip() for p in idents.get("phone", []) if p}

        # 3. Get Phase 3B evidence matches
        evidence_result = integrator.correlate_for_request(request, resolver)
        admissible_matches = evidence_result.get("admissible_matches", [])
        excluded_evidence = evidence_result.get("excluded_matches", [])
        errors.extend(evidence_result.get("errors", []))

        # 4. Discover subject resources
        # A. From positive evidence matches
        discovered_resources = {}  # res_id -> system_id
        for m in admissible_matches:
            rid = m.get("resource_id")
            sys_id = m.get("system_id") or "unknown_system"
            if rid:
                discovered_resources[rid] = sys_id

        # B. From catalog mapping LINK_RESOURCE_IDENTITY
        if user_id in self.activity_index.link_identity_map:
            for rid in self.activity_index.link_identity_map[user_id]:
                if rid and rid not in discovered_resources:
                    discovered_resources[rid] = self._infer_system_from_activity(rid)

        for em in target_emails:
            if em in self.activity_index.link_identity_map:
                for rid in self.activity_index.link_identity_map[em]:
                    if rid and rid not in discovered_resources:
                        discovered_resources[rid] = self._infer_system_from_activity(rid)

        # C. From direct user_id matches in system_activity details
        user_id_regex = make_word_boundary_regex(user_id)
        for act in self.activity_index.all_events:
            rid = act.get("resource_id", "").strip()
            details = act.get("details", "")
            if rid and rid not in discovered_resources:
                if user_id_regex.search(details):
                    discovered_resources[rid] = act.get("target_system") or act.get("source_system") or "unknown_system"

        # 5. Build timeline for each resource
        resources_dict = {}
        recreation_findings = []
        replica_drift_findings = []
        failed_attempts = []
        incomplete_chains = []
        active_data_flows = []
        restore_risks = []
        contradictions = []

        for rid, default_sys in sorted(discovered_resources.items()):
            timeline = self._reconstruct_single_resource(
                resource_id=rid,
                default_system_id=default_sys,
                user_id=user_id,
                target_emails=target_emails,
                audit_cutoff=audit_cutoff,
                admissible_matches=admissible_matches,
                excluded_evidence=excluded_evidence,
            )
            resources_dict[rid] = timeline

            if timeline.is_recreated:
                recreate_ev = next((e for e in timeline.post_deletion_events if e.action_category == "ACTION_RECREATE"), None)
                delete_ev_id = timeline.deletion_attempts[-1]["event_id"] if timeline.deletion_attempts else None
                recreation_findings.append({
                    "resource_id": rid,
                    "system_id": timeline.system_id,
                    "source_system": recreate_ev.system_id if recreate_ev else None,
                    "target_system": timeline.system_id,
                    "state_at_cutoff": timeline.state_at_cutoff,
                    "recreation_event_type": recreate_ev.event_type if recreate_ev else "RECREATE",
                    "recreation_event_id": recreate_ev.event_id if recreate_ev else None,
                    "recreation_timestamp": recreate_ev.timestamp.isoformat() if recreate_ev and recreate_ev.timestamp else None,
                    "delete_event_id": delete_ev_id,
                    "evidence_id": timeline.latest_admissible_evidence_id,
                    "details": recreate_ev.details if recreate_ev else "",
                })

            if timeline.replica_drift:
                delete_ev_id = timeline.deletion_attempts[-1]["event_id"] if timeline.deletion_attempts else None
                replica_drift_findings.append({
                    "resource_id": rid,
                    "primary_system": "account_service",
                    "replica_system": timeline.system_id,
                    "delete_event_id": delete_ev_id,
                    "evidence_id": timeline.latest_admissible_evidence_id,
                    "state_at_cutoff": timeline.state_at_cutoff,
                    "details": (
                        f"Primary deletion reported SUCCESS, but replica snapshot "
                        f"{timeline.latest_admissible_evidence_id} retains record at audit cutoff"
                    ),
                })

            for att in timeline.deletion_attempts:
                if att.get("reported_result") in ("FAILED", "PARTIAL"):
                    failed_attempts.append({
                        "resource_id": rid,
                        "system_id": timeline.system_id,
                        "event_id": att.get("event_id"),
                        "timestamp": att.get("timestamp"),
                        "reported_result": att.get("reported_result"),
                        "details": att.get("details"),
                        "attempt_type": "FAILED_DELETION",
                    })

            if timeline.is_active_flow:
                active_data_flows.append({
                    "resource_id": rid,
                    "system_id": timeline.system_id,
                    "state_at_cutoff": timeline.state_at_cutoff,
                    "evidence_id": timeline.latest_admissible_evidence_id,
                })

            if timeline.is_restore_risk:
                restore_risks.append({
                    "resource_id": rid,
                    "system_id": timeline.system_id,
                    "state_at_cutoff": timeline.state_at_cutoff,
                    "evidence_id": timeline.latest_admissible_evidence_id,
                })

            contradictions.extend(timeline.contradictions)

        # Count states
        state_counts = {}
        for r in resources_dict.values():
            state_counts[r.state_at_cutoff] = state_counts.get(r.state_at_cutoff, 0) + 1

        summary = {
            "total_resources": len(resources_dict),
            "absent_count": state_counts.get("ABSENT", 0),
            "present_count": state_counts.get("PRESENT", 0),
            "redacted_count": state_counts.get("REDACTED", 0),
            "anonymized_count": state_counts.get("ANONYMIZED", 0),
            "active_count": state_counts.get("ACTIVE", 0),
            "blocked_count": state_counts.get("BLOCKED", 0),
            "recreation_count": len(recreation_findings),
            "replica_drift_count": len(replica_drift_findings),
            "failed_attempt_count": len(failed_attempts),
            "active_flow_count": len(active_data_flows),
            "restore_risk_count": len(restore_risks),
        }

        return TimelineReconstructionResult(
            case_id=case_id,
            user_id=user_id,
            audit_at=audit_cutoff,
            is_non_deletion_request=is_non_del,
            resolution_status=res_status,
            resources=resources_dict,
            recreation_findings=recreation_findings,
            active_data_flows=active_data_flows,
            restore_risks=restore_risks,
            unassociated_events=[],
            contradictions=contradictions,
            errors=errors,
            summary=summary,
            replica_drift_findings=replica_drift_findings,
            failed_attempts=failed_attempts,
            incomplete_chains=incomplete_chains,
        )

    def _infer_system_from_activity(self, resource_id: str) -> str:
        """Helper to get system name from activity index."""
        acts = self.activity_index.by_resource_id.get(resource_id, [])
        for act in acts:
            sys_id = act.get("target_system") or act.get("source_system")
            if sys_id:
                return sys_id
        cat = categorize_resource_id(resource_id)
        if cat == "USER_PROFILE":
            return "account_service"
        elif cat == "SEARCH_INDEX_ENTRY":
            return "search_service"
        elif cat == "ANALYTICS_PROFILE":
            return "analytics_platform"
        elif cat in ("SUPPORT_RECORD", "SUPPORT_MESSAGE"):
            return "support_platform"
        elif cat == "SUPPORT_ATTACHMENT":
            return "object_storage"
        elif cat == "MARKETING_PROFILE":
            return "marketing_platform"
        elif cat == "DATA_FLOW":
            return "integration_service"
        elif cat == "BACKUP_ARCHIVE":
            return "backup_service"
        return "unknown_system"

    def _reconstruct_single_resource(
        self,
        resource_id: str,
        default_system_id: str,
        user_id: str,
        target_emails: set,
        audit_cutoff: datetime,
        admissible_matches: list[dict],
        excluded_evidence: list[dict],
    ) -> ResourceTimeline:
        """Build the chronological event list and resolve state for a single resource."""
        category = categorize_resource_id(resource_id)
        raw_events = []
        evidence_provenance = set()

        # 1. Evidence matches for this resource
        for m in admissible_matches:
            if m.get("resource_id") == resource_id:
                ev_id = m.get("evidence_id")
                if ev_id:
                    evidence_provenance.add(ev_id)
                
                event_ts_raw = m.get("event_time")
                capture_ts_raw = m.get("captured_at")
                ts_raw = event_ts_raw or capture_ts_raw
                parsed_ts = None
                parsed_capture_ts = None

                if event_ts_raw:
                    try:
                        parsed_ts = parse_timestamp(event_ts_raw)
                    except (ValueError, TypeError):
                        parsed_ts = None

                if capture_ts_raw:
                    try:
                        parsed_capture_ts = parse_timestamp(capture_ts_raw)
                    except (ValueError, TypeError):
                        parsed_capture_ts = None

                # Fallback to capture time if event_time is absent
                if parsed_ts is None and parsed_capture_ts is not None:
                    parsed_ts = parsed_capture_ts

                # Evaluate temporal admissibility
                is_admiss = True
                ex_reason = None

                if parsed_ts is None:
                    is_admiss = False
                    ex_reason = "MALFORMED_EVENT_TIME" if ts_raw else "MISSING_EVENT_TIME"
                elif parsed_capture_ts is not None and parsed_capture_ts > audit_cutoff:
                    is_admiss = False
                    ex_reason = "EXCLUDED_CAPTURE_POST_CUTOFF"
                elif parsed_ts > audit_cutoff:
                    is_admiss = False
                    ex_reason = "EXCEEDS_AUDIT_CUTOFF"
                elif (
                    parsed_ts is not None
                    and parsed_capture_ts is not None
                    and event_ts_raw
                    and capture_ts_raw
                    and parsed_ts > parsed_capture_ts
                ):
                    is_admiss = False
                    ex_reason = "EXCLUDED_TEMPORAL_CONTRADICTION"

                rep_res = "PRESENT"
                rec_summary = m.get("record_summary", {})
                if isinstance(rec_summary, dict) and "result" in rec_summary:
                    res_val = str(rec_summary["result"]).upper()
                    if res_val in ("NOT_FOUND", "ABSENT"):
                        rep_res = "ABSENT"
                    elif res_val in ("DISABLED", "BLOCKED", "REDACTED", "ANONYMIZED", "ACTIVE"):
                        rep_res = res_val
                    elif res_val in ("FOUND", "IDENTIFIABLE"):
                        rep_res = "PRESENT"

                raw_events.append(TimelineEvent(
                    event_id=f"ev_{ev_id}_{m.get('record_index', 0)}",
                    timestamp=parsed_ts,
                    source_type="evidence_record",
                    evidence_id=ev_id or "",
                    system_id=m.get("system_id") or default_system_id,
                    resource_id=resource_id,
                    event_type=m.get("event_type") or "EVIDENCE_SIGHTING",
                    action_category=ACTION_CATEGORY_MAP.get(m.get("event_type"), "ACTION_EVIDENCE_SIGHTING"),
                    reported_result=rep_res,
                    details=m.get("explanation", ""),
                    matched_identifier=m.get("matched_identifier", ""),
                    is_admissible=is_admiss,
                    exclusion_reason=ex_reason,
                    raw_timestamp=ts_raw,
                ))

        # 2. Activity events for this resource
        acts = self.activity_index.by_resource_id.get(resource_id, [])
        for act in acts:
            act_id = act.get("activity_id", "")
            ts_raw = act.get("event_time", "")
            parsed_ts = None
            if ts_raw:
                try:
                    parsed_ts = parse_timestamp(ts_raw)
                except (ValueError, TypeError):
                    parsed_ts = None

            ev_type = act.get("event_type", "")
            act_cat = ACTION_CATEGORY_MAP.get(ev_type, "ACTION_ACTIVITY")
            rep_res = act.get("reported_result", "SUCCESS")
            sys_id = act.get("target_system") or act.get("source_system") or default_system_id

            if parsed_ts is None:
                is_admiss = False
                ex_reason = "MALFORMED_EVENT_TIME" if ts_raw else "MISSING_EVENT_TIME"
            elif parsed_ts <= audit_cutoff:
                is_admiss = True
                ex_reason = None
            else:
                is_admiss = False
                ex_reason = "EXCEEDS_AUDIT_CUTOFF"

            raw_events.append(TimelineEvent(
                event_id=act_id,
                timestamp=parsed_ts,
                source_type="system_activity",
                evidence_id=act_id,
                system_id=sys_id,
                resource_id=resource_id,
                event_type=ev_type,
                action_category=act_cat,
                reported_result=rep_res,
                details=act.get("details", ""),
                matched_identifier=user_id,
                is_admissible=is_admiss,
                exclusion_reason=ex_reason,
                raw_timestamp=ts_raw,
            ))

        # 3. Sort events deterministically
        def event_sort_key(ev: TimelineEvent):
            ts = ev.timestamp or datetime.min.replace(tzinfo=timezone.utc)
            return (ts, ev.event_id)

        raw_events.sort(key=event_sort_key)

        admissible_events = [e for e in raw_events if e.is_admissible]
        post_cutoff_events = [e for e in raw_events if not e.is_admissible]

        # 4. Analyze state transitions & recreation
        is_recreated = False
        latest_delete_ts = None
        latest_delete_ev = None
        has_post_delete_sync = False
        post_deletion_events = []
        deletion_attempts = []
        has_failed_deletion = False

        for ev in admissible_events:
            if ev.action_category == "ACTION_DELETE":
                att = {
                    "event_id": ev.event_id,
                    "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
                    "reported_result": ev.reported_result,
                    "details": ev.details,
                }
                deletion_attempts.append(att)
                if ev.reported_result in ("FAILED", "PARTIAL"):
                    has_failed_deletion = True
                if ev.reported_result in ("SUCCESS", "PRESENT", "FAILED"):
                    latest_delete_ts = ev.timestamp
                    latest_delete_ev = ev

        if latest_delete_ts:
            for ev in admissible_events:
                if ev.timestamp and ev.timestamp > latest_delete_ts:
                    post_deletion_events.append(ev)
                    if ev.action_category == "ACTION_RECREATE":
                        is_recreated = True
                        has_post_delete_sync = True

        # Check evidence sightings vs activity claims
        has_admissible_evidence_sighting = any(
            e.source_type == "evidence_record" and e.reported_result in ("PRESENT", "IDENTIFIABLE", "ACTIVE")
            for e in admissible_events
        )
        has_admissible_negative_sighting = any(
            e.source_type == "evidence_record" and e.reported_result in ("ABSENT", "NOT_FOUND")
            for e in admissible_events
        )

        contradictions = []
        state_at_cutoff = "ABSENT"
        latest_ev_id = ""

        # Determine latest establishing evidence ID
        admissible_ev_ids = [e.evidence_id for e in admissible_events if e.evidence_id.startswith("evidence_")]
        if admissible_ev_ids:
            latest_ev_id = admissible_ev_ids[-1]
        elif admissible_events:
            latest_ev_id = admissible_events[-1].evidence_id

        is_active_flow = False
        is_restore_risk = False
        replica_drift = False

        # Specific State Determination by Category
        if category == "USER_PROFILE":
            # If positive evidence sighting exists in database/replica, it is PRESENT
            if has_admissible_evidence_sighting:
                state_at_cutoff = "PRESENT"
                if latest_delete_ts and latest_delete_ev and latest_delete_ev.reported_result in ("SUCCESS", "PRESENT"):
                    replica_drift = True
                    contradictions.append(
                        f"Replica drift detected for {resource_id}: DELETE_RECORD reported SUCCESS at {latest_delete_ts.isoformat()}, "
                        f"but evidence snapshot {latest_ev_id} proves record remains PRESENT at audit cutoff."
                    )
            elif has_admissible_negative_sighting:
                state_at_cutoff = "ABSENT"
            elif latest_delete_ts:
                state_at_cutoff = "ABSENT"
            else:
                # No delete event and no evidence -> default to PRESENT or UNCERTAIN
                state_at_cutoff = "PRESENT"

        elif category == "SEARCH_INDEX_ENTRY":
            if is_recreated or has_admissible_evidence_sighting:
                state_at_cutoff = "PRESENT"
            elif latest_delete_ts:
                state_at_cutoff = "ABSENT"
            else:
                state_at_cutoff = "PRESENT"

        elif category == "DATA_FLOW":
            # Check latest connector state
            flow_state = "DISABLED"
            for ev in admissible_events:
                if ev.event_type == "CHECK_DATA_FLOW":
                    # Check details or sighting
                    if "status=stopped" in ev.details.lower() or "disabled" in ev.details.lower():
                        flow_state = "DISABLED"
                    else:
                        flow_state = "ACTIVE"
                elif ev.event_type == "DISABLE_DATA_FLOW":
                    flow_state = "DISABLED"

            if has_admissible_evidence_sighting:
                # Check connector record in service export
                for ev in admissible_events:
                    if "enabled" in ev.details.lower() and "true" in ev.details.lower():
                        flow_state = "ACTIVE"

            state_at_cutoff = flow_state
            is_active_flow = (flow_state == "ACTIVE")

        elif category == "BACKUP_ARCHIVE":
            # Check restore permissions
            restore_state = "BLOCKED"
            for ev in admissible_events:
                if ev.event_type == "CHECK_RESTORE_ACCESS":
                    if "restore_allowed=false" in ev.details.lower() or "blocked" in ev.details.lower():
                        restore_state = "BLOCKED"
                    else:
                        restore_state = "ACTIVE"
                elif ev.event_type == "BLOCK_RESTORE":
                    restore_state = "BLOCKED"

            if has_admissible_evidence_sighting:
                for ev in admissible_events:
                    if "restore_allowed" in ev.details.lower() and "true" in ev.details.lower():
                        restore_state = "ACTIVE"

            state_at_cutoff = restore_state
            is_restore_risk = (restore_state == "ACTIVE")

        elif category == "ANALYTICS_PROFILE":
            if has_admissible_evidence_sighting:
                # Check if unredacted direct identifiers were present in record
                has_pii = False
                for ev in admissible_events:
                    if ev.matched_identifier in target_emails or ev.matched_identifier == user_id:
                        has_pii = True
                state_at_cutoff = "PRESENT" if has_pii else "ANONYMIZED"
            else:
                state_at_cutoff = "ANONYMIZED" if any(e.event_type == "ANONYMIZE_RECORD" for e in admissible_events) else "ABSENT"

        elif category in ("SUPPORT_RECORD", "SUPPORT_MESSAGE"):
            if has_admissible_evidence_sighting:
                has_pii = any(ev.matched_identifier in target_emails for ev in admissible_events)
                state_at_cutoff = "PRESENT" if has_pii else "REDACTED"
            else:
                state_at_cutoff = "REDACTED" if any(e.event_type == "REDACT_RECORD" for e in admissible_events) else "ABSENT"

        elif category in ("SUPPORT_ATTACHMENT", "MARKETING_PROFILE"):
            state_at_cutoff = "ABSENT" if any(e.event_type == "DELETE_RECORD" for e in admissible_events) else "PRESENT"

        elif category == "ACCOUNT_TOMBSTONE":
            if has_admissible_evidence_sighting:
                has_pii = any(ev.matched_identifier in target_emails for ev in admissible_events)
                state_at_cutoff = "PRESENT" if has_pii else "REDACTED"
            else:
                state_at_cutoff = "REDACTED"

        elif category == "SECURITY_AUDIT_LOG":
            state_at_cutoff = "PRESENT"

        else:
            state_at_cutoff = "PRESENT" if has_admissible_evidence_sighting else "ABSENT"

        has_corroborated_deletion = (
            latest_delete_ev is not None
            and latest_delete_ev.reported_result in ("SUCCESS", "PRESENT")
            and not has_admissible_evidence_sighting
            and not is_recreated
        )

        return ResourceTimeline(
            resource_id=resource_id,
            system_id=default_system_id,
            resource_category=category,
            events=admissible_events,
            post_cutoff_events=post_cutoff_events,
            state_at_cutoff=state_at_cutoff,
            latest_admissible_evidence_id=latest_ev_id,
            is_recreated=is_recreated,
            is_active_flow=is_active_flow,
            is_restore_risk=is_restore_risk,
            contradictions=contradictions,
            evidence_provenance=sorted(list(evidence_provenance)),
            post_deletion_events=post_deletion_events,
            deletion_attempts=deletion_attempts,
            has_failed_deletion=has_failed_deletion,
            has_corroborated_deletion=has_corroborated_deletion,
            replica_drift=replica_drift,
        )

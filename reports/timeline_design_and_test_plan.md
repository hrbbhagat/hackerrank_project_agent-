# Phase 5 — Chunk 2: Timeline Reconstruction Design and Test Plan

**Project:** HackerRank Orchestrate (October 2026) — Ghost Data Still Exists  
**Phase:** Phase 5 — Timeline Reconstruction  
**Stage:** Chunk 2 — Timeline Design and Test Plan  
**Date:** 2026-10-25  
**Author:** Senior Agentic AI Developer, Software Architect, and Digital-Forensics Auditor  
**Harness / Model:** `Antigravity IDE` / `Gemini 3.8 Flash (Medium)`  
**Status:** DESIGN COMPLETE — PENDING USER APPROVAL BEFORE IMPLEMENTATION

---

## 1. Input and Output Schemas

### 1.1 Input Schema
The timeline reconstructor receives:
- **`request` (dict):**
  - `case_id`: Unique case ID (e.g. `case_35`).
  - `email`: Request email (current or historical).
  - `requested_at`: Submission timestamp.
  - `reported_status`: Initial workflow claim (`COMPLETE`, `PARTIALLY_COMPLETE`, `NOT_STARTED`).
  - `reported_at`: Claim reporting timestamp.
  - `audit_at`: Evaluation cutoff timestamp.
  - `request_text`: Request text (evaluated for non-deletion intent).
- **`resolver` (`IdentityResolver`):** Phase 3A verified resolver.
- **`integrator` (`EvidenceIntegrator`):** Phase 3B evidence integration module.
- **`activity_events` (list[dict]):** Pre-indexed rows from `dataset/system_activity.csv`.

### 1.2 Output Data Model

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class TimelineEvent:
    event_id: str                      # activity_id, audit_id, or evidence record locator
    timestamp: datetime                # UTC-aware datetime
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
    exclusion_reason: Optional[str]    # None or "EXCEEDS_AUDIT_CUTOFF"

@dataclass
class ResourceTimeline:
    resource_id: str
    system_id: str
    resource_category: str             # USER_PROFILE, SEARCH_INDEX, DATA_FLOW, BACKUP_ARCHIVE, etc.
    events: list[TimelineEvent]        # Chronologically sorted admissible events
    post_cutoff_events: list[TimelineEvent] # Excluded future events
    state_at_cutoff: str               # ABSENT | PRESENT | REDACTED | ANONYMIZED | ACTIVE | BLOCKED
    latest_admissible_evidence_id: str # Evidence ID proving state at cutoff
    is_recreated: bool                 # True if recreation occurred before audit_at
    is_active_flow: bool               # True if data flow is actively copying
    is_restore_risk: bool              # True if backup archive can restore data
    contradictions: list[str]          # Discrepancies between activity claims and evidence
    evidence_provenance: list[str]     # All evidence_ids sighting this resource

@dataclass
class TimelineReconstructionResult:
    case_id: str
    user_id: Optional[str]
    audit_at: datetime
    is_non_deletion_request: bool      # True for cases 533-542
    resources: dict[str, ResourceTimeline] # Keyed by resource_id
    recreation_findings: list[dict]
    active_data_flows: list[dict]
    restore_risks: list[dict]
    unassociated_events: list[TimelineEvent]
    contradictions: list[str]
    summary: dict                      # Aggregate counts (total_resources, absent, present, etc.)
```

---

## 2. Request Connection Path to Identities, Events, Resources, and Evidence

```
+-----------------------------------------------------------------------------------------+
|                                    Deletion Request                                     |
|               (case_id, email, requested_at, reported_status, audit_at)                 |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
                       +---------------------------------------------+
                       |       Phase 3A: IdentityResolver            |
                       |  - resolve_email(email, audit_at)           |
                       |  - identifiers_for_user(user_id, audit_at)  |
                       +---------------------------------------------+
                                             |
                     [user_id, current_email, historical_emails, hashes, phones]
                                             |
                                             v
                       +---------------------------------------------+
                       |      Phase 3B: EvidenceIntegrator           |
                       |  - correlate_for_request(request, resolver) |
                       +---------------------------------------------+
                                             |
                      +----------------------+----------------------+
                      |                                             |
                      v                                             v
       [Admissible Evidence Matches]                 [Post-Cutoff Excluded Matches]
      (evidence_id, system_id,                      (Retained for diagnostics)
       resource_id, record_summary)
                      |
                      +----------------------+
                                             |
                                             v
                       +---------------------------------------------+
                       |       Phase 5: TimelineReconstructor        |
                       |  1. Discovered Resources from Evidence      |
                       |  2. LINK_RESOURCE_IDENTITY Catalog Events   |
                       |  3. System Activity Stream Index            |
                       |  4. Merge & Chronological Sort (UTC)        |
                       |  5. Cutoff Enforcement (<= audit_at)        |
                       |  6. State & Risk Classification Engine      |
                       +---------------------------------------------+
                                             |
                                             v
                       +---------------------------------------------+
                       |        TimelineReconstructionResult         |
                       |  - Resource timelines & cutoff states       |
                       |  - Recreation findings                      |
                       |  - Active flow & restore risks              |
                       +---------------------------------------------+
```

1. **Step 1 — Non-Deletion Filtering:** Inspect `request_text`. If it matches the 10 known non-deletion patterns (`case_533` to `case_542`), flag `is_non_deletion_request = True`.
2. **Step 2 — Identity Resolution:** Resolve `user_id` and all valid identifiers as of `audit_at`.
3. **Step 3 — Evidence Ingestion:** Ingest `admissible_matches` from Phase 3B. Extract all sighted `resource_id`s and system identifiers.
4. **Step 4 — Activity Linking:** Query indexed `system_activity.csv` for:
   - Direct occurrences of the subject's `resource_id`s.
   - `LINK_RESOURCE_IDENTITY` events matching the subject's `user_id` or emails.
   - Textual mentions of `user_id` in activity `details` (bounded by word-boundary regex).
5. **Step 5 — Resource Aggregation:** Group all events and evidence records under their respective `resource_id`.

---

## 3. Event Normalization While Preserving Original Labels

Original labels from `system_activity.csv` are strictly preserved in `event_type` and `reported_result`. The reconstructor maps them into high-level action categories for state machine transitions:

| Raw `event_type` | Action Category | Role in Timeline Engine |
|---|---|---|
| `DELETE_RECORD` | `ACTION_DELETE` | Claims deletion of resource. If result is SUCCESS, marks candidate ABSENT. |
| `SYNC_RECORD` | `ACTION_RECREATE` | Background sync. If occurring after DELETE_RECORD, triggers recreation finding. |
| `INDEX_RECORD` | `ACTION_RECREATE` | Search index refresh. If occurring after DELETE_RECORD, triggers recreation finding. |
| `UPDATE_RECORD` | `ACTION_UPDATE` | Record update. If occurring after DELETE_RECORD, triggers recreation finding. |
| `RESTORE_BACKUP` | `ACTION_RECREATE` | Backup restoration. Triggers immediate recreation finding. |
| `CHECK_DATA_FLOW` | `ACTION_FLOW_CHECK` | Verifies whether connector is active (`enabled=True`) or idle. |
| `DISABLE_DATA_FLOW` | `ACTION_FLOW_DISABLE` | Explicit deactivation of connector; moves state to BLOCKED/DISABLED. |
| `CHECK_RESTORE_ACCESS`| `ACTION_RESTORE_CHECK`| Verifies whether backup can still be restored (`restore_allowed=True`). |
| `BLOCK_RESTORE` | `ACTION_RESTORE_BLOCK`| Explicit revocation of restore permissions; moves state to BLOCKED. |
| `REDACT_RECORD` | `ACTION_POLICY_REDACT`| Policy action redacting identifiers. |
| `ANONYMIZE_RECORD` | `ACTION_POLICY_ANON` | Policy action anonymizing analytics profile. |
| `RETAIN_RECORD` | `ACTION_POLICY_RETAIN`| Security event retention in archive service. |
| `DATABASE_RECORD`, `STRUCTURED_RECORD`, `LOG_EVENT`, `TEXT_ENTRY` | `ACTION_EVIDENCE_SIGHTING` | Grounded physical proof from evidence files. Trumps workflow claims! |

---

## 4. Resource Association and Decoy Rejection

1. **Grounded Association:** A resource is associated with a case ONLY if:
   - It appears in Phase 3B's verified `admissible_matches` for the subject's `user_id` or email.
   - An activity `LINK_RESOURCE_IDENTITY` event binds that specific `resource_id` to the subject.
   - An activity row's `details` matches the subject's `user_id` via word-bounded regex `(?<![A-Za-z0-9_])<user_id>(?![A-Za-z0-9_])`.
2. **Decoy Rejection:**
   - If an activity event references a resource but its `details` references a conflicting `user_id` or distinct email, it is flagged as a decoy and excluded.
   - Generic activity rows that do not identify a user or resource are placed into `unassociated_events` and not used to derive resource state.

---

## 5. Timestamp Validation, Timezone Handling, and Cutoff Semantics

1. **UTC Consistency:** All timestamps (`event_time`, `captured_at`, `audit_at`) are parsed with `parse_timestamp()` and compared as UTC-aware `datetime` objects.
2. **Inclusive Cutoff (`<= audit_at`):**
   - An event occurring at `2026-09-20T12:00:00Z` against an `audit_at` of `2026-09-20T12:00:00Z` is **admissible**.
   - An event occurring at `2026-09-20T12:00:01Z` is **inadmissible** (`EXCEEDS_AUDIT_CUTOFF`).
3. **Segregation:** Inadmissible events are stored in `post_cutoff_events` for diagnostics but are strictly prevented from influencing the historical state determination at `audit_at`.
4. **Capture Cutoff:** Evidence files captured after `audit_at` are already segregated by Phase 3B into `excluded_matches`.

---

## 6. Deletion, Restoration, and Recreation Classifications

For each associated resource, the chronological sequence of admissible events and evidence sightings determines the state at `audit_at`:

### 6.1 State Matrix

| Resource Prefix | Resource Category | Required State Determination Logic |
|---|---|---|
| `account_...` | User Profile | **ABSENT** if latest pre-cutoff evidence shows 404/deleted or absent from replica snapshot, with no subsequent update/sync.<br>**PRESENT** if present in database replica, export, or profile lookup. |
| `search_...` | Search Index Entry | **ABSENT** if deleted and index query returns 0 hits.<br>**PRESENT** if search index query returns hits, or if `INDEX_RECORD` / `SYNC_RECORD` occurred after `DELETE_RECORD`. |
| `analytics_...` | Analytics Profile | **ANONYMIZED** if all direct identifiers (user_id, email, phone, hash) are stripped/null.<br>**PRESENT** if identifiers are still populated. |
| `support_...` | Support Ticket / Msg | **REDACTED** if message text / conversation has PII stripped.<br>**PRESENT** if raw PII or unredacted attachment remains. |
| `data_flow_...` | Active Data Flow | **ACTIVE** if connector is enabled, or if latest activity is `CHECK_DATA_FLOW` reporting enabled without a subsequent `DISABLE_DATA_FLOW`.<br>**DISABLED** if disabled. |
| `backup_...` | Backup Archive | **ACTIVE** (Restore Risk) if `restore_allowed=True` without a subsequent `BLOCK_RESTORE`.<br>**BLOCKED** if restore access is blocked. |
| `tombstone_...`| Account Tombstone | **REDACTED** if `subject_reference` is retained and direct PII (name, email, phone, hash) is null.<br>**PRESENT** (Exposed PII) if direct PII is exposed. |
| `audit_record_...`| Security Audit Log | **PRESENT** if retained under policy retention window. |

### 6.2 Recreation Classification
Recreation is flagged when:
$$\exists\, t_{\text{del}} < t_{\text{recreate}} \le t_{\text{audit\_at}}$$
where:
- At $t_{\text{del}}$, a `DELETE_RECORD` occurred.
- At $t_{\text{recreate}}$, an `INDEX_RECORD`, `SYNC_RECORD`, `UPDATE_RECORD`, or `RESTORE_BACKUP` occurred for the same `resource_id`.

---

## 7. Provenance, Conflicts, and Uncertainty

1. **Evidence Provenance:** Every `ResourceTimeline` records `latest_admissible_evidence_id` (e.g. `evidence_54`) or `activity_id` that established its cutoff state.
2. **Conflict Resolution (Evidence > Claims):**
   - If an activity event claims `DELETE_RECORD reported_result: SUCCESS`, but a subsequent admissible evidence snapshot (e.g. failover replica SQL) still contains the record, the state is resolved to **`PRESENT`**.
   - The discrepancy is recorded in `contradictions`: `"Activity claimed SUCCESS at <ts>, but evidence <file_id> confirmed record PRESENT at <ts>"`.
3. **Uncertainty Tracking:** If an account profile was requested for deletion but neither deletion activity nor negative evidence (404/snapshot absence) exists, it is flagged as `UNCERTAIN_ABSENCE` and treated as `PRESENT` to avoid false-negative audits.

---

## 8. Performance and Deterministic Ordering

1. **Pre-Indexing:** `system_activity.csv` is loaded and indexed once into dictionary lookups (`by_resource_id`, `by_user_id`, `by_link_identity`). Memory footprint is under 15 MB for 4,011 rows.
2. **Deterministic Sorting:**
   - Events are sorted with key: `(event.timestamp, event.event_id)`.
   - Resources are returned in sorted alphabetical order by `resource_id`.
   - All results across repeated invocations are identical.

---

## 9. Test Plan (Chunk 5 Suite — 15 Tests)

A dedicated test suite `code/timeline/test_reconstructor.py` will validate:

1. **`test_01_pre_cutoff_events_ingested`**: Admissible events before `audit_at` are loaded.
2. **`test_02_boundary_cutoff_inclusive`**: Event exactly at `audit_at` is included.
3. **`test_03_post_cutoff_events_excluded`**: Event after `audit_at` is segregated into `post_cutoff_events`.
4. **`test_04_post_cutoff_evidence_excluded`**: Phase 3B capture exclusions respected.
5. **`test_05_recreation_detected_before_cutoff`**: `DELETE_RECORD` followed by `SYNC_RECORD` triggers `is_recreated = True`.
6. **`test_06_post_cutoff_recreation_ignored`**: Recreation after `audit_at` does not change cutoff state.
7. **`test_07_evidence_trumps_activity_claims`**: Activity claims `DELETE SUCCESS` but replica SQL contains record -> state is `PRESENT`.
8. **`test_08_active_data_flow_detected`**: `data_flow_...` with `enabled=True` classified as `ACTIVE`.
9. **`test_09_disabled_data_flow_detected`**: Connector with `DISABLE_DATA_FLOW` classified as `DISABLED`.
10. **`test_10_backup_restore_risk_detected`**: `backup_...` with `restore_allowed=True` classified as `ACTIVE`.
11. **`test_11_blocked_backup_detected`**: Archive with `BLOCK_RESTORE` classified as `BLOCKED`.
12. **`test_12_compliant_tombstone_classified_redacted`**: Tombstone with null PII classified as `REDACTED`.
13. **`test_13_exposed_pii_tombstone_classified_present`**: Tombstone exposing email classified as `PRESENT`.
14. **`test_14_non_deletion_request_flagged`**: Requests `case_533` to `case_542` return `is_non_deletion_request = True`.
15. **`test_15_deterministic_timeline_replay`**: Successive reconstructions produce identical resource lists and event orders.

---

## 10. Exact Files to Add or Change

| File | Type | Description |
|---|---|---|
| `code/timeline/__init__.py` | New file | Module exports: `TimelineReconstructor`, `TimelineEvent`, `ResourceTimeline`, `TimelineReconstructionResult`. |
| `code/timeline/reconstructor.py` | New file | Complete Phase 5 implementation: activity pre-indexer, resource correlator, event merger, lifecycle state evaluator, recreation/flow/restore analyzers. |
| `code/timeline/test_reconstructor.py` | New file | 15 unit tests covering all planned test cases. |
| `reports/timeline_design_and_test_plan.md` | New file | This design report. |

*Zero changes to existing Phase 1–4 source files or challenge datasets. No changes to `code/main.py` or `output.csv`.*

---

## 11. Prioritized Implementation Checklist (Chunk 3 & 4)

- [ ] **Chunk 3.1:** Implement `code/timeline/__init__.py` and data classes in `code/timeline/reconstructor.py`.
- [ ] **Chunk 3.2:** Implement activity pre-indexer (`ActivityIndex`) for fast lookups.
- [ ] **Chunk 3.3:** Implement resource correlation and chronological event merging with inclusive cutoff filter.
- [ ] **Chunk 3.4:** Implement lifecycle state machine, recreation detector, active flow detector, and restore risk detector.
- [ ] **Chunk 4.1:** Implement `code/timeline/test_reconstructor.py` (15 tests).
- [ ] **Chunk 4.2:** Execute unit tests and full repository regression suite.
- [ ] **Chunk 4.3:** Run dataset-level validation across all 518 evaluation requests.
- [ ] **Chunk 4.4:** Produce `reports/phase_5_timeline_reconstruction_report.md`.

---

## 12. Blockers and Unresolved Questions

**Zero Blockers Identified.**  
All data fields, event types, evidence records, and temporal cutoffs are established and grounded in verified repository files.

**Stopping for review before coding Chunk 3.**

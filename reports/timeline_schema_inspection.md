# Phase 5 — Chunk 5.1: Timeline Schema & Code Inspection Report

**Project:** HackerRank Orchestrate (October 2026) — Ghost Data Still Exists  
**Module:** Phase 5 — Timeline Reconstruction  
**Inspection Date:** 2026-10-25  
**Inspector:** Senior Agentic AI Developer, Software Architect, and Digital-Forensics Auditor  
**Status:** READ-ONLY INSPECTION COMPLETE (Ready for Chunk 5.2/5.3 Design & Implementation)

---

## 1. Actual Dataset Inventory and Schemas

### 1.1 Complete CSV Inventory Reconciliation
The prior Phase 2 audit reported 9 CSV files loaded in `dataset/`. The actual directory contains exactly 9 CSV files. Every file exists on disk, was read with Python's standard `csv.DictReader`, and has 0 missing required cells:

| File | Actual Row Count | Key Identifier | Timestamp Fields | Inferred Types & Notes |
|---|---:|---|---|---|
| `dataset/deletion_requests.csv` | 518 | `case_id` | `requested_at`, `reported_at`, `audit_at` | Evaluation cases (case_33 to case_550) |
| `dataset/system_activity.csv` | 4,011 | `activity_id` | `event_time` | Global event log across services |
| `dataset/user_audit_log.csv` | 306 | `audit_id` | `event_time` | Historical identity field changes |
| `dataset/user_identities.csv` | 850 | `user_id` | `updated_at` | Current identity snapshot |
| `dataset/deletion_rules.csv` | 15 | `rule_id` | *(none)* | Policy categories, conditions, actions |
| `dataset/evidence_files.csv` | 94 | `file_id` | `captured_at` | Manifest of all evidence artifacts |
| `dataset/sample_deletion_requests.csv` | 32 | `case_id` | `requested_at`, `reported_at`, `audit_at` | Public reference requests (case_01 to case_32) |
| `dataset/sample_output.csv` | 32 | `case_id` | *(none)* | Benchmark outputs and step serialization |
| `dataset/output.csv` | 0 | `case_id` | *(none)* | Blank submission template (header only) |

### 1.2 Exact Column Schemas
1. **`deletion_requests.csv`**: `case_id,email,requested_at,reported_status,reported_at,audit_at,request_text`
2. **`system_activity.csv`**: `activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details`
3. **`user_audit_log.csv`**: `audit_id,user_id,event_time,field_name,old_value,new_value`
4. **`user_identities.csv`**: `user_id,name,email,phone,email_hash,updated_at`
5. **`deletion_rules.csv`**: `rule_id,data_category,condition,required_action`
6. **`evidence_files.csv`**: `file_id,file_path,origin,captured_at`

### 1.3 Request Intent Analysis
Inspection of `request_text` across all 518 evaluation requests revealed exactly **10 non-deletion requests** (`case_533` through `case_542`). These requests ask for:
- Phone number rectification (`case_533`)
- Marketing opt-out (`case_534`, `case_538`)
- Data portability download (`case_535`)
- Password/login support (`case_536`)
- Name spelling rectification (`case_537`)
- Subject access request (SAR) (`case_539`, `case_542`)
- Invoices copy (`case_540`)
- Email update while keeping account active (`case_541`)

All 10 explicitly request to keep the account active ("do not close", "not asking for deletion", "leave the account active", "don't delete"). In accordance with the challenge specification, these 10 cases resolve to `NOT_APPLICABLE` with `steps_json=[]`. The remaining 508 cases are authorized deletion requests requiring full timeline and policy audits.

---

## 2. Actual Event Types and Observed Semantics

Inspection of all 4,011 rows in `dataset/system_activity.csv` established the exact vocabulary of event types, systems, reported results, and resource prefixes:

### 2.1 Event Types Observed (17 distinct)
1. `DELETE_RECORD` (890): Deletion worker submits resource deletion to service (e.g. account, search, support, export).
2. `UPDATE_RECORD` (672): Profile update or support index update.
3. `SYNC_RECORD` (447): Cross-service profile synchronization (e.g., account_service syncing to analytics_platform or search_service). Can recreate deleted data.
4. `INDEX_RECORD` (400): Search index refresh. Can recreate deleted search index entries.
5. `SEND_EMAIL` (368): Transactional email delivery.
6. `REFRESH_CACHE` (284): Cache warming / invalidation.
7. `RETAIN_RECORD` (206): Security-event archival to archive_service.
8. `ANONYMIZE_RECORD` (204): Policy action removing direct identifiers from analytics profiles.
9. `REDACT_RECORD` (173): Policy action redacting PII from support messages or tombstones.
10. `CREATE_EXPORT` (155): Scheduled account export generation.
11. `CHECK_DATA_FLOW` (89): Connector status check confirming whether a data flow remains `enabled` or `stopped`.
12. `DISABLE_DATA_FLOW` (36): Explicit deactivation of active sync/connector flows.
13. `BLOCK_RESTORE` (36): Policy action disabling restore access on backup archives.
14. `CHECK_RESTORE_ACCESS` (28): Backup audit checking whether an archive can still be restored.
15. `LINK_RESOURCE_IDENTITY` (12): Catalog event explicitly mapping resource IDs to user IDs and emails.
16. `CLASSIFY_REQUEST` (10): Privacy intake request classification.
17. `RESTORE_BACKUP` (1): Database restore operation recreating resources from backup.

### 2.2 Systems Observed
- **Source Systems:** `deletion_worker`, `account_service`, `profile_service`, `notification_service`, `support_platform`, `security_service`, `export_service`, `integration_service`, `data_catalog`, `privacy_intake`, `backup_service`.
- **Target Systems:** `account_service`, `search_service`, `analytics_platform`, `email_delivery_service`, `cache_service`, `archive_service`, `support_platform`, `object_store`, `integration_service`, `backup_service`, `account_replication_cluster`, `export_service`, `identity_service`, `legal_service`, `privacy_case_management`, `account_failover_replica`, `marketing_platform`.

### 2.3 Reported Results
- `SUCCESS` (2,914), `FAILED` (721), `PARTIAL` (376). Per the specification, reported results are claims; actual state must be established from grounded evidence.

### 2.4 Resource ID Prefixes
- `account_...` (USER_PROFILE), `search_...` (SEARCH_INDEX_ENTRY), `analytics_...` (ANALYTICS_PROFILE), `support_...` (SUPPORT_MESSAGE / SUPPORT_ATTACHMENT), `email_...` (EMAIL_DELIVERY_LOG), `cache_...` (CACHE_ENTRY), `audit_record_...` (SECURITY_AUDIT_LOG), `export_...` (USER_EXPORT), `data_flow_...` (DATA_FLOW), `backup_...` (BACKUP_ARCHIVE), `tombstone_...` (ACCOUNT_TOMBSTONE), `legal_...` (LEGAL_HOLD_RECORD).

---

## 3. Evidence Reader's Returned Structure Across Formats

Inspection of `code/evidence/reader.py` across the 6 supported evidence formats revealed the following runtime structures:

```python
# Top-level dictionary returned by read_evidence_file(path):
{
    "path": str,                      # Local file path
    "format": str,                    # "json" | "log" | "sql" | "txt" | "pdf" | "png"
    "extraction_method": str,         # extraction engine used
    "records": list[dict],            # parsed records
    "errors": list[str]               # parser warnings / errors
}
```

### Record Formats by Type:
1. **Periodic Structured System Exports (`service_resource_export_*.json`)**:
   - `raw_record["service_exports"]` contains sub-dictionaries for each system:
     - `account_service["profile_lookups"]`: `resource_id, status_code (404 = ABSENT), profile (None = ABSENT), observed_at`
     - `analytics_platform["profiles"]`: `resource_id, customer_reference, email, phone, email_hash, audience_cohort, observed_at`
     - `backup_service["restore_entries"]`: `resource_id, customer_reference, restore_allowed (True/False), archive_key, observed_at`
     - `export_service["exports"]`: `resource_id, customer_reference, owner_email, object_key, observed_at`
     - `integration_service["connectors"]`: `resource_id, customer_reference, customer_email, enabled (True/False), last_delivery_status, observed_at`
     - `search_service["index_queries"]`: `resource_id, query, hits["documents"], observed_at`
     - `security_service["audit_records"]`: `resource_id, subject_reference, event_code, retention_until, observed_at`
     - `support_platform["tickets"]`: `resource_id, customer_reference, requester_email, requester_name, requester_phone, observed_at`
2. **Snapshot Bundles (`customer_data_snapshot_bundle_*.json`)**:
   - `snapshots`: list of collections with `data_store`, `collection`, `captured_at`, `records` (e.g. `identity_service.deleted_customer_references` containing tombstones).
3. **Database Snapshots (`.sql`)**:
   - Parsed by static `sql_parser.py`: `statement_type == "INSERT INTO"`, `table`, `columns`, and `values` dictionary.
   - Example: `customer_profiles_failover_replica` with `resource_id, user_id, full_name, email, phone, account_status, updated_at`.
4. **Log Traces (`.log`)**:
   - `event_timestamp`, `fields` (service, level, trace_id, resource_id, event, lookup_key, subject_reference, customer_reference, http_status, rows), `raw_text`.
5. **Shift Handovers (`.txt`)**:
   - Standard line format: `timestamp | system_id | resource_id | category | status | match_key` (e.g. `evidence_03`).
6. **PDF Documents & PNG Screenshots**:
   - PDF: Page text with timestamp candidates.
   - PNG: OCR text with word-level confidence and timestamp candidates.

---

## 4. Identity Resolver Interface and Cutoff Semantics

### 4.1 Resolver Interface
- **Module:** `code/identity/resolver.py`
- **Instantiation:** `resolver = IdentityResolver.from_directory("dataset")`
- **Resolution:** `res = resolver.resolve_email(email, audit_at)`
  - Returns `{"status": "RESOLVED", "user_id": str, "matches": [str]}`
  - If ambiguous or unresolved, returns `"status": "AMBIGUOUS"` or `"UNRESOLVED"` with `user_id: None`.
- **Identifiers at Cutoff:** `idents = resolver.identifiers_for_user(user_id, audit_at)`
  - Returns `{"user_id": user_id, "as_of": audit_at, "identifiers": {"email": [...], "email_hash": [...], "phone": [...]}}`
  - Reconstructs exact state at `audit_at` by rolling back audit transitions occurring after `audit_at`.
  - Recovers historical emails, hashes, and phones that were recorded at or before `audit_at`.

### 4.2 Cutoff Comparison Semantics
- **Rule:** Inclusive temporal boundary (`<= audit_at`).
- All timestamps parsed to UTC `datetime` objects.
- Events with `event_time <= audit_at` are admissible for reconstructing historical events.
- Events with `event_time > audit_at` are strictly excluded from deciding state at `audit_at`.
- Evidence files with `captured_at > audit_at` cannot be used to prove the state at `audit_at`.

---

## 5. Resource and Data-Flow Correlation Strategy

To correlate activities and evidence records to a case without cross-talk or missing records:

1. **Subject Identifiers:** For a case, obtain `user_id` and all current and historical `emails`, `phones`, and `email_hashes`.
2. **Resource Discovery (Multi-source Grounding):**
   - Direct User Links: Evidence records and activity rows explicitly referencing `user_id` or any of the subject's emails/hashes/phones.
   - Catalog Linkage: `LINK_RESOURCE_IDENTITY` activity events linking resource IDs to the user's email or `user_id`.
   - Secondary Lookups: Once a `resource_id` is linked to the subject (e.g., `account_4248`, `search_052`, `support_864`, `data_flow_9522`), all system activity events referencing that `resource_id` are gathered.
3. **Temporal Ordering:** Group all events and evidence sightings for each resource and sort chronologically by timestamp.
4. **State Machine by Category:**
   - **User Profile (`account_...`):**
     - Initial: CREATED -> DELETED.
     - State at cutoff: Proven ABSENT if latest pre-cutoff evidence shows 404 / NOT_FOUND / absence from database snapshot; PRESENT if found in snapshot.
   - **Search Index (`search_...`):**
     - Initial: CREATED -> DELETED.
     - Recreation Check: If `INDEX_RECORD` or `SYNC_RECORD` occurred after `DELETE_RECORD` and before `audit_at`, status is PRESENT.
     - State at cutoff: ABSENT if deleted and not recreated; PRESENT if index query returns hits or handover lists FOUND.
   - **Analytics Profile (`analytics_...`):**
     - If direct identifiers (user_id, email, phone, hash) are null/omitted -> ANONYMIZED.
     - If direct identifiers are populated -> PRESENT (violating anonymization rule).
   - **Support Records (`support_...`):**
     - Attachment: If attachment still exists -> PRESENT (violating rule 06).
     - Conversation: If PII still present -> PRESENT (violating redaction rule 05); if PII null -> REDACTED.
   - **Active Data Flows (`data_flow_...`):**
     - If connector `enabled == True` or latest activity is `CHECK_DATA_FLOW` reporting enabled -> ACTIVE.
     - If connector `enabled == False` or latest activity is `DISABLE_DATA_FLOW` -> DISABLED.
   - **Backup Restores (`backup_...`):**
     - If `restore_allowed == True` or latest activity is `CHECK_RESTORE_ACCESS` -> ACTIVE (Restore Risk).
     - If `restore_allowed == False` or latest activity is `BLOCK_RESTORE` -> BLOCKED.
   - **Account Tombstones (`tombstone_...`):**
     - If `subject_reference == user_id` and name/email/phone/hash are all null -> REDACTED (Compliant).
     - If name/email/phone/hash are still populated -> PRESENT (Exposed PII).
   - **Security Audit Records (`audit_record_...`):**
     - Mandatory retention: Must be verified PRESENT under rule 12.

---

## 6. Known Ambiguities and Quality Limitations

1. **Untrusted Workflow Claims:** Activity logs frequently report `DELETE_RECORD` with `reported_result: SUCCESS` even when downstream copies or database replicas still retain the record. The timeline must treat activity entries as operational events, but rely on grounded evidence captures (`evidence_*.sql`, `.json`, `.log`) to prove resource state.
2. **Replication Drift:** Databases have primary and failover replicas. Failover replicas (e.g. `evidence_54`) may still contain profiles after primary deletion.
3. **Missing Resource Timestamps:** Some evidence snapshots contain capture times for the bundle rather than individual creation times. In those cases, `captured_at` represents the snapshot boundary.

---

## 7. Proposed Internal Timeline Model (Chunk 5.2 Schema)

```python
@dataclass(frozen=True)
class TimelineEvent:
    event_id: str                      # activity_id, audit_id, or evidence record id
    timestamp: datetime                # parsed UTC event timestamp
    source_type: str                   # "system_activity" | "evidence_record" | "user_audit"
    evidence_id: str                   # file_id from manifest, or activity_id
    system_id: str                     # account_service, search_service, etc.
    resource_id: str                   # account_..., search_..., etc.
    event_type: str                    # DELETE_RECORD, SYNC_RECORD, OBSERVATION, etc.
    outcome: str                       # SUCCESS, FAILED, PRESENT, ABSENT, etc.
    details: str                       # raw description or text
    matched_identifier: str            # email, user_id, etc.
    is_admissible: bool                # timestamp <= audit_at
    exclusion_reason: Optional[str]    # None or "EXCEEDS_AUDIT_CUTOFF"

@dataclass
class ResourceTimeline:
    resource_id: str
    system_id: str
    category: str                      # USER_PROFILE, SEARCH_INDEX_ENTRY, etc.
    events: list[TimelineEvent]        # chronologically sorted
    state_at_cutoff: str               # ABSENT, PRESENT, REDACTED, ANONYMIZED, ACTIVE, BLOCKED
    latest_evidence_id: str            # file_id proving state at cutoff
    is_recreated: bool                 # recreation detected before cutoff
    is_active_flow: bool               # active connector flow
    is_restore_risk: bool              # unblocked backup
    contradictions: list[str]          # any conflicting findings
```

---

## 8. Planned Test Cases (Chunk 5.4 Suite)

1. **Pre-cutoff Ingestion:** Events with `event_time < audit_at` correctly included.
2. **Boundary Cutoff Inclusion:** Event exactly at `audit_at` included (inclusive boundary).
3. **Post-cutoff Exclusion:** Events with `event_time > audit_at` marked inadmissible.
4. **Capture-time Enforcement:** Evidence captured after `audit_at` excluded from proving historical state.
5. **Recreation Detection:** `DELETE_RECORD` followed by `SYNC_RECORD` / `INDEX_RECORD` before `audit_at` correctly flags recreation.
6. **Post-cutoff Recreation Ignored:** Deletion before cutoff followed by recreation after cutoff does not affect cutoff state.
7. **Active Flow Identification:** `enabled=True` connector correctly identified as active data flow.
8. **Disabled Flow Check:** `enabled=False` or `DISABLE_DATA_FLOW` correctly identified as disabled.
9. **Backup Restore Risk:** `restore_allowed=True` correctly identified as restore risk.
10. **Blocked Backup:** `restore_allowed=False` or `BLOCK_RESTORE` correctly identified as blocked.
11. **Tombstone Compliant State:** Redacted tombstone with null direct identifiers marked REDACTED.
12. **Tombstone PII Violation:** Tombstone exposing email/phone marked PRESENT / Exposed PII.
13. **Mandatory Retention:** `audit_record_...` within retention period identified as PRESENT.
14. **Multilingual Non-deletion Intent:** Non-deletion requests correctly flagged as NOT_APPLICABLE.
15. **Deterministic Ordering:** Identical inputs produce identical timeline order across runs.

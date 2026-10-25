# Phase 5 — Chunk 1: Repository Discovery and Baseline Audit Report

**Project:** HackerRank Orchestrate (October 2026) — Ghost Data Still Exists  
**Phase:** Phase 5 — Timeline Reconstruction  
**Stage:** Chunk 1 — Discovery and Baseline Audit  
**Date:** 2026-10-25  
**Auditor:** Senior Agentic AI Developer, Software Architect, and Digital-Forensics Auditor  
**Harness / Model:** `Antigravity IDE` / `Gemini 3.8 Flash (Medium)`  
**Status:** DISCOVERY COMPLETE — PROCEED TO CHUNK 2 DESIGN

---

## 1. Executive Summary

Chunk 1 of Phase 5 conducts a forensic discovery audit of the repository, baseline test environment, dataset schemas, event semantics, and integration boundaries.

### Key Discoveries:
1. **Clean Baseline:** The full existing test suite passes with **53 passed** tests and **24 subtests passed** (exit code `0`) across Phase 3A, Phase 3B, and Phase 4.
2. **Untracked Core Modules:** Verified implementations exist in `code/identity/` (`resolver.py`, `integration.py`) and `code/evidence/` (`collector.py`, `reader.py`, `sql_parser.py`).
3. **Downstream Isolation:** `code/main.py` and `code/evaluation/main.py` remain empty 0-byte stubs. `output.csv` is untracked and untouched.
4. **Target Location for Phase 5:** Dedicated module `code/timeline/` (`__init__.py`, `reconstructor.py`, `test_reconstructor.py`), preserving separation of concerns.

---

## 2. Baseline Test Execution Results

Baseline regression was executed in the project virtual environment:

- **Command:** `./.venv/bin/pytest -v`
- **Working Directory:** `/Users/harsh/hackerrank-orchestrate-october26`
- **Exit Code:** `0`
- **Duration:** 10.81s
- **Test Counts by Layer:**
  - `code/evidence/test_collector.py`: **9 passed**
  - `code/evidence/test_reader.py`: **6 passed**
  - `code/evidence/test_sql_parser.py`: **9 passed** (including 24 subtests)
  - `code/identity/test_integration.py`: **22 passed**
  - `code/identity/test_resolver.py`: **7 passed**
  - **Total:** **53 passed, 24 subtests passed, 0 failures**

---

## 3. Actual Event, Identity, Evidence, and Resource Fields

Every field was audited against physical CSV headers and evidence artifacts in `dataset/`:

### 3.1 Event Stream (`dataset/system_activity.csv`)
- **Row Count:** 4,011 rows
- **Columns:**
  - `activity_id`: Unique event string (`activity_0001` to `activity_4011`)
  - `event_time`: ISO 8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`)
  - `event_type`: Categorical action (17 distinct types observed)
  - `source_system`: Originating service (`deletion_worker`, `account_service`, `backup_service`, etc.)
  - `target_system`: Receiving or target service (`search_service`, `analytics_platform`, `backup_service`, etc.)
  - `resource_id`: Subject resource reference (`account_...`, `search_...`, `data_flow_...`, `backup_...`, etc.)
  - `reported_result`: Operational status claim (`SUCCESS`, `FAILED`, `PARTIAL`)
  - `details`: Plain text or structured descriptions (e.g., status codes, error messages)

### 3.2 Identity Records
- **Current Snapshot (`dataset/user_identities.csv` - 850 rows):**
  - `user_id`: Stable subject reference (`user_01` to `user_850`)
  - `name`: Full name
  - `email`: Current primary email address
  - `phone`: Current phone number
  - `email_hash`: SHA-256 / hashed email
  - `updated_at`: Snapshot update timestamp
- **Audit History (`dataset/user_audit_log.csv` - 306 rows):**
  - `audit_id`: Unique history record ID
  - `user_id`: Subject reference
  - `event_time`: Timestamp of field modification
  - `field_name`: Modified property (`email`, `phone`, `email_hash`)
  - `old_value`: Prior value
  - `new_value`: Resulting value

### 3.3 Evidence Manifest (`dataset/evidence_files.csv` - 94 files)
- `file_id`: Unique evidence identifier (`evidence_01` to `evidence_94`)
- `file_path`: Path relative to `dataset/evidence/`
- `origin`: Category (`service_export`, `database_replica`, `log_trace`, `support_ticket`, etc.)
- `captured_at`: Evidence acquisition cutoff timestamp

### 3.4 Request Schema (`dataset/deletion_requests.csv` - 518 cases)
- `case_id`: Unique case ID (`case_33` to `case_550`)
- `email`: Request contact email (current or historical)
- `requested_at`: Deletion request submission timestamp
- `reported_status`: Workflow claim (`COMPLETE`, `PARTIALLY_COMPLETE`, `NOT_STARTED`)
- `reported_at`: Claim reporting timestamp
- `audit_at`: Evaluation cutoff timestamp
- `request_text`: User prompt in natural language (10 cases are non-deletion requests)

---

## 4. Existing Reusable Functions and Interfaces

Phase 5 will reuse without duplicating:

1. **`IdentityResolver` (`code/identity/resolver.py`):**
   - `IdentityResolver.from_directory("dataset")`: Factory loader.
   - `resolver.resolve_email(email, audit_at)`: Returns canonical `user_id` or `AMBIGUOUS`/`UNRESOLVED`.
   - `resolver.identifiers_for_user(user_id, audit_at)`: Recovers valid historical emails, hashes, phones.
   - `parse_timestamp(ts)`: Robust ISO 8601 parsing into UTC-aware `datetime`.
   - `normalize(text)`: String normalization.

2. **`EvidenceIntegrator` (`code/identity/integration.py`):**
   - Pre-cached multi-format parser (`read_evidence_file`).
   - `correlate_for_request(request, resolver)`: Grounded evidence matches, inclusive cutoff checks (`<= audit_at`), and post-cutoff exclusions (`EXCLUDED_CAPTURE_POST_CUTOFF`, `EXCLUDED_EVENT_POST_CUTOFF`).

3. **`reader.py` & `sql_parser.py` (`code/evidence/`):**
   - Static non-executing SQL parser (`parse_sql_file`).
   - Unified multi-format parser across JSON, LOG, SQL, TXT, PDF, PNG.

---

## 5. Event Types and Semantic Analysis

Analysis of 4,011 events in `system_activity.csv`:

| Event Group | Event Types Observed | Count | Semantic Role in Timeline |
|---|---|---:|---|
| **Deletion** | `DELETE_RECORD` | 890 | Marks resource deletion intent / operation. |
| **Recreation / Sync** | `SYNC_RECORD`, `INDEX_RECORD`, `UPDATE_RECORD` | 1,519 | If occurring after `DELETE_RECORD` and `<= audit_at`, proves recreation. |
| **Data Flow** | `CHECK_DATA_FLOW`, `DISABLE_DATA_FLOW` | 125 | Confirms whether connector `data_flow_...` is `enabled` or `stopped`. |
| **Backup / Restore** | `CHECK_RESTORE_ACCESS`, `BLOCK_RESTORE`, `RESTORE_BACKUP` | 65 | Proves restore risk or blocked status for `backup_...`. |
| **Policy Treatment** | `REDACT_RECORD`, `ANONYMIZE_RECORD`, `RETAIN_RECORD` | 583 | Redaction, anonymization, and mandatory retention operations. |
| **Identity Linkage** | `LINK_RESOURCE_IDENTITY` | 12 | Authoritative cross-service linkage between `user_id`/email and `resource_id`. |
| **Auxiliary** | `SEND_EMAIL`, `REFRESH_CACHE`, `CREATE_EXPORT`, `CLASSIFY_REQUEST` | 817 | Delivery, caching, and export generation events. |

---

## 6. Output Generation & Conflict Prevention

- **`output.csv`:** Root `output.csv` is neither committed nor generated yet.
- **`code/main.py`:** Reserved for Phase 9 orchestration. Currently a 0-byte file.
- **Phase 5 Guardrail:** Phase 5 will NOT write `output.csv` or implement final audit status decisions (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`), which belong to Phase 7 and Phase 9.

---

## 7. Recommended Implementation Design for Chunk 2

Phase 5 implementation will be located cleanly in:
`code/timeline/`
├── `__init__.py`
├── `reconstructor.py`
└── `test_reconstructor.py`

### Proposed Architecture for Chunk 2:
1. **Activity Indexer:**
   - Pre-index `dataset/system_activity.csv` by `resource_id`, `details` (matching emails/user_ids), and `LINK_RESOURCE_IDENTITY` mappings.
2. **Resource Correlation:**
   - Given a resolved `user_id` and verified identifiers from Phase 3B, collect:
     - Admissible evidence records from `EvidenceIntegrator`.
     - Direct activity events (`resource_id` belonging to subject).
     - Linked activity events via `LINK_RESOURCE_IDENTITY`.
3. **Chronological Reconstruction:**
   - Merge activity events and evidence sightings into a unified, UTC-sorted timeline per resource.
   - Enforce cutoff: events `<= audit_at` establish historical state; events `> audit_at` marked excluded.
4. **Lifecycle State Resolver:**
   - Detect recreation: `DELETE_RECORD` followed by `SYNC_RECORD` / `INDEX_RECORD` before `audit_at`.
   - Classify resource state at `audit_at`: `ABSENT`, `PRESENT`, `REDACTED`, `ANONYMIZED`, `ACTIVE`, `BLOCKED`.
   - Identify active data flows (`data_flow_...` enabled) and restore risks (`backup_...` restore_allowed).

---

## 8. Verified Facts vs. Assumptions

| Item | Status | Finding / Evidence |
|---|:---:|---|
| Baseline regression | **FACT** | 53 passed, 24 subtests passed, exit code 0. |
| Non-deletion cases | **FACT** | Cases 533-542 are explicit non-deletion requests; require `NOT_APPLICABLE`. |
| Reported results are claims | **FACT** | `system_activity.csv` reports SUCCESS even when replicas retain records. |
| Cutoff boundary | **FACT** | Inclusively `<= audit_at`. Post-cutoff evidence cannot justify historical state. |
| Resource state inference | **PLANNED** | Must be grounded in evidence sightings combined with activity event sequence. |

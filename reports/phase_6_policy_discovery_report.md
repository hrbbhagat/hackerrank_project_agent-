# Phase 6.1: Repository and Policy Discovery Report
## HackerRank Orchestrate (October 2026) — Ghost Data Still Exists

**Date:** 2026-10-25  
**Auditor / Engineer:** Senior Forensic Software Engineer (Antigravity IDE)  
**Runtime Model:** Gemini 3.8 Flash (Medium)  
**Task:** Phase 6.1 — Discovery and Architecture Specification for Phase 6: Policy Engine  
**Deliverable Artifact:** `reports/phase_6_policy_discovery_report.md`

---

## 1. Authoritative Source Documents Inspected

1. **`README.md` & `problem_statement.md`:**
   - Defines the three allowed deletion statuses: `COMPLETE`, `INCOMPLETE`, and `NOT_APPLICABLE`.
   - Defines allowed operations across phases (`FINDING`, `REMEDIATION`, `VERIFICATION`):
     - Findings: `REPORT_REMAINING_RECORD` (`PRESENT`), `REPORT_EXPOSED_PII` (`PRESENT`), `REPORT_ACTIVE_DATA_FLOW` (`ACTIVE`), `REPORT_RESTORE_RISK` (`ACTIVE`).
     - Remediation: `DELETE_RECORD` (`ABSENT`), `REDACT_RECORD` (`REDACTED`), `ANONYMIZE_RECORD` (`ANONYMIZED`), `DISABLE_DATA_FLOW` (`DISABLED`), `BLOCK_RESTORE` (`BLOCKED`).
     - Verification: `VERIFY_RECORD_ABSENT` (`ABSENT`), `VERIFY_RECORD_PRESENT` (`PRESENT`), `VERIFY_RECORD_REDACTED` (`REDACTED`), `VERIFY_RECORD_ANONYMIZED` (`ANONYMIZED`), `VERIFY_DATA_FLOW_DISABLED` (`DISABLED`), `VERIFY_RESTORE_BLOCKED` (`BLOCKED`).
   - Requires that `steps_json` be empty (`[]`) for `NOT_APPLICABLE` non-deletion requests.
   - For `COMPLETE`, includes only evidence-backed verification steps proving the compliant state.
   - For `INCOMPLETE`, includes findings (citing evidence), remediation actions (empty evidence ID), and post-remediation verification checks (empty evidence ID).
2. **`AGENTS.md` (§6.4 & §6.5):**
   - Mandatory policy application: "Apply `deletion_rules.csv` to every relevant record. Do not delete data that policy requires to be retained, redacted, anonymized, or preserved as a tombstone."
   - Tombstone treatment: "For an `ACCOUNT_TOMBSTONE`, preserve the stable subject reference and remove the name, email, phone, email hash, and any other direct identifiers required by the applicable `REDACT` rule."
   - Completeness definition: A deletion is complete only when every relevant copy has the required treatment, every required retained record remains available, and no active sync, import, or restore path can recreate prohibited data.
3. **Phase 5 Forensic Audit and Reconciliation Reports (`reports/phase_5_forensic_audit_report.md`, `reports/phase_5_chunk_completion_reconciliation.md`):**
   - Confirms that Phase 5 is verified complete and frozen.
   - Confirms that resource lifecycles, cutoff states, replica drifts, recreations, active flows, and restore risks are structured and ready for consumption.

---

## 2. Actual Policy Data Inspection (`dataset/deletion_rules.csv`)

### 2.1 File Structure & Schema
- **Path:** `dataset/deletion_rules.csv`
- **Total Lines:** 16 (1 header row + 15 rule rows)
- **Header Columns:** `rule_id`, `data_category`, `condition`, `required_action`
- **Missing Values:** None (0 null or blank cells across all rows)
- **Duplicate Rules:** None (`rule_01` to `rule_15` are unique primary keys)

### 2.2 Complete Rule Inventory

| Rule ID | Data Category | Condition Text | Required Action | Target Treatment Meaning |
|---|---|---|---|---|
| `rule_01` | `USER_PROFILE` | Always | `DELETE` | Entire profile record must be completely deleted (`ABSENT`). |
| `rule_02` | `SECONDARY_IDENTIFIER` | Always | `DELETE` | Secondary mapping or alias must be completely deleted (`ABSENT`). |
| `rule_03` | `SEARCH_INDEX_ENTRY` | Always | `DELETE` | Search index doc/entry must be completely deleted (`ABSENT`). |
| `rule_04` | `CACHE_ENTRY` | Always | `DELETE` | Cached session/profile data must be completely deleted (`ABSENT`). |
| `rule_05` | `SUPPORT_MESSAGE` | Conversation contains shared customer, agent, or order context that must be retained | `REDACT` | Ticket/message retained, but direct PII (name, email, phone) redacted (`REDACTED`). |
| `rule_06` | `SUPPORT_ATTACHMENT` | Attachment belongs only to the deletion subject | `DELETE` | Customer-uploaded identity/delivery files must be deleted (`ABSENT`). |
| `rule_07` | `ANALYTICS_PROFILE` | Record is still attributable to a user | `ANONYMIZE` | Event/analytics record unlinked from user identifiers (`ANONYMIZED`). |
| `rule_08` | `PRODUCT_TELEMETRY` | Record is still attributable to a user | `ANONYMIZE` | Usage telemetry stripped of user identifiers (`ANONYMIZED`). |
| `rule_09` | `USER_EXPORT` | Always | `DELETE` | User data export packages (zip/tar/json) must be deleted (`ABSENT`). |
| `rule_10` | `MARKETING_PROFILE` | Always | `DELETE` | Marketing/campaign profile must be completely deleted (`ABSENT`). |
| `rule_11` | `EMAIL_DELIVERY_LOG` | Log contains a user email address | `REDACT` | Delivery records retained, email addresses redacted (`REDACTED`). |
| `rule_12` | `SECURITY_AUDIT_LOG` | Record is within the supplied retention period | `RETAIN` | Audit logs must remain available for compliance (`PRESENT`). |
| `rule_13` | `LEGAL_HOLD_RECORD` | A supplied legal hold is active | `RETAIN` | Legal hold records must remain available (`PRESENT`). |
| `rule_14` | `BACKUP_ARCHIVE` | Restore access can be blocked | `RETAIN` | Backup archive retained, but restore access blocked (`BLOCKED`). |
| `rule_15` | `ACCOUNT_TOMBSTONE` | Account is deleted and only a stable internal user_id is needed to preserve references to retained records | `REDACT` | Retain internal `user_id` reference; redact name, email, phone, email hash (`REDACTED`). |

### 2.3 Distinct Required Actions
1. `DELETE`: Resource must be `ABSENT`.
2. `REDACT`: Resource must be `REDACTED` (prohibited direct PII removed).
3. `ANONYMIZE`: Resource must be `ANONYMIZED` (irreversibly unlinked from subject).
4. `RETAIN`: Resource must remain `PRESENT` (or `BLOCKED` for backup restore access).

---

## 3. Existing Architecture & Interface Mapping

The policy engine will sit directly downstream of Phase 5 and consume the verified data models:

```
[Phase 3A: IdentityResolver]  [Phase 4: Evidence Reader/Collector]
                 │                            │
                 └──────────────┬─────────────┘
                                ▼
               [Phase 3B: EvidenceIntegrator]
                                │
                                ▼
              [Phase 5: TimelineReconstructor]
                                │
                                ▼
                  TimelineReconstructionResult
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
       ResourceTimeline                Flow & Restore Risks
   (state_at_cutoff, category,        (active_data_flows,
    replica_drift, evidence_id)          restore_risks)
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
                    [Phase 6: Policy Engine]
                                │
                                ▼
                     PolicyEvaluationResult
```

### 3.1 Upstream Interfaces Consumed
- **Class:** `TimelineReconstructionResult` (`code/timeline/reconstructor.py`):
  - `resources: dict[str, ResourceTimeline]`: All resources reconstructed for the subject.
  - `active_data_flows: list[dict]`: Unmitigated active data flows copying user data.
  - `restore_risks: list[dict]`: Unblocked backup archives capable of restoring user data.
  - `recreation_findings: list[dict]`: Confirmed recreations post-deletion.
  - `replica_drift_findings: list[dict]`: Confirmed primary deletion vs replica retention.
  - `is_non_deletion_request: bool`: Flags non-deletion requests (e.g. `case_533` to `case_542`).
- **Class:** `ResourceTimeline`:
  - `resource_id: str`: Standardized resource identifier (e.g., `account_005`, `search_001`, `analytics_901`).
  - `system_id: str`: Owning system (e.g., `account_service`, `search_service`, `analytics_platform`).
  - `resource_category: str`: Inferred category (e.g., `USER_PROFILE`, `SEARCH_INDEX_ENTRY`, `ANALYTICS_PROFILE`, `ACCOUNT_TOMBSTONE`, `SECURITY_AUDIT_LOG`).
  - `state_at_cutoff: str`: Empirical state (`PRESENT`, `ABSENT`, `REDACTED`, `ANONYMIZED`, `ACTIVE`, `BLOCKED`).
  - `latest_admissible_evidence_id: str`: Evidence ID proving the state at cutoff.
  - `replica_drift: bool`: True if replica snapshot retains record despite reported deletion.
  - `is_recreated: bool`: True if post-deletion recreation occurred.

---

## 4. Phase 6 Boundary Definition

To prevent leakage across architectural phases:
- **Phase 6 Scope (Policy Engine):**
  - Ingests `dataset/deletion_rules.csv`.
  - Determines the applicable rule and required treatment for every resource.
  - Evaluates whether the observed resource state satisfies the policy requirement (Compliant vs Non-Compliant).
  - Identifies specific policy violations:
    - Remaining record that should have been deleted -> Violation (`REPORT_REMAINING_RECORD`)
    - Exposed PII in a record that should have been redacted or anonymized -> Violation (`REPORT_EXPOSED_PII`)
    - Missing record that policy requires to be retained -> Violation (`REPORT_MISSING_RETAINED_RECORD`)
    - Active data flow that can recreate data -> Violation (`REPORT_ACTIVE_DATA_FLOW`)
    - Restore risk that can bring back data -> Violation (`REPORT_RESTORE_RISK`)
- **Strict Exclusions from Phase 6:**
  - Does **NOT** assign case-level deletion statuses (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`) — reserved for **Phase 7: Audit Engine**.
  - Does **NOT** generate ordered remediation steps or verification steps — reserved for **Phase 8: Step Planner**.
  - Does **NOT** generate or format `output.csv` — reserved for **Phase 9: Output Generation**.
  - Does **NOT** modify `code/main.py` or write to `output.csv`.

---

## 5. Chunk-by-Chunk Implementation Plan (Chunks 6.2 – 6.10)

| Chunk | Title | Scope & Acceptance Criteria |
|---|---|---|
| **Chunk 6.2** | Policy Rule Ingestion & Loader | Implement `PolicyRule` dataclass and `PolicyLoader` to parse `dataset/deletion_rules.csv`. Verify all 15 rules loaded with exact category, condition, and action. |
| **Chunk 6.3** | Resource Category Matching | Implement deterministic mapping from resource IDs, system IDs, and evidence context to policy `data_category` (handling ambiguous support attachments vs messages). |
| **Chunk 6.4** | Direct Deletion Policy Evaluation | Evaluate `DELETE` rules (`rule_01`, `rule_02`, `rule_03`, `rule_04`, `rule_06`, `rule_09`, `rule_10`). If `state == ABSENT`, compliant; if `state == PRESENT`, flag `REPORT_REMAINING_RECORD`. |
| **Chunk 6.5** | Redaction & Tombstone Policy Evaluation | Evaluate `REDACT` rules (`rule_05`, `rule_11`, `rule_15`). Verify `ACCOUNT_TOMBSTONE` preserves internal `user_id` while redacting PII. If PII exposed, flag `REPORT_EXPOSED_PII`. |
| **Chunk 6.6** | Anonymization Policy Evaluation | Evaluate `ANONYMIZE` rules (`rule_07`, `rule_08`). If record unlinked (`ANONYMIZED`), compliant; if user attributable (`PRESENT`), flag `REPORT_EXPOSED_PII`. |
| **Chunk 6.7** | Retention Policy Evaluation | Evaluate `RETAIN` rules (`rule_12`, `rule_13`, `rule_14`). Ensure mandatory security audit logs and legal hold records remain `PRESENT`. |
| **Chunk 6.8** | Active Flow & Restore Risk Evaluation | Evaluate integration flows and backup restore risks. Active unmitigated flows trigger `REPORT_ACTIVE_DATA_FLOW`; unblocked restore candidates trigger `REPORT_RESTORE_RISK`. |
| **Chunk 6.9** | Policy Unit & Integration Test Suite | Add comprehensive test suite in `code/policy/test_engine.py` covering all 15 rules, compliant cases, violation cases, tombstone boundary checks, and full regression runs. |
| **Chunk 6.10** | Full-Dataset Policy Evaluation & Audit | Execute policy evaluation across all 518 evaluation requests, aggregate policy compliance metrics, verify zero regressions on existing 81 tests, and produce Phase 6 audit report. |

---

## 6. Risks & Key Technical Questions Resolved

1. **How to differentiate `SUPPORT_MESSAGE` (REDACT) from `SUPPORT_ATTACHMENT` (DELETE)?**
   - In `dataset/evidence/`, support tickets contain conversations (`support_ticket_*.txt`), while attachment evidence files are images/PDFs (`support_attachment_*.png` or `*.pdf`).
   - Resource IDs like `support_attachment_*` map to `SUPPORT_ATTACHMENT` (`DELETE`), while ticket/message records map to `SUPPORT_MESSAGE` (`REDACT`).
2. **How to differentiate `ACCOUNT_TOMBSTONE` from ordinary `USER_PROFILE`?**
   - Resource ID prefix `tombstone_*` or records where only stable `user_id` is retained while `name`, `email`, `phone` are null/redacted map to `ACCOUNT_TOMBSTONE` (`REDACT`).
   - Profile records under `account_service` with full PII map to `USER_PROFILE` (`DELETE`).
3. **What is the compliance condition for `BACKUP_ARCHIVE`?**
   - `rule_14`: "Restore access can be blocked" -> `RETAIN`.
   - If restore access is blocked (`BLOCKED`), the archive is compliant. If restore risk is active (`ACTIVE`), policy evaluation flags a restore risk.

---

## 7. Completion Gate

- [x] All authoritative project source documents inspected (`README.md`, `problem_statement.md`, `AGENTS.md`, Phase 3B/4/5 reports).
- [x] `dataset/deletion_rules.csv` fully inspected (15 rules, 4 columns, 0 nulls, 4 action types).
- [x] Upstream interfaces mapped (`TimelineReconstructionResult`, `ResourceTimeline`).
- [x] Strict phase boundaries defined (no Phase 7/8/9 logic in Phase 6).
- [x] Chunks 6.2–6.10 acceptance criteria established.
- [x] Zero production code modified during discovery.

**Phase 6.1 Status:** **COMPLETE** — Ready to proceed to **Chunk 6.2: Policy Rule Ingestion & Loader**.

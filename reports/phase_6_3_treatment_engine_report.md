# Phase 6.3: Deterministic Resource-Treatment Engine Report

**Module:** `code/policy/engine.py`, `code/policy/__init__.py`, `code/policy/test_engine.py`  
**Execution Date:** 2026-10-25T04:42:00+05:30  
**Status:** COMPLETE & VERIFIED  

---

## 1. Executive Summary

Phase 6.3 establishes the **Deterministic Resource-Treatment Engine** for the HackerRank Orchestrate "Ghost Data Still Exists" challenge.

The policy evaluator operates on top of the validated Phase 6.2 `PolicyLoader` schema. It provides typed, deterministic evaluation of whether an observed resource state at the case's audit cutoff complies with governing policy rules (`DELETE`, `REDACT`, `ANONYMIZE`, `RETAIN`) as well as infrastructure recreation entities (`DATA_FLOW`, `BACKUP_ARCHIVE`).

Strict architectural boundaries are maintained:
- **Zero LLM dependency:** Evaluation is 100% deterministic, reproducible, and explainable.
- **Separation of concerns:** The engine outputs resource-level decisions (`ResourceTreatmentDecision`). It **does not** compute case-level deletion verdicts (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`), which are strictly reserved for Phase 7 (Audit Engine).
- **No Remediation Planning:** It **does not** construct step sequences or write `output.csv`, which are strictly reserved for Phase 8 (Step Planner) and Phase 9 (Pipeline Packaging).
- **Evidence Grounding:** The engine preserves and validates authentic evidence IDs and activity IDs, never fabricating evidence markers or treating absence of evidence as proof of non-existence.
- **Uncertainty Isolation:** Any missing policy rule, unknown resource state, ambiguous contextual match, or contradictory rule is mapped explicitly to `INDETERMINATE`.

---

## 2. Resource-Level Decision Contract

The interface consumed by downstream layers (Phase 7 Audit Engine and Phase 8 Step Planner) is the immutable, typed dataclass `ResourceTreatmentDecision`:

```python
@dataclass(frozen=True)
class ResourceTreatmentDecision:
    resource_id: str                          # e.g. "account_005", "support_864"
    system_id: str                            # e.g. "account_service", "support_platform"
    data_category: str                        # e.g. "USER_PROFILE", "SUPPORT_MESSAGE"
    rule_id: Optional[str]                    # Governing rule (e.g. "rule_01") or None
    required_action: Optional[str]            # "DELETE", "REDACT", "ANONYMIZE", "RETAIN", "DISABLE_DATA_FLOW"
    observed_state: str                       # State at cutoff: ABSENT, PRESENT, REDACTED, ANONYMIZED, etc.
    compliance_result: ComplianceResult       # COMPLIANT | NON_COMPLIANT | INDETERMINATE | NOT_APPLICABLE
    reason: str                               # Grounded policy and evidence explanation
    evidence_id: Optional[str] = None         # Cites authentic file_id or activity_id proving the state
    diagnostics: list[str] = field(default_factory=list) # Traceability and ambiguity notes
```

---

## 3. Treatment Semantics & Decision Table

The evaluator implements the authoritative semantics across all four policy actions plus active data flows:

| Action / Entity | Data Category | Required Condition | Observed State | Compliance Result | Meaning / Rationale |
|---|---|---|---|---|---|
| **DELETE** | `USER_PROFILE`, `SECONDARY_IDENTIFIER`, `SEARCH_INDEX_ENTRY`, `CACHE_ENTRY`, `SUPPORT_ATTACHMENT`, `USER_EXPORT`, `MARKETING_PROFILE` | Record prohibited | `ABSENT` | **COMPLIANT** | Record completely absent at cutoff. |
| **DELETE** | *(same as above)* | Record prohibited | `PRESENT` | **NON_COMPLIANT** | Record still exists; policy violation. |
| **DELETE** | *(same as above)* | Record prohibited | `REDACTED` / `ANONYMIZED` | **NON_COMPLIANT** | Record must be deleted, not kept redacted/anonymized. |
| **REDACT** | `SUPPORT_MESSAGE`, `EMAIL_DELIVERY_LOG`, `ACCOUNT_TOMBSTONE` | Direct PII prohibited | `REDACTED` | **COMPLIANT** | Direct identifiers safely removed; stable reference preserved. |
| **REDACT** | *(same as above)* | Direct PII prohibited | `ABSENT` | **COMPLIANT** | Complete removal is strictly compliant with redaction. |
| **REDACT** | *(same as above)* | Direct PII prohibited | `PRESENT` | **NON_COMPLIANT** | Direct identifiers (email/phone/hash) remain exposed. |
| **ANONYMIZE** | `ANALYTICS_PROFILE`, `PRODUCT_TELEMETRY` | Irreversible unlinking | `ANONYMIZED` | **COMPLIANT** | Record unlinked from subject identifiers. |
| **ANONYMIZE** | *(same as above)* | Irreversible unlinking | `ABSENT` | **COMPLIANT** | Complete deletion is compliant. |
| **ANONYMIZE** | *(same as above)* | Irreversible unlinking | `PRESENT` | **NON_COMPLIANT** | Record still attributable to subject. |
| **RETAIN** | `SECURITY_AUDIT_LOG`, `LEGAL_HOLD_RECORD` | Mandatory retention | `PRESENT` | **COMPLIANT** | Mandatory record preserved as required by law/policy. |
| **RETAIN** | *(same as above)* | Mandatory retention | `ABSENT` | **NON_COMPLIANT** | Mandatory record prematurely deleted. |
| **RETAIN** | `BACKUP_ARCHIVE` | Restore blocked | `BLOCKED` / `DISABLED` | **COMPLIANT** | Backup retained but restore access safely blocked. |
| **RETAIN** | `BACKUP_ARCHIVE` | Restore blocked | `ACTIVE` / `PRESENT` | **NON_COMPLIANT** | Backup can restore deleted personal data (restore risk). |
| **FLOW** | `DATA_FLOW` | Synchronization stopped | `DISABLED` / `BLOCKED` | **COMPLIANT** | Active sync disabled; no data recreation risk. |
| **FLOW** | `DATA_FLOW` | Synchronization stopped | `ACTIVE` | **NON_COMPLIANT** | Active data flow can copy/recreate deleted records. |
| **ANY** | Any Category | Any Treatment | `UNKNOWN` / `INDETERMINATE` | **INDETERMINATE** | State cannot be proven from evidence at cutoff. |
| **ANY** | Unregistered Category | Any Treatment | Any State | **INDETERMINATE** | No governing rule exists in policy ruleset. |

---

## 4. Resource Category Matching & Disambiguation

The engine resolves categories deterministically:
1. **Explicit Sighting Metadata:** Takes priority if explicitly indicated in evidence (e.g. `SUPPORT_ATTACHMENT` vs `SUPPORT_MESSAGE` in handover sheets or database schemas).
2. **Contextual Disambiguation for `support_*`:**
   - Resources associated with file attachments, PDFs, or upload records map to `SUPPORT_ATTACHMENT` (`rule_06`, `DELETE`).
   - Resources associated with ticket messages, chat conversations, or support logs map to `SUPPORT_MESSAGE` (`rule_05`, `REDACT`).
3. **Contextual Disambiguation for `analytics_*`:**
   - Mapped to `ANALYTICS_PROFILE` (`rule_07`, `ANONYMIZE`), or `MARKETING_PROFILE` (`rule_10`, `DELETE`) if marketing cohort context is present.
4. **Deterministic Prefix Mapping:** Standard system-to-category associations (`account_*` -> `USER_PROFILE`, `search_*` -> `SEARCH_INDEX_ENTRY`, `backup_*` -> `BACKUP_ARCHIVE`, `tombstone_*` -> `ACCOUNT_TOMBSTONE`, `audit_record_*` -> `SECURITY_AUDIT_LOG`).

---

## 5. Verification & Test Results

### 5.1 Focused Treatment Engine Suite (`code/policy/test_engine.py`)
- **21 unit tests executed:**
  - `test_01_delete_treatment_compliant_when_absent`: PASSED
  - `test_02_delete_treatment_non_compliant_when_present`: PASSED
  - `test_03_delete_treatment_non_compliant_if_retained_redacted`: PASSED
  - `test_04_redact_treatment_compliant_when_redacted`: PASSED
  - `test_05_redact_treatment_compliant_when_absent`: PASSED
  - `test_06_redact_treatment_non_compliant_when_present`: PASSED
  - `test_07_anonymize_treatment_compliant_when_anonymized`: PASSED
  - `test_08_anonymize_treatment_non_compliant_when_present`: PASSED
  - `test_09_retain_treatment_compliant_when_present`: PASSED
  - `test_10_retain_treatment_non_compliant_when_absent`: PASSED
  - `test_11_backup_archive_compliant_when_blocked`: PASSED
  - `test_12_backup_archive_non_compliant_when_active`: PASSED
  - `test_13_data_flow_compliant_when_disabled`: PASSED
  - `test_14_data_flow_non_compliant_when_active`: PASSED
  - `test_15_uncertainty_missing_policy_rule`: PASSED
  - `test_16_uncertainty_unknown_observed_state`: PASSED
  - `test_17_uncertainty_unsupported_state_for_action`: PASSED
  - `test_18_uncertainty_conflicting_rules`: PASSED
  - `test_19_support_disambiguation`: PASSED
  - `test_20_repeat_run_determinism`: PASSED
  - `test_21_non_mutation_of_inputs`: PASSED
- **Result:** 21 passed in 0.001s.

### 5.2 Combined Policy Module Suite (`code/policy/`)
- **33 tests executed** (12 loader tests + 21 engine tests).
- **Result:** 33 passed in 0.02s.

### 5.3 Full Repository Regression Suite (`pytest code/ -q`)
- **Total Tests Collected & Passed:** **114 passed, 24 subtests passed in 21.74s (exit code 0)**.
- **Breakdown:**
  - `code/evidence/test_collector.py`: 9 passed
  - `code/evidence/test_reader.py`: 6 passed
  - `code/evidence/test_sql_parser.py`: 9 passed, 24 subtests passed
  - `code/identity/test_resolver.py`: 7 passed
  - `code/identity/test_integration.py`: 22 passed
  - `code/timeline/test_reconstructor.py`: 28 passed
  - `code/policy/test_loader.py`: 12 passed
  - `code/policy/test_engine.py`: 21 passed
- **Failures / Regressions:** 0.
- **Git Status:** Clean tracked files (`git diff HEAD` is empty).

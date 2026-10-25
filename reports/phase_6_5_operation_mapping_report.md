# Phase 6.5: Policy-to-Challenge Operation Mapping Report

**Module:** `code/policy/mapper.py`, `code/policy/__init__.py`, `code/policy/test_mapper.py`  
**Execution Date:** 2026-10-25T05:04:00+05:30  
**Status:** COMPLETE & VERIFIED  

---

## 1. Executive Summary

Phase 6.5 implements the authoritative, validated translation layer between resource-level policy decisions (from `TreatmentEngine`) and the exact operational step vocabulary defined by HackerRank Orchestrate: Ghost Data Still Exists (`AGENTS.md` §6.3–6.4).

Key architectural guarantees:
- **Strict Vocabulary Enforcement:** Enforces the closed set of 15 challenge operations across 3 phases (`FINDING`, `REMEDIATION`, `VERIFICATION`) and 7 allowed states. Any invalid name or combination is strictly rejected at instantiation.
- **Zero Hallucination / Safe Retention:** Missing retained records (`SECURITY_AUDIT_LOG`) are surfaced via diagnostics without inventing unapproved operations like `RESTORE_RECORD`.
- **Clean Decoupling:** Does not declare case status (`COMPLETE` / `INCOMPLETE`) or perform step numbering and JSON serialization, which belong to Phase 7 and Phase 8 respectively.

---

## 2. Authoritative Step Vocabulary Contract

`PERMITTED_COMBINATIONS` in `code/policy/mapper.py` serves as the single source of truth:

```python
PERMITTED_COMBINATIONS: set[tuple[str, str, str]] = {
    # Findings (4)
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),

    # Remediation (5)
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),

    # Verification (6)
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
}
```

---

## 3. Mapping Semantics

| Trigger / Condition | Category / Entity | Phase | Operation | State | Evidence Attribution |
|---|---|---|---|---|---|
| **DELETE Violation** | `USER_PROFILE`, `SEARCH_INDEX_ENTRY`, `USER_EXPORT`, etc. | FINDING | `REPORT_REMAINING_RECORD` | `PRESENT` | Cites proving evidence ID |
| | | REMEDIATION | `DELETE_RECORD` | `ABSENT` | `""` (future proposed action) |
| | | VERIFICATION | `VERIFY_RECORD_ABSENT` | `ABSENT` | `""` (post-remediation check) |
| **DELETE Compliant** | *(same)* | VERIFICATION | `VERIFY_RECORD_ABSENT` | `ABSENT` | Cites proving evidence ID |
| **REDACT Violation** | `SUPPORT_MESSAGE`, `ACCOUNT_TOMBSTONE`, `EMAIL_DELIVERY_LOG` | FINDING | `REPORT_EXPOSED_PII` | `PRESENT` | Cites proving evidence ID |
| | | REMEDIATION | `REDACT_RECORD` | `REDACTED` | `""` |
| | | VERIFICATION | `VERIFY_RECORD_REDACTED` | `REDACTED` | `""` |
| **REDACT Compliant** | *(same)* | VERIFICATION | `VERIFY_RECORD_REDACTED` | `REDACTED` | Cites proving evidence ID |
| **ANONYMIZE Violation**| `ANALYTICS_PROFILE`, `PRODUCT_TELEMETRY` | FINDING | `REPORT_EXPOSED_PII` | `PRESENT` | Cites proving evidence ID |
| | | REMEDIATION | `ANONYMIZE_RECORD` | `ANONYMIZED` | `""` |
| | | VERIFICATION | `VERIFY_RECORD_ANONYMIZED`| `ANONYMIZED` | `""` |
| **ANONYMIZE Compliant**| *(same)* | VERIFICATION | `VERIFY_RECORD_ANONYMIZED`| `ANONYMIZED` | Cites proving evidence ID |
| **RETAIN Compliant** | `SECURITY_AUDIT_LOG`, `LEGAL_HOLD_RECORD` | VERIFICATION | `VERIFY_RECORD_PRESENT` | `PRESENT` | Cites proving evidence ID |
| **RETAIN Violation** | *(same, but prematurely ABSENT)* | *None* | *None (Diagnostic only)* | *None* | Surfaced in `diagnostics` |
| **Active Flow Risk** | `DATA_FLOW` | FINDING | `REPORT_ACTIVE_DATA_FLOW` | `ACTIVE` | Cites proving evidence ID |
| | | REMEDIATION | `DISABLE_DATA_FLOW` | `DISABLED` | `""` |
| | | VERIFICATION | `VERIFY_DATA_FLOW_DISABLED` | `DISABLED` | `""` |
| **Restore Risk** | `BACKUP_ARCHIVE` | FINDING | `REPORT_RESTORE_RISK` | `ACTIVE` | Cites proving evidence ID |
| | | REMEDIATION | `BLOCK_RESTORE` | `BLOCKED` | `""` |
| | | VERIFICATION | `VERIFY_RESTORE_BLOCKED` | `BLOCKED` | `""` |

---

## 4. Verification & Test Suite

### 4.1 Focused Mapper Suite (`code/policy/test_mapper.py`)
- **11 unit tests executed:**
  - `test_01_authoritative_permitted_combinations_count`: PASSED (exactly 15 allowed triples)
  - `test_02_rejection_of_invalid_combinations`: PASSED (rejects invalid operations, states, and phase combinations)
  - `test_03_delete_violation_mapping`: PASSED (`REPORT_REMAINING_RECORD`, `DELETE_RECORD`, `VERIFY_RECORD_ABSENT`)
  - `test_04_delete_compliant_mapping`: PASSED (`VERIFY_RECORD_ABSENT` with evidence citing)
  - `test_05_redact_violation_mapping`: PASSED (`REPORT_EXPOSED_PII`, `REDACT_RECORD`, `VERIFY_RECORD_REDACTED`)
  - `test_06_anonymize_violation_mapping`: PASSED (`REPORT_EXPOSED_PII`, `ANONYMIZE_RECORD`, `VERIFY_RECORD_ANONYMIZED`)
  - `test_07_retain_compliant_mapping`: PASSED (`VERIFY_RECORD_PRESENT`)
  - `test_08_retain_missing_record_no_invented_restore`: PASSED (no unapproved operation invented)
  - `test_09_active_data_flow_mapping`: PASSED (`REPORT_ACTIVE_DATA_FLOW`, `DISABLE_DATA_FLOW`, `VERIFY_DATA_FLOW_DISABLED`)
  - `test_10_restore_risk_mapping`: PASSED (`REPORT_RESTORE_RISK`, `BLOCK_RESTORE`, `VERIFY_RESTORE_BLOCKED`)
  - `test_11_tombstone_compliant_mapping`: PASSED (`VERIFY_RECORD_REDACTED`)
- **Result:** 11 passed in 0.001s.

### 4.2 Combined Policy Package Suite (`code/policy/`)
- **53 unit tests passed in 0.04s** (12 loader tests + 30 engine tests + 11 mapper tests).

### 4.3 Full Repository Regression Suite (`pytest code/ -q`)
- **134 passed, 24 subtests passed in 21.08s (exit code 0)**.
- **Failures / Regressions:** 0.
- **Git Status:** Clean tracked files (`git diff HEAD` is empty).

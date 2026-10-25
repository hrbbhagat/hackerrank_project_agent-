# Phase 6.4: Mandatory Retention, Account Tombstones, and Exceptions Report

**Module:** `code/policy/engine.py`, `code/policy/__init__.py`, `code/policy/test_engine.py`  
**Execution Date:** 2026-10-25T05:00:00+05:30  
**Status:** COMPLETE & VERIFIED  

---

## 1. Executive Summary

Phase 6.4 extends the Phase 6 deterministic policy evaluator to rigorously handle **mandatory retention**, **account tombstones**, and **policy condition / exception evaluation**.

The implementation directly operationalizes the challenge specification:
> *"The dataset models a commerce platform where a workflow can report Complete while personal data remains... It must preserve records required by policy and correctly handle account tombstones whose stable internal user reference remains while prohibited direct identifiers are removed."* (`AGENTS.md` §1)
> *"For an ACCOUNT_TOMBSTONE, preserve the stable subject reference and remove the name, email, phone, email hash, and any other direct identifiers required by the applicable REDACT rule."* (`AGENTS.md` §6.5)

---

## 2. Mandatory Retention & Exception Logic

### 2.1 Behaviors Explicitly Required by Challenge & Policy

1. **Governing Rules:**
   - `rule_12`: `SECURITY_AUDIT_LOG` — Condition: `"Record is within the supplied retention period"`, Action: `RETAIN`.
   - `rule_13`: `LEGAL_HOLD_RECORD` — Condition: `"A supplied legal hold is active"`, Action: `RETAIN`.
   - `rule_14`: `BACKUP_ARCHIVE` — Condition: `"Restore access can be blocked"`, Action: `RETAIN`.

2. **Retention Compliance Rules:**
   - A policy-required retained record (`SECURITY_AUDIT_LOG`, `LEGAL_HOLD_RECORD`) must be `PRESENT` at the audit cutoff.
   - If the required retained record is `ABSENT`, it is evaluated as **`NON_COMPLIANT`** (premature deletion). Downstream Phase 8 step planning will never recommend deleting a record that policy requires to be retained.
   - For `BACKUP_ARCHIVE`, retention is compliant only when restore access is `BLOCKED` or `DISABLED`. If restore access is `ACTIVE`, it is flagged as **`NON_COMPLIANT`** (unmitigated restore risk).

3. **Condition & Exception Handling:**
   - **Retention Period:** When context indicates that a security audit record is outside the retention period (`within_retention_period is False`), retention does not protect it from deletion; the condition fails and non-compliance is raised.
   - **Legal Hold:** When a legal hold is inactive (`legal_hold_active is False`), `rule_13` does not mandate retention, returning `NOT_APPLICABLE` for that rule.
   - **Restrictions on Identifying Contents:** Even when a record is retained (e.g. security audit log), prohibited sensitive direct credentials (e.g. unhashed passwords, raw credentials, payment card numbers) must not be exposed. If found, a non-compliance violation is issued.

---

## 3. Account Tombstone Semantics

### 3.1 Behaviors Required by Challenge & Policy

1. **Governing Rule:**
   - `rule_15`: `ACCOUNT_TOMBSTONE` — Condition: `"Account is deleted and only a stable internal user_id is needed to preserve references to retained records"`, Action: `REDACT`.

2. **Field-Level Inspection (`inspect_tombstone_fields`):**
   - **Permitted Stable Reference:** Must retain a stable internal identifier (`subject_reference`, `user_id`, `userid`, `customer_id`, `customer_reference`). If missing, it is non-compliant.
   - **Prohibited Direct Identifiers:** Direct personal identifiers (`name`, `full_name`, `email`, `email_address`, `phone`, `phone_number`, `email_hash`, `emailhash`) must be absent or null/empty. If any non-null string value remains, it is non-compliant (`REPORT_EXPOSED_PII`).
   - **Field Alias Normalization:** Normalizes snake_case, camelCase, uppercase, and hyphenated variations (e.g., `emailHash`, `email_hash`, `EMAIL`, `phoneNumber`, `phone_number`) without indiscriminately discarding fields containing the word `user` (e.g. `user_id` is preserved).
   - **Preserved `user_id` Is Not a Violation:** Does not automatically classify a preserved internal `user_id` or `subject_reference` in a tombstone as a violation.

---

## 4. Verification & Test Results

### 4.1 Extended Policy Evaluator Suite (`code/policy/test_engine.py`)
- **30 unit tests executed:**
  - Tests 1–21: Direct treatments (`DELETE`, `REDACT`, `ANONYMIZE`, `RETAIN`, `DATA_FLOW`), uncertainty handling, and support disambiguation.
  - `test_22_tombstone_compliant_with_stable_reference`: PASSED (compliant tombstone with `user_541` preserved and null PII).
  - `test_23_tombstone_non_compliant_with_exposed_pii`: PASSED (detects exposed name, email, phone, and email_hash).
  - `test_24_tombstone_missing_stable_reference`: PASSED (detects orphan tombstone lacking stable user ID).
  - `test_25_tombstone_field_aliases_and_casing`: PASSED (detects `emailHash`, `phoneNumber`, `EMAIL`).
  - `test_26_retained_record_correctly_preserved`: PASSED (`SECURITY_AUDIT_LOG` present within retention period).
  - `test_27_required_retained_record_missing`: PASSED (flags premature deletion of retained log).
  - `test_28_retention_condition_outside_period`: PASSED (flags record past retention period).
  - `test_29_retention_legal_hold_inactive`: PASSED (returns `NOT_APPLICABLE` when legal hold is inactive).
  - `test_30_retained_record_with_prohibited_sensitive_fields`: PASSED (flags prohibited raw credentials in retained record).
- **Result:** 30 passed in 0.001s.

### 4.2 Combined Policy Package Suite (`code/policy/`)
- **42 tests executed** (12 loader tests + 30 engine tests).
- **Result:** 42 passed in 0.03s.

### 4.3 Full Repository Regression Suite (`pytest code/ -q`)
- **Total Tests Collected & Passed:** **123 passed, 24 subtests passed in 26.89s (exit code 0)**.
- **Failures / Regressions:** 0.
- **Git Status:** Clean tracked files (`git diff HEAD` is empty). No modifications to `code/main.py` or `output.csv`.

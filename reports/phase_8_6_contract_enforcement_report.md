# Phase 8.6 Engineering Report: Strict Operation, State, and Phase Contract Enforcement

## 1. Executive Summary & Verdict

- **Phase:** 8.6 — Strict Operation, State, and Phase Contract Enforcement
- **Date & Cutoff Context:** 2026-10-25
- **Role:** Senior Platform Engineer and Software Quality Architect
- **Verdict:** `PASS`
- **Scope Compliance:** Phase 8.6 only. Established centralized, authoritative contract validation in `code/planner/contract.py`, integrated seamlessly with `models.py`, `validator.py`, and `__init__.py`. Tested all 15 valid combinations, all 300 invalid combinations from valid vocabularies, mutated casing/whitespace, missing fields, extra fields, invalid field types, and canonical intra-phase ordering. No dataset files modified; `output.csv` ungenerated.

---

## 2. Authoritative Challenge Contract Matrix

Extracted directly from `problem_statement.md` (§ "Allowed Operations") and `AGENTS.md` §6.4:

### 2.1 Complete Vocabulary

1. **Phases (3):**
   - `FINDING`
   - `REMEDIATION`
   - `VERIFICATION`

2. **Operations (15):**
   - Findings (4): `REPORT_REMAINING_RECORD`, `REPORT_EXPOSED_PII`, `REPORT_ACTIVE_DATA_FLOW`, `REPORT_RESTORE_RISK`
   - Remediation (5): `DISABLE_DATA_FLOW`, `BLOCK_RESTORE`, `DELETE_RECORD`, `REDACT_RECORD`, `ANONYMIZE_RECORD`
   - Verification (6): `VERIFY_RECORD_ABSENT`, `VERIFY_RECORD_PRESENT`, `VERIFY_RECORD_REDACTED`, `VERIFY_RECORD_ANONYMIZED`, `VERIFY_DATA_FLOW_DISABLED`, `VERIFY_RESTORE_BLOCKED`

3. **States (7):**
   - `PRESENT`, `ACTIVE`, `DISABLED`, `BLOCKED`, `ABSENT`, `REDACTED`, `ANONYMIZED`

4. **Output Schema Fields (7):**
   - `step_no` (int >= 1, boolean strictly rejected)
   - `phase` (str)
   - `system_id` (str, non-empty, non-whitespace)
   - `resource_id` (str, non-empty, non-whitespace)
   - `operation` (str)
   - `state` (str)
   - `evidence_id` (str)

### 2.2 Complete 15 Permitted Triples Table

| # | Phase | Operation | State | Canonical Index | Challenge Semantic Meaning |
|---|---|---|---|---|---|
| 1 | `FINDING` | `REPORT_REMAINING_RECORD` | `PRESENT` | 1 | A record that should have been deleted still exists. |
| 2 | `FINDING` | `REPORT_EXPOSED_PII` | `PRESENT` | 2 | A record may remain, but it still contains identifiers that should have been redacted or anonymized. |
| 3 | `FINDING` | `REPORT_ACTIVE_DATA_FLOW` | `ACTIVE` | 3 | An active process can copy or recreate the user's data. |
| 4 | `FINDING` | `REPORT_RESTORE_RISK` | `ACTIVE` | 4 | A backup or restore path can bring deleted data back. |
| 5 | `REMEDIATION` | `DISABLE_DATA_FLOW` | `DISABLED` | 1 | Stop the process that can copy or recreate the data. |
| 6 | `REMEDIATION` | `BLOCK_RESTORE` | `BLOCKED` | 2 | Prevent the affected backup from restoring the user's data. |
| 7 | `REMEDIATION` | `DELETE_RECORD` | `ABSENT` | 3 | Remove the entire record. |
| 8 | `REMEDIATION` | `REDACT_RECORD` | `REDACTED` | 4 | Keep the record but remove the identifying fields required by policy. |
| 9 | `REMEDIATION` | `ANONYMIZE_RECORD` | `ANONYMIZED` | 5 | Keep the record after irreversibly unlinking it from the user. |
| 10 | `VERIFICATION` | `VERIFY_RECORD_ABSENT` | `ABSENT` | 1 | Confirm that a record no longer exists. |
| 11 | `VERIFICATION` | `VERIFY_RECORD_PRESENT` | `PRESENT` | 2 | Confirm that a policy-required retained record still exists. |
| 12 | `VERIFICATION` | `VERIFY_RECORD_REDACTED` | `REDACTED` | 3 | Confirm that required identifying fields have been removed. |
| 13 | `VERIFICATION` | `VERIFY_RECORD_ANONYMIZED` | `ANONYMIZED` | 4 | Confirm that the record can no longer be linked to the user. |
| 14 | `VERIFICATION` | `VERIFY_DATA_FLOW_DISABLED` | `DISABLED` | 5 | Confirm that the relevant data flow is inactive. |
| 15 | `VERIFICATION` | `VERIFY_RESTORE_BLOCKED` | `BLOCKED` | 6 | Confirm that the affected data cannot be restored. |

Every operation in the challenge maps strictly to **exactly one valid phase** and **exactly one valid state**.

---

## 3. Implementation Details

### 3.1 Centralized Contract Module (`code/planner/contract.py`)

1. **Enumerations & Sets:**
   - `StepPhase`, `StepOperation`, `StepState` with strict string Enum backing.
   - `PERMITTED_PHASES`: frozenset of the 3 phases.
   - `PERMITTED_OPERATIONS`: frozenset of the 15 operations.
   - `PERMITTED_STATES`: frozenset of the 7 states.
   - `PERMITTED_COMBINATIONS`: frozenset of the exact 15 allowed `(phase, operation, state)` triples.
   - `REQUIRED_STEP_FIELDS`: tuple of the exact 7 contract field names in order.

2. **Mappings & Canonical Ordering:**
   - `OPERATION_TO_PHASE`: maps every operation to its single permitted phase.
   - `OPERATION_TO_STATE`: maps every operation to its single permitted state.
   - `PHASE_TO_OPERATIONS`: maps each phase to its permitted operations.
   - `OPERATION_CANONICAL_INDEX`: encodes the exact intra-phase sort order specified by `problem_statement.md` table order.

3. **Authoritative Validator Engine (`StepContractValidator`):**
   - `is_valid_phase(phase) -> bool`
   - `is_valid_operation(operation) -> bool`
   - `is_valid_state(state) -> bool`
   - `is_valid_combination(phase, operation, state) -> bool`
   - `get_expected_phase(operation) -> Optional[str]`
   - `get_expected_state(operation) -> Optional[str]`
   - `validate_phase(phase) -> list[str]`
   - `validate_operation(operation) -> list[str]`
   - `validate_state(state) -> list[str]`
   - `validate_semantic_combination(phase, operation, state) -> list[str]`
   - `validate_step_fields(data, allow_extra=False) -> list[str]`
   - `validate_step(step_or_dict, allow_extra=False) -> ContractValidationResult`

4. **Zero Tolerance for Normalization or Aliases:**
   - Lowercase or mixed case (`"finding"`, `"delete_record"`) is rejected.
   - Whitespace padding (`" PRESENT "`) is rejected.
   - Invented operations (`"RESTORE_RECORD"`, `"PURGE_DATA"`) are rejected.
   - Extra fields when `allow_extra=False` are rejected with `ExtraFieldsError`.

### 3.2 Integration with Existing Planner Modules

- `code/planner/models.py`: imports all contract enumerations, exceptions, and sets from `contract.py`. Re-exports them to preserve full backward compatibility with Phases 8.2–8.5.
- `code/planner/validator.py`: integrates `StepContractValidator`, exposing `validate_contract`, `validate_combination`, `is_valid_combination`, `is_valid_phase`, `is_valid_operation`, and `is_valid_state` on `StepValidator`.
- `code/planner/__init__.py`: exports all contract models, sets, mappings, and validators.

---

## 4. Exhaustive Test Suite & Verification Results

### 4.1 Test Coverage in `code/planner/test_contract.py` (384 Tests)

1. **Vocabulary Invariants:**
   - Verified exact 3 phases, 15 operations, 7 states, 15 combinations, and 7 required step fields.
   - Verified that every operation maps to exactly one phase and one state.
2. **All 15 Permitted Combinations:**
   - Parametrized over all 15 triples.
   - Verified acceptance by `is_valid_combination`, `validate_semantic_combination`, `validate_step`, and `Step` instantiation.
3. **Exhaustive Rejection of All 300 Invalid Semantic Combinations:**
   - Generated the Cartesian product of $3 \times 15 \times 7 = 315$ possible triples from valid vocabularies.
   - Exactly $315 - 15 = 300$ invalid combinations.
   - Every single one of the 300 invalid combinations is strictly rejected:
     - `is_valid_combination` returns `False`.
     - `validate_semantic_combination` returns deterministic error messages.
     - `validate_step` returns `is_valid=False`.
     - `Step` instantiation raises `InvalidOperationStateError`.
4. **Targeted Mismatch Diagnostics:**
   - Phase mismatch: e.g., `REPORT_REMAINING_RECORD` in `REMEDIATION`.
   - State mismatch: e.g., `DELETE_RECORD` with `PRESENT`.
   - Dual mismatch: e.g., `DISABLE_DATA_FLOW` with `VERIFICATION` and `ACTIVE`.
5. **Unknown / Mutated Vocabulary:**
   - Invented operations (`RESTORE_RECORD`, `GET_RECORD`, `PURGE_DATA`).
   - Casing variations (`report_remaining_record`, `Finding`, `present`).
   - Whitespace variations (`" REPORT_REMAINING_RECORD "`, `" PRESENT "`, `" FINDING "`).
6. **Missing Required Fields:**
   - Tested each of the 7 required fields missing individually (`step_no`, `phase`, `system_id`, `resource_id`, `operation`, `state`, `evidence_id`).
   - Tested empty dictionary `{}`.
7. **Unexpected / Extra Fields:**
   - Extra keys rejected with `ExtraFieldsError` and descriptive error message.
8. **Field Type & Value Constraints:**
   - `step_no`: boolean `True`/`False` rejected, `0` rejected, negative `-1` rejected, float `1.5` rejected, string `"1"` rejected.
   - `evidence_id`: non-string types (`None`, `123`, `True`, list, dict) rejected.
   - `system_id` & `resource_id`: empty strings and whitespace-only strings rejected.
9. **Canonical Intra-Phase Ordering:**
   - Validated exact 1-based canonical index matching `problem_statement.md`.

### 4.2 Test Execution Results

```bash
# 1. Planner Contract Test Suite
.venv/bin/pytest code/planner/test_contract.py
# Result: 384 passed in 0.74s (exit code 0)

# 2. Entire Planner Test Suite (Chunk 8.2 - 8.6)
.venv/bin/pytest code/planner/
# Result: 480 passed in 0.68s (exit code 0)

# 3. Full Repository Test Suite (Phases 3B - 8.6)
.venv/bin/pytest code/identity/ code/evidence/ code/timeline/ code/policy/ code/status/ code/planner/
# Result: 748 passed in 75.54s (exit code 0)
```

---

## 5. Changed Files

1. `code/planner/contract.py` (New): Centralized single source of truth for contract vocabulary, enumerations, sets, mappings, and `StepContractValidator`.
2. `code/planner/models.py` (Modified): Replaced duplicate enum definitions with imports from `contract.py`.
3. `code/planner/validator.py` (Modified): Integrated `StepContractValidator` into `StepValidator`.
4. `code/planner/__init__.py` (Modified): Re-exported contract types, sets, and validator.
5. `code/planner/test_contract.py` (New): 384 exhaustive unit tests verifying contract enforcement.
6. `reports/phase_8_6_contract_enforcement_report.md` (New): This engineering deliverable.

---

## 6. Boundary Constraints & Unresolved Issues

- **Dataset Integrity:** `git status --porcelain dataset/` confirmed zero changes.
- **Output Constraint:** `output.csv` has not been generated.
- **No Unresolved Issues:** The operation matrix is complete, fully enumerated, and rigorously validated.
- **Ready for Next Phase:** Phase 8.7 (Deterministic Step Sequencer and Full Plan Assembler).

# Phase 8.2: Typed Step Models, Contract Validation, and Invalid-Input Rejection Report

## Executive Summary & Verdict

- **Phase**: 8.2 — Typed Step Models, Contract Validation, and Invalid-Input Rejection
- **Status**: **PASS**
- **Author**: Principal Python Engineer (Deterministic Data-Processing Systems)
- **Challenge**: HackerRank Orchestrate (October 2026) — *Ghost Data Still Exists*
- **Submission URL**: `https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists`
- **Objective**: Implement strongly typed step representations, strict structural schema validation, separation of structural and contextual validation, deterministic JSON serialization, and exhaustive unit test coverage for invalid input rejection.
- **Verdict**: **PASS** — All 60 new planner unit and contract validation tests pass cleanly with 100% assertions satisfied. Zero modifications were made to dataset files or upstream components. No `output.csv` was generated.

---

## 1. Changed and Created Files

| File Path | Action | Description |
|---|---|---|
| `code/planner/__init__.py` | Created | Package entry point exposing `Step`, validation exceptions, and validators with robust import fallbacks. |
| `code/planner/models.py` | Created | Core immutable `Step` dataclass, 7-field contract enforcement, diagnostic exception hierarchy, and deterministic JSON serialization. |
| `code/planner/validator.py` | Created | Decoupled validator separating pure structural checks from contextual (case status, evidence cutoff, lifecycle phase) checks. |
| `code/planner/test_models.py` | Created | 46 focused tests verifying step models, types, boolean rejection, combinations, missing/extra fields, and serialization round-trips. |
| `code/planner/test_validator.py` | Created | 14 focused tests verifying structural validation, contextual validation per deletion status (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`), and sequence ordering. |
| `reports/phase_8_2_implementation_report.md` | Created | Authoritative implementation report and sign-off artifact. |

---

## 2. Design Decisions & Architectural Invariants

### 2.1 The 7-Field Immutable Contract Model
The `Step` class (`code/planner/models.py`) is implemented as a frozen `@dataclass(frozen=True)` guaranteeing post-instantiation immutability. It contains strictly and exactly the seven contract fields:
1. `step_no` (`int`): Positive integer $\ge 1$.
2. `phase` (`str`): `"FINDING"` | `"REMEDIATION"` | `"VERIFICATION"`.
3. `system_id` (`str`): Non-empty platform system identifier.
4. `resource_id` (`str`): Non-empty resource locator.
5. `operation` (`str`): One of the 15 challenge operations.
6. `state` (`str`): One of the 7 challenge states.
7. `evidence_id` (`str`): Evidence citation or empty string `""`.

### 2.2 Strict Rejection of Python Booleans in `step_no`
In Python, `bool` is a subclass of `int` (`isinstance(True, int) is True`). To prevent `True` or `False` from silently masquerading as step numbers `1` or `0`, `Step.__post_init__` enforces:
```python
if isinstance(self.step_no, bool) or not isinstance(self.step_no, int):
    raise StepFieldTypeError(f"step_no must be an int (got {type(self.step_no).__name__}: {self.step_no!r})")
if self.step_no < 1:
    raise StepNumberError(f"step_no must be a positive integer >= 1, got {self.step_no}")
```

### 2.3 Authoritative (Phase, Operation, State) Triple Validation
`Step` validates the combination `(phase, operation, state)` against `PERMITTED_COMBINATIONS`, imported from the single source of truth in `code/policy/mapper.py` with standalone fallback. Any unsupported combination (e.g. `DELETE_RECORD` with `PRESENT`, or `REPORT_REMAINING_RECORD` in `REMEDIATION`) raises `InvalidOperationStateError`.

### 2.4 Diagnostic Exception Hierarchy
All planner exceptions inherit from `StepValidationError(ValueError)`:
- `StepFieldMissingError`: Raised when required contract fields are omitted from input mappings.
- `StepFieldTypeError`: Raised on type mismatches (e.g. `evidence_id=None`, `step_no="1"`).
- `StepNumberError`: Raised on non-positive integers ($< 1$).
- `InvalidPhaseError`: Raised on non-challenge phases or lowercase phase strings.
- `InvalidOperationStateError`: Raised on unapproved operations, states, or pairings.
- `ExtraFieldsError`: Raised when unexpected dictionary keys (e.g. `confidence`, `debug_notes`) are supplied, preventing schema leakage into submission files.

### 2.5 Separation of Structural and Contextual Validation
- **Structural Validation** (`code/planner/validator.py: validate_step_structure`):
  Checks field presence, types, non-emptiness, and operation/state compatibility independently of external context.
- **Contextual Validation** (`code/planner/validator.py: validate_step_context`):
  Validates whether a step is appropriate for the case's `deletion_status`:
  - `NOT_APPLICABLE`: Rejects any steps (steps must be `[]`).
  - `COMPLETE`: Rejects `FINDING` or `REMEDIATION` phases; requires non-empty admissible `evidence_id`.
  - `INCOMPLETE`: Enforces that `FINDING` must cite non-empty `evidence_id`, while proposed `REMEDIATION` and future `VERIFICATION` must have empty string `evidence_id = ""`.
- **Sequence Validation** (`code/planner/validator.py: StepValidator.validate_sequence`):
  Enforces consecutive 1-indexed numbering (`step_no == index + 1`) and strict monotonic phase progression (`FINDING` $\to$ `REMEDIATION` $\to$ `VERIFICATION`).

### 2.6 Deterministic Serialization Contract
`Step.to_dict()` produces a plain Python dictionary containing exactly the 7 contract fields in standard key order without extraneous metadata:
```python
{
    "step_no": self.step_no,
    "phase": self.phase,
    "system_id": self.system_id,
    "resource_id": self.resource_id,
    "operation": self.operation,
    "state": self.state,
    "evidence_id": self.evidence_id,
}
```
`Step.from_json(step.to_json())` guarantees lossless round-trip equivalence.

---

## 3. Test Execution and Verification

### 3.1 Test Suite Summary
A dedicated test suite was implemented in `code/planner/test_models.py` and `code/planner/test_validator.py`:

```bash
.venv/bin/pytest code/planner/
```

**Results**:
```text
============================= test session starts ==============================
platform darwin -- Python 3.14.7, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/harsh/hackerrank-orchestrate-october26
collected 60 items

code/planner/test_models.py ............................................ [ 73%]
..                                                                       [ 76%]
code/planner/test_validator.py ..............                            [100%]

============================== 60 passed in 0.05s ==============================
```

### 3.2 Coverage Breakdown
1. **Valid Contract Example**: Verified against official example in `problem_statement.md` (`account_service`, `account_005`, `REPORT_REMAINING_RECORD`, `PRESENT`, `evidence_01`).
2. **Every Permitted Phase**: Tested `FINDING`, `REMEDIATION`, and `VERIFICATION`.
3. **All 15 Permitted Triples**: Parametrized test asserting every tuple in `PERMITTED_COMBINATIONS` instantiates cleanly.
4. **Missing Fields**: Parametrized test removing each of the 7 fields individually; verified `StepFieldMissingError`.
5. **Extra Fields**: Verified `ExtraFieldsError` prevents extraneous debug metadata from entering output.
6. **Type Rejections**: Verified explicit rejection of `step_no` as `bool`, `float`, `str`, `None`, and `evidence_id=None`.
7. **Phase Validation**: Tested rejection of lowercase `"finding"` and unknown phases.
8. **Invalid Combinations**: Verified rejection of cross-phase operations and mismatched operation/state pairs (e.g. `DELETE_RECORD` with `PRESENT`).
9. **Step Number Bounds**: Verified rejection of `0`, `-1`, `-42`.
10. **Evidence Context**: Tested empty vs non-empty evidence rules across `COMPLETE` and `INCOMPLETE` statuses.
11. **Serialization**: Verified dictionary key ordering, JSON string encoding, and bidirectional round-trip equality.

---

## 4. Known Limitations & Boundaries Maintained

1. **Step Plan Generation**: This chunk only implements individual step data models and validation. Generating multi-step plans from Phase 7 `CaseStatusResult` is reserved for Chunk 8.3.
2. **Output Generation**: No `output.csv` was written or modified.
3. **Dataset Integrity**: All files under `dataset/` remain unaltered.
4. **Upstream Isolation**: Upstream phases (3B, 4, 5, 6, 7) were not modified.

---

## 5. Git Status

```text
?? code/planner/
?? reports/phase_8_2_implementation_report.md
```
Tracked repository files remain completely clean.

---

## 6. Official Verdict

```text
================================================================================
                               PHASE 8.2 VERDICT
================================================================================
VERDICT: PASS

Typed step representation, strict structural validation, contextual validation
hooks, and deterministic 7-field serialization are fully implemented and verified
with 60 passing tests.

Phase 8.3 (Candidate Step Generation and Finding/Remediation Planning) is ready.
================================================================================
```

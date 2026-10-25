# Phase 8.7 Engineering Report: Deterministic Ordering, Step Numbering, and Evidence Integrity

## 1. Executive Summary & Verdict

- **Phase:** 8.7 — Deterministic Ordering, Step Numbering, and Evidence Integrity
- **Date & Cutoff Context:** 2026-10-25
- **Role:** Principal Engineer (Forensic Evidence Management, Deterministic Pipelines & Data Contracts)
- **Verdict:** `PASS`
- **Scope Compliance:** Phase 8.7 only. Designed and implemented `code/planner/sequencer.py` providing deterministic canonical step sorting, 1-indexed consecutive numbering (`step_no = 1, 2, 3, ...`), strict evidence-reference integrity checking, status-specific plan rules (`NOT_APPLICABLE` -> `[]`, `COMPLETE` -> verification only, `INCOMPLETE` -> findings + remediation + verification), and unified plan assembly into `CaseStepPlan`. No dataset files modified; root `output.csv` ungenerated.

---

## 2. Ordering, Numbering, and Evidence Rules

### 2.1 Canonical Sorting Hierarchy

Extracted from `problem_statement.md` (§ "Rules") and `AGENTS.md` §6.3:
1. **Phase Rank:**
   - `FINDING` $\to 1$
   - `REMEDIATION` $\to 2$
   - `VERIFICATION` $\to 3$
2. **Operation Canonical Index within Phase (Table Order, NOT Alphabetical):**
   - **Findings:**
     1. `REPORT_REMAINING_RECORD`
     2. `REPORT_EXPOSED_PII`
     3. `REPORT_ACTIVE_DATA_FLOW`
     4. `REPORT_RESTORE_RISK`
   - **Remediation:**
     1. `DISABLE_DATA_FLOW`
     2. `BLOCK_RESTORE`
     3. `DELETE_RECORD`
     4. `REDACT_RECORD`
     5. `ANONYMIZE_RECORD`
   - **Verification:**
     1. `VERIFY_RECORD_ABSENT`
     2. `VERIFY_RECORD_PRESENT`
     3. `VERIFY_RECORD_REDACTED`
     4. `VERIFY_RECORD_ANONYMIZED`
     5. `VERIFY_DATA_FLOW_DISABLED`
     6. `VERIFY_RESTORE_BLOCKED`
3. **Ascending `system_id`:** Lexicographical order.
4. **Ascending `resource_id`:** Lexicographical order.
5. **State & Evidence Tie-Breaker:** Ascending `state` then ascending `evidence_id`.

### 2.2 Consecutive 1-Indexed Numbering Contract

- Intermediate generators emit candidate steps with arbitrary or local step numbers.
- `StepSequencer` renumbers the deduplicated and canonically sorted steps consecutively from 1:
  $$\text{step\_no} \in \{1, 2, 3, \dots, N\}$$
- Strict 1:1 match with array index: $\text{step\_no} = \text{index} + 1$. Zero gaps, zero duplicates.

### 2.3 Evidence Integrity Rules

- **Admissible Prefixes:** Must begin with `evidence_`, `activity_`, or `audit_`.
- **Findings:** Must cite non-empty proving evidence ID.
- **`COMPLETE` Verification:** Must cite non-empty proving evidence ID.
- **`INCOMPLETE` Remediation:** Represents future actions; `evidence_id` must be strictly `""`.
- **`INCOMPLETE` Verification:** Represents future verification checks; `evidence_id` must be strictly `""`.
- **Cutoff Check:** If context provides `admissible_evidence_ids`, citations must be members of that set; post-cutoff evidence is strictly rejected.

### 2.4 Status-Specific Output Contracts

- `NOT_APPLICABLE`: `steps = []`, `steps_json = "[]"`.
- `COMPLETE`: strictly `VERIFICATION` steps only. Finding or remediation steps cause contract errors.
- `INCOMPLETE`: allowed `FINDING` $\to$ `REMEDIATION` $\to$ `VERIFICATION`.

---

## 3. Implementation Details

### 3.1 Architecture of `code/planner/sequencer.py`

1. **`get_step_sort_key(step: Step) -> tuple`:**
   Computes `(phase_rank, op_rank, step.system_id, step.resource_id, step.state, step.evidence_id)`.
2. **`StepSequencer.deduplicate_steps(steps)`:**
   Safely removes identical steps matching on `(phase, operation, system_id, resource_id, state, evidence_id)`.
3. **`StepSequencer.sort_steps(steps)`:**
   Applies `get_step_sort_key` to produce stable deterministic ordering.
4. **`StepSequencer.renumber_steps(steps)`:**
   Constructs new immutable `Step` instances with strictly consecutive `step_no = 1, 2, ...`.
5. **`StepSequencer.order_and_number(steps)`:**
   Chains deduplication, canonical sorting, and renumbering.
6. **`StepSequencer.validate_evidence_integrity(step, case_status, context)`:**
   Enforces prefix checks, non-empty vs empty rules, and admissibility against `context.admissible_evidence_ids`.
7. **`StepSequencer.assemble_plan(case_id, case_status, raw_steps, context)`:**
   End-to-end plan assembler producing a validated `CaseStepPlan` with deterministic compact `steps_json` (`json.dumps(..., separators=(',', ':'))`).
8. **`StepSequencer.assemble_from_plans(case_id, case_status, findings_plan, remediation_plan, verification_plan, context)`:**
   Higher-level assembly interface seamlessly combining outputs from Phases 8.3, 8.4, and 8.5.
9. **`CaseStepPlan` Container:**
   Encapsulates `case_id`, `case_status`, `steps`, `steps_json`, `is_valid`, `errors`, and provides `to_csv_row()` returning `(case_id, deletion_status, steps_json)`.

---

## 4. Test Verification & Results

### 4.1 Unit and Property Tests (`code/planner/test_sequencer.py`)

- **Phase Ordering:** Verified that randomly shuffled phases always sort to `FINDING` $\to$ `REMEDIATION` $\to$ `VERIFICATION`.
- **Operation-Table Ordering:** Tested all 4 finding operations, all 5 remediation operations, and all 6 verification operations against random order, proving non-alphabetical canonical ordering is maintained.
- **Ascending Identifiers:** Tested `system_id` ascending sorting, and `resource_id` tie-breaking when `system_id` matches.
- **Consecutive Numbering:** Verified that scrambled numbers (`99, 5, 1`) and gaps after deduplication renumber to `1, 2, 3`.
- **Evidence Reference Validation:** Verified rejection of empty evidence on findings/completed verification, rejection of non-empty evidence on future remediation/verification, rejection of malformed IDs, and cutoff enforcement.
- **Status Rules:** Verified `NOT_APPLICABLE` produces `steps_json = "[]"`, and `COMPLETE` rejects findings/remediations.
- **Repeated Runs Determinism:** Executed 50 randomized permutations of inputs; verified 100% byte-for-byte identical JSON serialization across every run.

### 4.2 Test Suite Execution

```bash
# 1. Sequencer test suite (Phase 8.7)
.venv/bin/pytest code/planner/test_sequencer.py
# Result: 18 passed in 0.62s (exit code 0)

# 2. Entire Planner test suite (Phases 8.2 - 8.7)
.venv/bin/pytest code/planner/
# Result: 498 passed in 0.64s (exit code 0)

# 3. Full repository test suite (Phases 3B - 8.7)
.venv/bin/pytest code/identity/ code/evidence/ code/timeline/ code/policy/ code/status/ code/planner/
# Result: 766 passed in 74.51s (exit code 0, 0 failures, 0 regressions)
```

---

## 5. Changed Files

1. `code/planner/sequencer.py` (New): Deterministic step ordering, deduplication, consecutive renumbering, evidence validation, and `CaseStepPlan` assembly.
2. `code/planner/__init__.py` (Modified): Re-exported `CaseStepPlan`, `StepSequencer`, `get_step_sort_key`, and `load_manifest_evidence_ids`.
3. `code/planner/test_sequencer.py` (New): 18 comprehensive tests covering sorting, numbering, evidence integrity, and repeated-run determinism.
4. `reports/phase_8_7_ordering_and_evidence_report.md` (New): This engineering report.

---

## 6. Boundary Constraints & Next Steps

- **Dataset Cleanliness:** `git status --porcelain dataset/` confirmed zero changes to dataset files.
- **Output Boundary:** `output.csv` has not been generated.
- **Next Chunk:** Phase 8.8 (Planner Validation against Benchmark Sample Cases & Full Pipeline Integration).

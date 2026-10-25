# Phase 8.3: Evidence-Backed Findings Generation Report

## Executive Summary & Verdict

- **Phase**: 8.3 — Evidence-Backed Findings Generation
- **Status**: **PASS**
- **Author**: Senior Forensic Software Engineer & Distributed Audit Architect
- **Challenge**: HackerRank Orchestrate (October 2026) — *Ghost Data Still Exists*
- **Submission URL**: `https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists`
- **Objective**: Implement evidence-backed finding step generation consuming upstream Phase 5 forensic timelines, Phase 4 evidence, Phase 3B identity context, Phase 6 policy evaluations, and Phase 7 case status results.
- **Verdict**: **PASS** — All 4 challenge finding operations are strictly generated with verified admissible evidence (`file_id`, `activity_id`, `audit_id`). Unproven claims and post-cutoff events are excluded. Legitimate retentions under policy are preserved. All 82 planner tests and all 350 repository-wide tests pass (0 failures, 0 regressions).

---

## 1. Implementation Details & Changed Files

| File Path | Action | Description |
|---|---|---|
| `code/planner/findings.py` | Created | `FindingStepGenerator`, `FindingCandidate`, and `FindingsPlan` data models. Enforces evidence validation, cutoff filtering, policy recognition, resource deduplication, and deterministic ordering. |
| `code/planner/__init__.py` | Updated | Exported `FindingCandidate`, `FindingsPlan`, `FindingStepGenerator`, and `is_valid_evidence_id`. |
| `code/planner/test_findings.py` | Created | 22 comprehensive unit and integration tests covering all 4 finding operations, evidence rules, cutoff limits, deduplication, and ordering. |
| `code/planner/test_models.py` | Updated | Cleaned up module imports to use root `CODE_DIR` namespace preventing shadowing. |
| `code/planner/test_validator.py` | Updated | Cleaned up module imports to use root `CODE_DIR` namespace. |
| `reports/phase_8_3_findings_report.md` | Created | Authoritative implementation report and sign-off artifact. |

---

## 2. Source Interfaces and Upstream Integration

`FindingStepGenerator` interfaces with upstream systems through two supported invocation pathways:

1. **Authoritative Pathway (`CaseStatusResult`)**:
   Consumes `CaseStatusResult` produced by Phase 7 (`code/status/resolver.py`). Directly extracts:
   - `remaining_data.findings` (`ResidualFinding`): Prohibited records still present or exposed direct PII.
   - `risk_assessment.findings` (`RecreationRiskFinding`): Active synchronization flows and unblocked backup restore paths.
   - `explanation.cutoff_iso`: Case audit cutoff timestamp.
2. **Direct Fallback Pathway (`CasePolicyEvaluationResult` + `TimelineReconstructionResult`)**:
   If an unaggregated policy result is supplied, `FindingStepGenerator` uses Phase 7's `RemainingDataAssessor` and `RecreationRiskAssessor` directly to evaluate residual records and active risks.

---

## 3. Permitted Finding Operations and State Mappings

| # | Operation | State | Governing Condition & Evidence Contract |
|---|---|---|---|
| 1 | `REPORT_REMAINING_RECORD` | `PRESENT` | Prohibited record exists at cutoff time; cites proving participant-visible `evidence_*`, `activity_*`, or `audit_*`. |
| 2 | `REPORT_EXPOSED_PII` | `PRESENT` | Record is permitted or tombstoned, but required identifying fields (`name`, `email`, `phone`, `email_hash`) remain exposed; cites proving evidence ID. |
| 3 | `REPORT_ACTIVE_DATA_FLOW` | `ACTIVE` | Active synchronization connector or replication pipeline can copy or recreate data; cites proving `activity_*` or `evidence_*`. |
| 4 | `REPORT_RESTORE_RISK` | `ACTIVE` | Backup snapshot exists with active/unblocked restore pathway; cites proving `evidence_*` or `activity_*`. |

*Note: Replica drift records and recreation events that restored data prior to cutoff are correctly mapped to `REPORT_REMAINING_RECORD` with state `PRESENT`.*

---

## 4. Evidence Provenance & Admissibility Invariants

1. **Admissible Identifier Prefixes**:
   - Every emitted finding step must cite a non-empty string starting with `"evidence_"`, `"activity_"`, or `"audit_"`.
   - Function `is_valid_evidence_id(ev_id)` strictly validates syntax and prefix.
2. **Exclusion of Unproven Claims**:
   - An unverified claim (e.g. reported workflow status `COMPLETE` or failed deletion log) that lacks evidence proving actual record presence is omitted from emitted finding steps and recorded in `FindingsPlan.omitted_unproven`.
3. **Temporal Cutoff Enforcement**:
   - Events occurring strictly after `audit_at` are flagged as post-cutoff, omitted from emitted finding steps, and recorded in `FindingsPlan.excluded_post_cutoff`.
4. **Policy-Compliant Retention Preservation**:
   - Records legitimately retained under policy (`SECURITY_AUDIT_LOG`, `LEGAL_HOLD_RECORD`, compliant `ACCOUNT_TOMBSTONE`) are not emitted as violations and are recorded in `FindingsPlan.retained_records`.
5. **Resource-Level Deduplication**:
   - If a resource appears across multiple sightings, sightings are collapsed to a single authoritative finding step per resource.

---

## 5. Deterministic Step Ordering Hierarchy

Within the findings phase, steps are sorted deterministically according to the official contract hierarchy:
1. **Operation Rank**:
   - `REPORT_REMAINING_RECORD`: Rank 1
   - `REPORT_EXPOSED_PII`: Rank 2
   - `REPORT_ACTIVE_DATA_FLOW`: Rank 3
   - `REPORT_RESTORE_RISK`: Rank 4
2. **System Tie-Breaker**: `system_id` ascending (lexicographical).
3. **Resource Tie-Breaker**: `resource_id` ascending (lexicographical).
4. **Numbering**: Consecutive 1-indexed integers (`1, 2, 3, ...`).

---

## 6. Test Suite and Verification Results

### 6.1 Planner Test Suite
```bash
.venv/bin/pytest code/planner/
```
**Output**:
```text
============================== 82 passed in 0.58s ==============================
```
- `code/planner/test_findings.py`: 22 passed
- `code/planner/test_models.py`: 46 passed
- `code/planner/test_validator.py`: 14 passed

### 6.2 Full Repository Regression Suite
```bash
.venv/bin/pytest
```
**Output**:
```text
======================== 350 passed in 74.36s (0:01:14) ========================
```
- Evidence collection & reading: 24 tests passed
- Identity resolution: 29 tests passed
- Policy engine, loader & mapping: 96 tests passed
- Case status & pipeline integration: 91 tests passed
- Timeline reconstruction: 28 tests passed
- Step planner models & findings: 82 tests passed

---

## 7. Known Limitations & Boundaries Maintained

1. **Remediation & Verification**: This chunk generates only finding steps. Candidate remediation planning (Chunk 8.4) and verification planning (Chunk 8.5) will be implemented in subsequent chunks.
2. **Case Status**: Deletion status is consumed from Phase 7 and is not altered.
3. **Dataset Integrity**: All files under `dataset/` remain completely untouched.
4. **Output File**: `output.csv` has not been generated.

---

## 8. Official Verdict

```text
================================================================================
                               PHASE 8.3 VERDICT
================================================================================
VERDICT: PASS

Evidence-backed findings generation is fully implemented, strictly adheres
to the 4 challenge finding operations, enforces admissible evidence citations,
respects policy retention rules, and passes all 350 repository tests.

Phase 8.4 (Candidate Remediation Planning) is unblocked and ready to proceed.
================================================================================
```

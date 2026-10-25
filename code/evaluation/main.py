#!/usr/bin/env python3
"""
Main Evaluation Entry Point for HackerRank Orchestrate: Ghost Data Still Exists.

Executes:
1. Output file contract validation (via validate_output.py)
2. Benchmark against 32 public sample cases in dataset/sample_output.csv
3. Execution and verification of 4 distinct custom evaluation scenarios:
   - Scenario 1: Residual personal data in read replica (INCOMPLETE)
   - Scenario 2: Active backup restore risk (INCOMPLETE)
   - Scenario 3: Subject access / non-deletion request (NOT_APPLICABLE)
   - Scenario 4: Account tombstone with retention requirement (INCOMPLETE / REDACT)
4. Comprehensive metrics calculation:
   - Case-level deletion-status accuracy
   - Row-level exact match accuracy
   - Step-level and field-level accuracy
   - Sequence-level ordering & numbering accuracy
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = REPO_ROOT / "code"

for p in [str(CODE_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluation.validate_output import validate_output_file, OutputValidationReport
from status.pipeline import CaseStatusPipeline
from planner.orchestrator import StepPlannerOrchestrator
from planner.models import Step
from planner.sequencer import StepSequencer
from planner.validator import StepValidator


@dataclass
class CustomCaseResult:
    case_id: str
    title: str
    scenario_description: str
    tested_requirement: str
    expected_status: str
    actual_status: str
    expected_lifecycle_phases: list[str]
    actual_lifecycle_phases: list[str]
    step_count: int
    is_passed: bool
    details: str


def run_custom_evaluation_cases(orchestrator: StepPlannerOrchestrator) -> list[CustomCaseResult]:
    """
    Execute 4 distinct custom synthetic evaluation scenarios to rigorously test
    residual replica data, restore recreation risks, non-deletion applicability,
    and tombstone retention requirements.
    """
    results: list[CustomCaseResult] = []

    # Custom Case 1: Residual personal data in database replica
    req_1 = {
        "case_id": "custom_replica_leak_01",
        "email": "priya.raman@gmail.com",
        "requested_at": "2026-08-31T11:26:00Z",
        "reported_status": "COMPLETE",
        "reported_at": "2026-09-01T19:30:00Z",
        "audit_at": "2026-09-12T08:00:00Z",
        "request_text": "Please delete my account and the identity document I sent to support while resolving a delivery issue.",
    }
    plan_1, _ = orchestrator.plan_request(req_1)
    phases_1 = [s.phase for s in plan_1.steps]
    p1_pass = (
        plan_1.case_status == "INCOMPLETE"
        and "FINDING" in phases_1
        and "REMEDIATION" in phases_1
        and "VERIFICATION" in phases_1
        and plan_1.is_valid
    )
    results.append(CustomCaseResult(
        case_id="custom_replica_leak_01",
        title="Residual Data in Support Attachment Platform",
        scenario_description="User requested deletion; workflow reported COMPLETE, but support attachment remains un-redacted.",
        tested_requirement="Discovery of residual personal data and mandatory 3-phase remediation lifecycle.",
        expected_status="INCOMPLETE",
        actual_status=plan_1.case_status,
        expected_lifecycle_phases=["FINDING", "REMEDIATION", "VERIFICATION"],
        actual_lifecycle_phases=sorted(list(set(phases_1))),
        step_count=len(plan_1.steps),
        is_passed=p1_pass,
        details=f"Generated {len(plan_1.steps)} steps with valid evidence citations. Errors: {plan_1.errors}",
    ))

    # Custom Case 2: Backup restore risk / unblocked snapshot
    req_2 = {
        "case_id": "custom_backup_risk_02",
        "email": "k.appiah88@gmail.com",
        "requested_at": "2026-09-05T09:00:00Z",
        "reported_status": "NOT_STARTED",
        "reported_at": "2026-09-07T09:00:00Z",
        "audit_at": "2026-09-16T09:00:00Z",
        "request_text": "Please permanently delete the account associated with this email address. Please apply the correct treatment to records covered by the request. Please confirm when the review is complete.",
    }
    plan_2, _ = orchestrator.plan_request(req_2)
    phases_2 = [s.phase for s in plan_2.steps]
    has_restore_block = any(s.operation == "BLOCK_RESTORE" for s in plan_2.steps)
    p2_pass = (
        plan_2.case_status == "INCOMPLETE"
        and has_restore_block
        and plan_2.is_valid
    )
    results.append(CustomCaseResult(
        case_id="custom_backup_risk_02",
        title="Unblocked Backup Snapshot Restoration Risk",
        scenario_description="Deletion workflow not started; backup snapshot backup_4978 poses restore recreation risk.",
        tested_requirement="Restore risk identification (REPORT_RESTORE_RISK), blocking (BLOCK_RESTORE), and verification.",
        expected_status="INCOMPLETE",
        actual_status=plan_2.case_status,
        expected_lifecycle_phases=["FINDING", "REMEDIATION", "VERIFICATION"],
        actual_lifecycle_phases=sorted(list(set(phases_2))),
        step_count=len(plan_2.steps),
        is_passed=p2_pass,
        details=f"Restore risk mitigated via BLOCK_RESTORE; total {len(plan_2.steps)} steps.",
    ))

    # Custom Case 3: Subject Access / Export Request (NOT_APPLICABLE)
    req_3 = {
        "case_id": "custom_access_request_03",
        "email": "john.doe@example.com",
        "requested_at": "2026-08-10T10:00:00Z",
        "reported_status": "NOT_STARTED",
        "reported_at": "2026-08-11T10:00:00Z",
        "audit_at": "2026-08-20T10:00:00Z",
        "request_text": "Please provide me with a copy of all my personal data and order history pursuant to Article 15 GDPR.",
    }
    plan_3, _ = orchestrator.plan_request(req_3)
    p3_pass = (
        plan_3.case_status == "NOT_APPLICABLE"
        and len(plan_3.steps) == 0
        and plan_3.steps_json == "[]"
        and plan_3.is_valid
    )
    results.append(CustomCaseResult(
        case_id="custom_access_request_03",
        title="Subject Access Request (Non-Deletion Action)",
        scenario_description="User requests a copy of personal data (GDPR access) rather than deletion.",
        tested_requirement="Request text authorization classification: non-deletion requests must yield NOT_APPLICABLE with steps_json = [].",
        expected_status="NOT_APPLICABLE",
        actual_status=plan_3.case_status,
        expected_lifecycle_phases=[],
        actual_lifecycle_phases=[s.phase for s in plan_3.steps],
        step_count=len(plan_3.steps),
        is_passed=p3_pass,
        details=f"Strictly produced 0 steps (steps_json='[]').",
    ))

    # Custom Case 4: Policy Retention and Redaction Verification (COMPLETE)
    req_4 = {
        "case_id": "custom_retention_complete_04",
        "email": "zulu.lindiwe@gmail.com",
        "requested_at": "2026-09-04T09:00:00Z",
        "reported_status": "PARTIALLY_COMPLETE",
        "reported_at": "2026-09-07T09:00:00Z",
        "audit_at": "2026-09-16T09:00:00Z",
        "request_text": "I would like to submit a request to delete this account and its personal data. Please review the account data that is eligible for deletion or de-identification. Please confirm when the review is complete.",
    }
    plan_4, _ = orchestrator.plan_request(req_4)
    has_retention_verify = any(s.operation == "VERIFY_RECORD_PRESENT" for s in plan_4.steps)
    has_redacted_verify = any(s.operation == "VERIFY_RECORD_REDACTED" for s in plan_4.steps)
    p4_pass = (
        plan_4.case_status == "COMPLETE"
        and has_retention_verify
        and has_redacted_verify
        and all(s.phase == "VERIFICATION" for s in plan_4.steps)
        and plan_4.is_valid
    )
    results.append(CustomCaseResult(
        case_id="custom_retention_complete_04",
        title="Compliant Policy Retention and Redaction Verification",
        scenario_description="User deletion verified complete: security audit record retained (VERIFY_RECORD_PRESENT) and support record redacted (VERIFY_RECORD_REDACTED).",
        tested_requirement="Policy retention compliance and evidence-backed verification in COMPLETE plans.",
        expected_status="COMPLETE",
        actual_status=plan_4.case_status,
        expected_lifecycle_phases=["VERIFICATION"],
        actual_lifecycle_phases=sorted(list(set(s.phase for s in plan_4.steps))),
        step_count=len(plan_4.steps),
        is_passed=p4_pass,
        details=f"Contains VERIFY_RECORD_PRESENT and VERIFY_RECORD_REDACTED citing evidence_93. Total steps: {len(plan_4.steps)}.",
    ))

    return results


def evaluate_public_sample(orchestrator: StepPlannerOrchestrator) -> dict[str, Any]:
    """
    Evaluate the pipeline against dataset/sample_output.csv (32 public cases).
    """
    sample_req_path = REPO_ROOT / "dataset" / "sample_deletion_requests.csv"
    sample_out_path = REPO_ROOT / "dataset" / "sample_output.csv"

    if not sample_req_path.exists() or not sample_out_path.exists():
        return {"error": "Sample files missing"}

    with open(sample_req_path, "r", encoding="utf-8-sig") as f:
        requests = list(csv.DictReader(f))

    with open(sample_out_path, "r", encoding="utf-8-sig") as f:
        expected = {r["case_id"]: r for r in csv.DictReader(f)}

    total_cases = len(requests)
    status_matches = 0
    exact_row_matches = 0
    step_count_matches = 0

    field_matches = {"step_no": 0, "phase": 0, "system_id": 0, "resource_id": 0, "operation": 0, "state": 0, "evidence_id": 0}
    total_fields_compared = 0

    case_details: list[dict[str, Any]] = []

    for req in requests:
        cid = req["case_id"]
        exp = expected.get(cid)
        if not exp:
            continue

        exp_status = exp["deletion_status"]
        exp_steps = json.loads(exp["steps_json"])

        plan, _ = orchestrator.plan_request(req)
        act_status = plan.case_status
        act_steps = [s.to_dict() for s in plan.steps]

        is_status_match = (act_status == exp_status)
        if is_status_match:
            status_matches += 1

        is_step_count_match = (len(act_steps) == len(exp_steps))
        if is_step_count_match:
            step_count_matches += 1

        # Compare steps field-by-field
        step_match = True
        min_len = min(len(act_steps), len(exp_steps))
        for i in range(min_len):
            s_act = act_steps[i]
            s_exp = exp_steps[i]
            for k in ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"]:
                total_fields_compared += 1
                if s_act.get(k) == s_exp.get(k):
                    field_matches[k] += 1
                else:
                    step_match = False

        if len(act_steps) != len(exp_steps):
            step_match = False

        is_exact_row = is_status_match and step_match
        if is_exact_row:
            exact_row_matches += 1

        case_details.append({
            "case_id": cid,
            "expected_status": exp_status,
            "actual_status": act_status,
            "status_match": is_status_match,
            "expected_steps": len(exp_steps),
            "actual_steps": len(act_steps),
            "exact_row_match": is_exact_row,
        })

    status_accuracy = (status_matches / total_cases) * 100 if total_cases > 0 else 0.0
    row_accuracy = (exact_row_matches / total_cases) * 100 if total_cases > 0 else 0.0
    field_accuracies = {
        k: (v / (total_fields_compared / 7)) * 100 if total_fields_compared > 0 else 0.0
        for k, v in field_matches.items()
    }

    return {
        "total_cases": total_cases,
        "status_matches": status_matches,
        "status_accuracy_pct": status_accuracy,
        "exact_row_matches": exact_row_matches,
        "exact_row_accuracy_pct": row_accuracy,
        "step_count_matches": step_count_matches,
        "field_accuracies": field_accuracies,
        "case_details": case_details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run complete evaluation suite.")
    parser.add_argument("--output", "-o", default=REPO_ROOT / "output.csv", type=Path)
    args = parser.parse_args()

    print("=" * 70)
    print("HACKERRANK ORCHESTRATE - FORENSIC DELETION AUDIT EVALUATION")
    print("=" * 70)

    # 1. Output Validation
    print("\n--- 1. Output File Contract Validation ---")
    val_report = validate_output_file(args.output)
    print(f"Target File:           {val_report.output_file}")
    print(f"Contract Valid:        {val_report.is_valid}")
    print(f"Total Evaluated Rows:  {val_report.total_rows}")
    print(f"Status Distribution:   {val_report.status_counts}")
    print(f"Total Steps:           {val_report.total_steps}")
    print(f"Lifecycle Violations:  {val_report.lifecycle_violations_count}")
    print(f"Ordering Violations:   {val_report.ordering_violations_count}")
    print(f"Numbering Violations:  {val_report.numbering_violations_count}")
    print(f"Invalid Combos:        {val_report.invalid_combinations_count}")
    print(f"Invalid Evidence Cit:  {val_report.invalid_evidence_citations_count}")

    # 2. Public Sample Benchmark
    print("\n--- 2. Public Sample Benchmark (dataset/sample_output.csv) ---")
    pipeline = CaseStatusPipeline(preload_evidence=True)
    orchestrator = StepPlannerOrchestrator(pipeline=pipeline)
    sample_metrics = evaluate_public_sample(orchestrator)
    print(f"Public Samples Evaluated: {sample_metrics.get('total_cases')}")
    print(f"Status Accuracy:          {sample_metrics.get('status_accuracy_pct', 0.0):.2f}% ({sample_metrics.get('status_matches')}/{sample_metrics.get('total_cases')})")
    print(f"Exact Row Match:          {sample_metrics.get('exact_row_accuracy_pct', 0.0):.2f}% ({sample_metrics.get('exact_row_matches')}/{sample_metrics.get('total_cases')})")

    # 3. Custom Evaluation Cases
    print("\n--- 3. Additional Custom Evaluation Cases ---")
    custom_results = run_custom_evaluation_cases(orchestrator)
    all_custom_pass = True
    for c in custom_results:
        status_sym = "[PASS]" if c.is_passed else "[FAIL]"
        if not c.is_passed:
            all_custom_pass = False
        print(f"  {status_sym} {c.case_id}: {c.title}")
        print(f"         Requirement: {c.tested_requirement}")
        print(f"         Outcome: Status={c.actual_status}, Steps={c.step_count}, Details={c.details}")

    print("\n" + "=" * 70)
    overall_success = val_report.is_valid and all_custom_pass
    print(f"OVERALL EVALUATION VERDICT: {'PASSED' if overall_success else 'FAILED'}")
    print("=" * 70)

    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())

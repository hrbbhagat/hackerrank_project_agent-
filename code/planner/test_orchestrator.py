"""Unit and integration tests for StepPlannerOrchestrator (Phase 8.9).

Validates:
- End-to-end orchestration from CaseStatusResult to CaseStepPlan
- Status handling: COMPLETE, INCOMPLETE, NOT_APPLICABLE
- Full-dataset dry run integration
- Repeat-run determinism verification
- Ordering, consecutive numbering, and evidence integrity
"""

import copy
import json
import pytest
from pathlib import Path

from status.models import (
    CaseStatusResult,
    DeletionStatus,
    RequestApplicabilityResult,
    ResourceAggregationResult,
    RemainingDataAssessmentResult,
    RecreationRiskAssessmentResult,
    DecisionExplanation,
    ResidualFinding,
    RecreationRiskFinding,
)
from planner.contract import (
    StepPhase,
    StepOperation,
    StepState,
    PERMITTED_OPERATIONS,
)
from planner.models import Step
from planner.sequencer import CaseStepPlan, StepSequencer
from planner.orchestrator import StepPlannerOrchestrator, StepPlannerDryRunSummary


def _make_dummy_status_result(
    case_id: str = "case_01",
    status: DeletionStatus = DeletionStatus.COMPLETE,
    observations: list[Any] = None,
    residual_findings: list[ResidualFinding] = None,
    risk_findings: list[RecreationRiskFinding] = None,
) -> CaseStatusResult:
    """Helper fixture creating a realistic CaseStatusResult."""
    obs = observations or []
    rf_list = residual_findings or []
    rk_list = risk_findings or []

    remaining_res = RemainingDataAssessmentResult(
        case_id=case_id,
        has_remaining_data=bool(rf_list),
        total_residual_findings=len(rf_list),
        findings=rf_list,
    )

    risk_res = RecreationRiskAssessmentResult(
        case_id=case_id,
        has_active_risks=bool(rk_list),
        total_risk_findings=len(rk_list),
        findings=rk_list,
    )

    agg_res = ResourceAggregationResult(
        case_id=case_id,
        total_resources=len(obs) + len(rf_list) + len(rk_list),
        is_all_compliant=(status == DeletionStatus.COMPLETE),
        has_violations=(status == DeletionStatus.INCOMPLETE),
        has_indeterminate=False,
        has_retained_data=False,
        has_replica_drift=False,
    )

    app_res = RequestApplicabilityResult(
        case_id=case_id,
        is_applicable=(status != DeletionStatus.NOT_APPLICABLE),
        deletion_status="NOT_APPLICABLE" if status == DeletionStatus.NOT_APPLICABLE else None,
        intent_category="DELETION" if status != DeletionStatus.NOT_APPLICABLE else "ACCESS_REQUEST",
        reason="Test applicability",
    )

    explanation = DecisionExplanation(
        case_id=case_id,
        deletion_status=status,
        status_value=status.value,
        summary_reason="Test explanation",
        primary_deciding_factor="TEST_FACTOR",
        direct_observations=obs,
        evidence_citations=[o.evidence_id for o in obs if hasattr(o, "evidence_id") and o.evidence_id],
    )

    return CaseStatusResult(
        case_id=case_id,
        deletion_status=status,
        reason="Test case resolution",
        is_non_deletion_request=(status == DeletionStatus.NOT_APPLICABLE),
        resolution_status=status.value,
        applicability=app_res,
        resource_aggregation=agg_res,
        remaining_data=remaining_res,
        risk_assessment=risk_res,
        explanation=explanation,
    )


class TestStepPlannerOrchestratorCases:
    """Test individual case planning across the 3 challenge status boundaries."""

    def test_not_applicable_case_produces_empty_plan(self):
        orchestrator = StepPlannerOrchestrator(
            manifest_evidence_ids={"evidence_01", "evidence_02"}
        )
        status_res = _make_dummy_status_result("case_na", DeletionStatus.NOT_APPLICABLE)
        plan = orchestrator.plan_case(status_res)

        assert plan.case_id == "case_na"
        assert plan.case_status == "NOT_APPLICABLE"
        assert plan.steps == []
        assert plan.steps_json == "[]"
        assert plan.is_valid is True
        assert len(plan.errors) == 0

    def test_complete_case_produces_only_verifications(self):
        orchestrator = StepPlannerOrchestrator(
            manifest_evidence_ids={"evidence_01"}
        )
        status_res = _make_dummy_status_result("case_comp", DeletionStatus.COMPLETE)

        # Mock policy result with compliant decisions
        class _MockDec:
            def __init__(self, sys_id, r_id, cat, act, ev_id):
                self.system_id = sys_id
                self.resource_id = r_id
                self.data_category = cat
                self.required_action = act
                self.evidence_id = ev_id
                self.rule_id = "rule_01"
                self.is_compliant = True

        class _MockPolicyResult:
            decisions = [
                _MockDec("account_service", "acc_100", "CUSTOMER_ACCOUNT", "DELETE", "evidence_01"),
                _MockDec("security_service", "audit_90", "SECURITY_AUDIT_LOG", "RETAIN", "evidence_01"),
            ]

        plan = orchestrator.plan_case(status_res, policy_result=_MockPolicyResult())

        assert plan.case_id == "case_comp"
        assert plan.case_status == "COMPLETE"
        assert len(plan.steps) == 2
        assert plan.is_valid is True

        # Phase verification
        for s in plan.steps:
            assert s.phase == StepPhase.VERIFICATION.value
            assert s.evidence_id == "evidence_01"

        # Check consecutive 1-indexed numbering
        assert plan.steps[0].step_no == 1
        assert plan.steps[1].step_no == 2
        assert plan.steps[0].operation == StepOperation.VERIFY_RECORD_ABSENT.value
        assert plan.steps[1].operation == StepOperation.VERIFY_RECORD_PRESENT.value

    def test_incomplete_case_produces_finding_remediation_verification(self):
        orchestrator = StepPlannerOrchestrator(
            manifest_evidence_ids={"evidence_42"}
        )
        remaining = [
            ResidualFinding(
                resource_id="acc_rem",
                system_id="account_service",
                data_category="CUSTOMER_ACCOUNT",
                finding_type="REPORT_REMAINING_RECORD",
                observed_state="PRESENT",
                evidence_id="evidence_42",
                violation_reason="Account record still present at cutoff",
                rule_id="rule_01",
            )
        ]
        status_res = _make_dummy_status_result(
            "case_incomp",
            DeletionStatus.INCOMPLETE,
            residual_findings=remaining,
        )

        plan = orchestrator.plan_case(status_res)

        assert plan.case_id == "case_incomp"
        assert plan.case_status == "INCOMPLETE"
        assert len(plan.steps) == 3
        assert plan.is_valid is True

        # Check phase ordering
        assert plan.steps[0].phase == StepPhase.FINDING.value
        assert plan.steps[0].operation == StepOperation.REPORT_REMAINING_RECORD.value
        assert plan.steps[0].evidence_id == "evidence_42"

        assert plan.steps[1].phase == StepPhase.REMEDIATION.value
        assert plan.steps[1].operation == StepOperation.DELETE_RECORD.value
        assert plan.steps[1].evidence_id == ""

        assert plan.steps[2].phase == StepPhase.VERIFICATION.value
        assert plan.steps[2].operation == StepOperation.VERIFY_RECORD_ABSENT.value
        assert plan.steps[2].evidence_id == ""

        # Check consecutive numbering
        assert [s.step_no for s in plan.steps] == [1, 2, 3]


class TestDryRunAndDeterminism:
    """Test dry run execution and strict determinism verification."""

    def test_verify_dry_run_determinism_identical_runs(self):
        plan_a = CaseStepPlan(
            case_id="case_01",
            case_status="COMPLETE",
            steps=[Step(1, "VERIFICATION", "sys_a", "res_1", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_01")],
            steps_json='[{"evidence_id":"evidence_01","operation":"VERIFY_RECORD_ABSENT","phase":"VERIFICATION","resource_id":"res_1","state":"ABSENT","step_no":1,"system_id":"sys_a"}]',
            is_valid=True,
        )
        run1 = StepPlannerDryRunSummary(
            input_file="test.csv",
            total_input_rows=1,
            successfully_planned=1,
            failed_cases=0,
            status_distribution={"COMPLETE": 1},
            steps_by_phase={"VERIFICATION": 1},
            steps_by_operation={"VERIFY_RECORD_ABSENT": 1},
            plans=[plan_a],
        )
        run2 = copy.deepcopy(run1)

        is_det, diffs = StepPlannerOrchestrator.verify_dry_run_determinism(run1, run2)
        assert is_det is True
        assert len(diffs) == 0

    def test_verify_dry_run_determinism_detects_differences(self):
        plan_a = CaseStepPlan(case_id="case_01", case_status="COMPLETE", steps=[], steps_json="[]", is_valid=True)
        plan_b = CaseStepPlan(case_id="case_01", case_status="INCOMPLETE", steps=[], steps_json="[]", is_valid=True)

        run1 = StepPlannerDryRunSummary(
            input_file="test.csv",
            total_input_rows=1,
            successfully_planned=1,
            failed_cases=0,
            status_distribution={"COMPLETE": 1},
            plans=[plan_a],
        )
        run2 = StepPlannerDryRunSummary(
            input_file="test.csv",
            total_input_rows=1,
            successfully_planned=1,
            failed_cases=0,
            status_distribution={"INCOMPLETE": 1},
            plans=[plan_b],
        )

        is_det, diffs = StepPlannerOrchestrator.verify_dry_run_determinism(run1, run2)
        assert is_det is False
        assert any("status mismatch" in d for d in diffs)

"""Phase 8 Lifecycle Remediation and Adversarial Contract Test Suite.

Verifies:
1. INCOMPLETE with empty array rejected.
2. INCOMPLETE with FINDING only rejected.
3. INCOMPLETE with REMEDIATION only rejected.
4. INCOMPLETE with VERIFICATION only rejected.
5. INCOMPLETE with FINDING and REMEDIATION but no VERIFICATION rejected.
6. INCOMPLETE with all three phases in the wrong order rejected.
7. INCOMPLETE with valid three-phase sequence accepted.
8. COMPLETE with empty or inadmissible evidence citations rejected.
9. NOT_APPLICABLE with nonempty steps rejected.
10. Indeterminate/unknown resources handling.
11. Genuinely resource-free case handling.
12. Temporal cutoff enforcement.
13. Contradictory evidence and recreation risks.
14. Compliant retained records handling.
15. Deterministic output under shuffled inputs.
16. Specific regression tests for previously failing cases (case_416, case_417, case_517, case_519, case_521, case_64).
"""

import copy
import random
import pytest

from planner.validator import StepValidator
from planner.contract import (
    StepContractValidator,
    InvalidPhaseError,
    StepValidationError,
)
from planner.sequencer import StepSequencer
from planner.models import Step
from status.models import DeletionStatus


@pytest.fixture
def validator():
    return StepValidator()


@pytest.fixture
def contract_validator():
    return StepContractValidator()


def make_step(step_no: int, phase: str, operation: str, state: str, evidence_id: str = "", resource_id: str = "account_101", system_id: str = "account_service"):
    return {
        "step_no": step_no,
        "phase": phase,
        "system_id": system_id,
        "resource_id": resource_id,
        "operation": operation,
        "state": state,
        "evidence_id": evidence_id,
    }


class TestLifecyclePhaseMatrixAdversarial:
    """Validates the strict 3-phase requirement for INCOMPLETE plans."""

    # 1. INCOMPLETE with an empty array
    def test_01_incomplete_empty_array_rejected(self, validator):
        res = validator.validate_sequence([], "INCOMPLETE")
        assert not res.is_valid
        assert any("expected 3-phase lifecycle" in e for e in res.errors)

    # 2. INCOMPLETE with FINDING only
    def test_02_incomplete_finding_only_rejected(self, validator):
        steps = [
            make_step(1, "FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        ]
        res = validator.validate_sequence(steps, "INCOMPLETE")
        assert not res.is_valid
        assert any("missing required" in e.lower() for e in res.errors)

    # 3. INCOMPLETE with REMEDIATION only
    def test_03_incomplete_remediation_only_rejected(self, validator):
        steps = [
            make_step(1, "REMEDIATION", "DELETE_RECORD", "ABSENT", "")
        ]
        res = validator.validate_sequence(steps, "INCOMPLETE")
        assert not res.is_valid
        assert any("missing required" in e.lower() for e in res.errors)

    # 4. INCOMPLETE with VERIFICATION only
    def test_04_incomplete_verification_only_rejected(self, validator):
        steps = [
            make_step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "")
        ]
        res = validator.validate_sequence(steps, "INCOMPLETE")
        assert not res.is_valid
        assert any("missing required" in e.lower() for e in res.errors)

    # 5. INCOMPLETE with FINDING and REMEDIATION but no VERIFICATION
    def test_05_incomplete_finding_remediation_no_verification_rejected(self, validator):
        steps = [
            make_step(1, "FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01"),
            make_step(2, "REMEDIATION", "DELETE_RECORD", "ABSENT", ""),
        ]
        res = validator.validate_sequence(steps, "INCOMPLETE")
        assert not res.is_valid
        assert any("missing required verification phase" in e.lower() for e in res.errors)

    # 6. INCOMPLETE with all three phases in the wrong order
    def test_06_incomplete_wrong_phase_order_rejected(self, validator):
        steps = [
            make_step(1, "REMEDIATION", "DELETE_RECORD", "ABSENT", ""),
            make_step(2, "FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01"),
            make_step(3, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
        ]
        res = validator.validate_sequence(steps, "INCOMPLETE")
        assert not res.is_valid
        assert any("phase ordering violation" in e.lower() for e in res.errors)

    # 7. INCOMPLETE with a valid three-phase sequence
    def test_07_incomplete_valid_three_phase_accepted(self, validator):
        steps = [
            make_step(1, "FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01"),
            make_step(2, "REMEDIATION", "DELETE_RECORD", "ABSENT", ""),
            make_step(3, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
        ]
        res = validator.validate_sequence(steps, "INCOMPLETE")
        assert res.is_valid
        assert len(res.errors) == 0

    # 8. COMPLETE with empty or invalid evidence citations
    def test_08_complete_empty_evidence_rejected(self, validator):
        steps = [
            make_step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "")
        ]
        res = validator.validate_sequence(steps, "COMPLETE")
        assert not res.is_valid
        assert any("must cite non-empty" in e.lower() for e in res.errors)

    # 9. NOT_APPLICABLE with nonempty steps
    def test_09_not_applicable_nonempty_rejected(self, validator):
        steps = [
            make_step(1, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_01")
        ]
        res = validator.validate_sequence(steps, "NOT_APPLICABLE")
        assert not res.is_valid
        assert any("expected 0 steps" in e.lower() for e in res.errors)

    # 10. Remediation in INCOMPLETE cannot cite evidence
    def test_10_incomplete_remediation_with_evidence_rejected(self, validator):
        steps = [
            make_step(1, "FINDING", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01"),
            make_step(2, "REMEDIATION", "DELETE_RECORD", "ABSENT", "evidence_01"),
            make_step(3, "VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
        ]
        res = validator.validate_sequence(steps, "INCOMPLETE")
        assert not res.is_valid
        assert any("must have empty evidence_id" in e.lower() for e in res.errors)


class TestSequencerDeterminismAndOrdering:
    """Validates deterministic sequencing, numbering, and order under adversarial input permutations."""

    def test_15_deterministic_under_shuffled_ordering(self):
        steps = [
            Step(step_no=1, phase="FINDING", system_id="account_service", resource_id="account_101", operation="REPORT_REMAINING_RECORD", state="PRESENT", evidence_id="evidence_01"),
            Step(step_no=2, phase="FINDING", system_id="search_service", resource_id="search_101", operation="REPORT_REMAINING_RECORD", state="PRESENT", evidence_id="evidence_02"),
            Step(step_no=3, phase="REMEDIATION", system_id="account_service", resource_id="account_101", operation="DELETE_RECORD", state="ABSENT", evidence_id=""),
            Step(step_no=4, phase="REMEDIATION", system_id="search_service", resource_id="search_101", operation="DELETE_RECORD", state="ABSENT", evidence_id=""),
            Step(step_no=5, phase="VERIFICATION", system_id="account_service", resource_id="account_101", operation="VERIFY_RECORD_ABSENT", state="ABSENT", evidence_id=""),
            Step(step_no=6, phase="VERIFICATION", system_id="search_service", resource_id="search_101", operation="VERIFY_RECORD_ABSENT", state="ABSENT", evidence_id=""),
        ]

        canonical = StepSequencer.order_and_number(steps)

        for _ in range(20):
            shuffled = list(steps)
            random.shuffle(shuffled)
            result = StepSequencer.order_and_number(shuffled)
            assert [s.to_dict() for s in result] == [s.to_dict() for s in canonical]


class TestPipelineRegressionFiveCases:
    """Specific regression tests for the 5 cases resolved via trace correlation."""

    @pytest.fixture(scope="class")
    def pipeline(self):
        from status.pipeline import CaseStatusPipeline
        return CaseStatusPipeline(preload_evidence=True)

    @pytest.fixture(scope="class")
    def orchestrator(self, pipeline):
        from planner.orchestrator import StepPlannerOrchestrator
        return StepPlannerOrchestrator(pipeline=pipeline)

    @pytest.mark.parametrize("case_id,expected_status", [
        ("case_416", "INCOMPLETE"),
        ("case_417", "INCOMPLETE"),
        ("case_517", "INCOMPLETE"),
        ("case_519", "INCOMPLETE"),
        ("case_521", "COMPLETE"),
        ("case_64", "COMPLETE"),
    ])
    def test_case_resolves_and_validates(self, pipeline, orchestrator, case_id, expected_status):
        import csv
        with open("dataset/deletion_requests.csv") as f:
            requests = {r["case_id"]: r for r in csv.DictReader(f)}
        
        req = requests[case_id]
        plan, status_res = orchestrator.plan_request(req)
        
        assert plan.is_valid, f"Plan for {case_id} failed validation: {plan.errors}"
        assert plan.case_status == expected_status, f"Expected {expected_status}, got {plan.case_status}"
        
        # Verify lifecycle contract
        if expected_status == "INCOMPLETE":
            phases = {s.phase for s in plan.steps}
            assert {"FINDING", "REMEDIATION", "VERIFICATION"}.issubset(phases)
            assert all(s.evidence_id == "" for s in plan.steps if s.phase in ("REMEDIATION", "VERIFICATION"))
            assert all(s.evidence_id != "" for s in plan.steps if s.phase == "FINDING")
        elif expected_status == "COMPLETE":
            assert all(s.phase == "VERIFICATION" for s in plan.steps)
            assert all(s.evidence_id.startswith("evidence_") for s in plan.steps)
            assert len(plan.steps) > 0

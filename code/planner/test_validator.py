"""Tests for Phase 8 Chunk 8.2: Step Validator (Structural, Contextual, Sequence).

Validates:
1. Structural validator non-throwing behavior.
2. Contextual validator for COMPLETE cases (only VERIFICATION, evidence required).
3. Contextual validator for INCOMPLETE cases (FINDING has evidence, REMED/VERIF empty).
4. Contextual validator for NOT_APPLICABLE cases (zero steps permitted).
5. Sequence validator: 1-indexed consecutive numbering.
6. Sequence validator: phase order (FINDING -> REMEDIATION -> VERIFICATION).
"""

from pathlib import Path
import sys
import pytest

CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from planner.models import Step
from planner.validator import (
    StepValidator,
    ContextualValidationContext,
    validate_step_structure,
    validate_step_context,
)


class TestStructuralValidator:
    """Tests for pure structural validation functions."""

    def test_validate_step_structure_valid_dict(self):
        d = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_01",
        }
        res = validate_step_structure(d)
        assert res.is_valid
        assert len(res.errors) == 0

    def test_validate_step_structure_invalid_dict(self):
        d = {
            "step_no": -1,  # Invalid
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_01",
        }
        res = validate_step_structure(d)
        assert not res.is_valid
        assert any("step_no must be a positive integer" in e for e in res.errors)

    def test_validate_step_structure_existing_step(self):
        step = Step(
            step_no=1,
            phase="VERIFICATION",
            system_id="account_service",
            resource_id="account_005",
            operation="VERIFY_RECORD_ABSENT",
            state="ABSENT",
            evidence_id="evidence_01",
        )
        res = validate_step_structure(step)
        assert res.is_valid


class TestContextualValidator:
    """Tests for contextual validation based on case status and evidence admissibility."""

    def test_complete_case_valid_verification(self):
        step = Step(
            step_no=1,
            phase="VERIFICATION",
            system_id="account_service",
            resource_id="account_005",
            operation="VERIFY_RECORD_ABSENT",
            state="ABSENT",
            evidence_id="evidence_01",
        )
        ctx = ContextualValidationContext(
            case_id="case_01",
            case_status="COMPLETE",
            admissible_evidence_ids={"evidence_01", "evidence_02"},
        )
        res = validate_step_context(step, ctx)
        assert res.is_valid

    def test_complete_case_rejects_finding_or_remediation(self):
        finding_step = Step(
            step_no=1,
            phase="FINDING",
            system_id="account_service",
            resource_id="account_005",
            operation="REPORT_REMAINING_RECORD",
            state="PRESENT",
            evidence_id="evidence_01",
        )
        ctx = ContextualValidationContext(case_id="case_01", case_status="COMPLETE")
        res = validate_step_context(finding_step, ctx)
        assert not res.is_valid
        assert any("only VERIFICATION steps are permitted" in e for e in res.errors)

    def test_complete_case_rejects_empty_evidence_id(self):
        step = Step(
            step_no=1,
            phase="VERIFICATION",
            system_id="account_service",
            resource_id="account_005",
            operation="VERIFY_RECORD_ABSENT",
            state="ABSENT",
            evidence_id="",  # Empty forbidden in COMPLETE
        )
        ctx = ContextualValidationContext(case_id="case_01", case_status="COMPLETE")
        res = validate_step_context(step, ctx)
        assert not res.is_valid
        assert any("must cite non-empty admissible evidence" in e for e in res.errors)

    def test_incomplete_case_valid_lifecycle(self):
        finding = Step(
            step_no=1,
            phase="FINDING",
            system_id="account_service",
            resource_id="account_005",
            operation="REPORT_REMAINING_RECORD",
            state="PRESENT",
            evidence_id="evidence_01",
        )
        remediation = Step(
            step_no=2,
            phase="REMEDIATION",
            system_id="account_service",
            resource_id="account_005",
            operation="DELETE_RECORD",
            state="ABSENT",
            evidence_id="",
        )
        verification = Step(
            step_no=3,
            phase="VERIFICATION",
            system_id="account_service",
            resource_id="account_005",
            operation="VERIFY_RECORD_ABSENT",
            state="ABSENT",
            evidence_id="",
        )
        ctx = ContextualValidationContext(
            case_id="case_02",
            case_status="INCOMPLETE",
            admissible_evidence_ids={"evidence_01"},
        )
        assert validate_step_context(finding, ctx).is_valid
        assert validate_step_context(remediation, ctx).is_valid
        assert validate_step_context(verification, ctx).is_valid

    def test_incomplete_case_rejects_finding_with_empty_evidence(self):
        finding = Step(
            step_no=1,
            phase="FINDING",
            system_id="account_service",
            resource_id="account_005",
            operation="REPORT_REMAINING_RECORD",
            state="PRESENT",
            evidence_id="",  # Empty forbidden for FINDING
        )
        ctx = ContextualValidationContext(case_id="case_02", case_status="INCOMPLETE")
        res = validate_step_context(finding, ctx)
        assert not res.is_valid
        assert any("must cite proving evidence_id" in e for e in res.errors)

    def test_incomplete_case_rejects_remediation_with_evidence(self):
        remediation = Step(
            step_no=1,
            phase="REMEDIATION",
            system_id="account_service",
            resource_id="account_005",
            operation="DELETE_RECORD",
            state="ABSENT",
            evidence_id="evidence_01",  # Forbidden for proposed REMEDIATION
        )
        ctx = ContextualValidationContext(case_id="case_02", case_status="INCOMPLETE")
        res = validate_step_context(remediation, ctx)
        assert not res.is_valid
        assert any("must have empty evidence_id" in e for e in res.errors)

    def test_not_applicable_case_rejects_any_step(self):
        step = Step(
            step_no=1,
            phase="VERIFICATION",
            system_id="account_service",
            resource_id="account_005",
            operation="VERIFY_RECORD_ABSENT",
            state="ABSENT",
            evidence_id="evidence_01",
        )
        ctx = ContextualValidationContext(case_id="case_03", case_status="NOT_APPLICABLE")
        res = validate_step_context(step, ctx)
        assert not res.is_valid
        assert any("NOT_APPLICABLE; no steps are permitted" in e for e in res.errors)


class TestSequenceValidator:
    """Tests for validating multi-step sequence invariants."""

    def test_valid_incomplete_sequence(self):
        steps = [
            Step(1, "FINDING", "sys_1", "res_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01"),
            Step(2, "REMEDIATION", "sys_1", "res_1", "DELETE_RECORD", "ABSENT", ""),
            Step(3, "VERIFICATION", "sys_1", "res_1", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
        ]
        ctx = ContextualValidationContext(case_status="INCOMPLETE")
        res = StepValidator.validate_sequence(steps, ctx)
        assert res.is_valid

    def test_gap_in_step_numbering_rejected(self):
        steps = [
            Step(1, "FINDING", "sys_1", "res_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01"),
            Step(3, "REMEDIATION", "sys_1", "res_1", "DELETE_RECORD", "ABSENT", ""),  # Skipped 2
        ]
        res = StepValidator.validate_sequence(steps)
        assert not res.is_valid
        assert any("Step numbering gap: expected step_no=2 at index 1, got step_no=3" in e for e in res.errors)

    def test_out_of_order_phases_rejected(self):
        # VERIFICATION before REMEDIATION
        steps = [
            Step(1, "VERIFICATION", "sys_1", "res_1", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
            Step(2, "REMEDIATION", "sys_1", "res_1", "DELETE_RECORD", "ABSENT", ""),
        ]
        res = StepValidator.validate_sequence(steps)
        assert not res.is_valid
        assert any("Phase ordering violation" in e for e in res.errors)

    def test_not_applicable_sequence_must_be_empty(self):
        ctx = ContextualValidationContext(case_status="NOT_APPLICABLE")
        # Empty list is valid
        assert StepValidator.validate_sequence([], ctx).is_valid

        # Non-empty list is invalid
        steps = [Step(1, "VERIFICATION", "sys_1", "res_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_1")]
        res = StepValidator.validate_sequence(steps, ctx)
        assert not res.is_valid
        assert any("expected 0 steps, got 1" in e for e in res.errors)

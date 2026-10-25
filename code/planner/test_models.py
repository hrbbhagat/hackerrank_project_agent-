"""Tests for Phase 8 Chunk 8.2: Typed Step Models and Structural Validation.

Validates:
1. Valid examples from the challenge contract.
2. Every permitted phase.
3. Every permitted (phase, operation, state) combination (all 15).
4. Missing required fields.
5. Extra unknown fields rejection.
6. Incorrect field types.
7. Invalid phases.
8. Invalid operation/state combinations.
9. Invalid step numbers (including bool, 0, negative, float).
10. Empty and non-empty evidence_id handling.
11. Deterministic serialization and JSON round-trip.
"""

import json
from pathlib import Path
import sys
import pytest

CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from planner.models import (
    Step,
    StepPhase,
    StepOperation,
    StepState,
    PERMITTED_COMBINATIONS,
    REQUIRED_STEP_FIELDS,
    StepValidationError,
    StepFieldMissingError,
    StepFieldTypeError,
    StepNumberError,
    InvalidPhaseError,
    InvalidOperationStateError,
    ExtraFieldsError,
)


class TestStepModelCreation:
    """Tests for basic and contract-valid step creation."""

    def test_valid_challenge_example(self):
        """Test exact example given in AGENTS.md §6.3 and problem_statement.md."""
        step = Step(
            step_no=1,
            phase="FINDING",
            system_id="account_service",
            resource_id="account_005",
            operation="REPORT_REMAINING_RECORD",
            state="PRESENT",
            evidence_id="evidence_01",
        )
        assert step.step_no == 1
        assert step.phase == "FINDING"
        assert step.system_id == "account_service"
        assert step.resource_id == "account_005"
        assert step.operation == "REPORT_REMAINING_RECORD"
        assert step.state == "PRESENT"
        assert step.evidence_id == "evidence_01"

    def test_all_permitted_phases_supported(self):
        """Verify each of the 3 challenge phases can be instantiated with valid operations."""
        # Finding
        s_finding = Step(
            step_no=1,
            phase="FINDING",
            system_id="support_platform",
            resource_id="ticket_901",
            operation="REPORT_EXPOSED_PII",
            state="PRESENT",
            evidence_id="evidence_44",
        )
        assert s_finding.phase == StepPhase.FINDING.value

        # Remediation
        s_remed = Step(
            step_no=2,
            phase="REMEDIATION",
            system_id="analytics_platform",
            resource_id="profile_101",
            operation="ANONYMIZE_RECORD",
            state="ANONYMIZED",
            evidence_id="",
        )
        assert s_remed.phase == StepPhase.REMEDIATION.value

        # Verification
        s_verif = Step(
            step_no=3,
            phase="VERIFICATION",
            system_id="backup_service",
            resource_id="snapshot_99",
            operation="VERIFY_RESTORE_BLOCKED",
            state="BLOCKED",
            evidence_id="",
        )
        assert s_verif.phase == StepPhase.VERIFICATION.value

    @pytest.mark.parametrize("phase,operation,state", list(PERMITTED_COMBINATIONS))
    def test_all_15_permitted_combinations_accepted(self, phase, operation, state):
        """Strictly test that every one of the 15 challenge combinations passes validation."""
        step = Step(
            step_no=1,
            phase=phase,
            system_id="test_system",
            resource_id="test_res",
            operation=operation,
            state=state,
            evidence_id="evidence_test" if phase == "FINDING" else "",
        )
        assert step.phase == phase
        assert step.operation == operation
        assert step.state == state


class TestStepNumberValidation:
    """Tests strictly validating step_no type and value constraints."""

    def test_reject_bool_as_step_no(self):
        """In Python, bool is a subclass of int. True and False must be rejected."""
        with pytest.raises(StepFieldTypeError, match="step_no must be an int"):
            Step(
                step_no=True,  # type: ignore
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

        with pytest.raises(StepFieldTypeError, match="step_no must be an int"):
            Step(
                step_no=False,  # type: ignore
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

    @pytest.mark.parametrize("invalid_no", [0, -1, -42])
    def test_reject_non_positive_integers(self, invalid_no):
        """step_no must be >= 1."""
        with pytest.raises(StepNumberError, match="positive integer >= 1"):
            Step(
                step_no=invalid_no,
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

    @pytest.mark.parametrize("invalid_type", ["1", 1.0, 2.5, None, [1]])
    def test_reject_non_int_types(self, invalid_type):
        """step_no must not be string, float, None, or collection."""
        with pytest.raises(StepFieldTypeError, match="step_no must be an int"):
            Step(
                step_no=invalid_type,  # type: ignore
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )


class TestFieldTypeAndContentValidation:
    """Tests for validating string fields, empty checks, and phase/op constraints."""

    def test_reject_empty_system_or_resource_id(self):
        """system_id and resource_id cannot be empty or pure whitespace."""
        with pytest.raises(StepValidationError, match="system_id cannot be empty"):
            Step(
                step_no=1,
                phase="FINDING",
                system_id="   ",
                resource_id="res_1",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

        with pytest.raises(StepValidationError, match="resource_id cannot be empty"):
            Step(
                step_no=1,
                phase="FINDING",
                system_id="sys_1",
                resource_id="",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

    def test_reject_invalid_phase(self):
        """Phases other than FINDING, REMEDIATION, VERIFICATION are rejected."""
        with pytest.raises(InvalidPhaseError, match="Invalid phase 'AUDIT'"):
            Step(
                step_no=1,
                phase="AUDIT",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

        with pytest.raises(InvalidPhaseError, match="Invalid phase 'finding'"):
            Step(
                step_no=1,
                phase="finding",  # Lowercase forbidden
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

    def test_reject_invalid_operation(self):
        """Unrecognized operations are rejected."""
        with pytest.raises(InvalidOperationStateError, match="Invalid operation 'WIPE_DATABASE'"):
            Step(
                step_no=1,
                phase="REMEDIATION",
                system_id="sys",
                resource_id="res",
                operation="WIPE_DATABASE",
                state="ABSENT",
                evidence_id="",
            )

    def test_reject_invalid_state(self):
        """Unrecognized states are rejected."""
        with pytest.raises(InvalidOperationStateError, match="Invalid state 'PURGED'"):
            Step(
                step_no=1,
                phase="REMEDIATION",
                system_id="sys",
                resource_id="res",
                operation="DELETE_RECORD",
                state="PURGED",
                evidence_id="",
            )

    def test_reject_mismatched_operation_state_pair(self):
        """Valid operations paired with invalid states for that operation are rejected."""
        # DELETE_RECORD expects ABSENT, not PRESENT
        with pytest.raises(InvalidOperationStateError, match="Invalid challenge step combination"):
            Step(
                step_no=1,
                phase="REMEDIATION",
                system_id="sys",
                resource_id="res",
                operation="DELETE_RECORD",
                state="PRESENT",
                evidence_id="",
            )

        # REPORT_REMAINING_RECORD cannot be in REMEDIATION phase
        with pytest.raises(InvalidOperationStateError, match="Invalid challenge step combination"):
            Step(
                step_no=1,
                phase="REMEDIATION",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="ev_1",
            )

        # VERIFY_RECORD_ABSENT cannot be in FINDING phase
        with pytest.raises(InvalidOperationStateError, match="Invalid challenge step combination"):
            Step(
                step_no=1,
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation="VERIFY_RECORD_ABSENT",
                state="ABSENT",
                evidence_id="ev_1",
            )

    def test_reject_non_str_evidence_id(self):
        """evidence_id must be str (can be empty str, but not None or int)."""
        with pytest.raises(StepFieldTypeError, match="evidence_id must be a str"):
            Step(
                step_no=1,
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id=None,  # type: ignore
            )


class TestDictionaryAndJsonParsing:
    """Tests for from_dict and from_json factory methods."""

    def test_from_dict_valid(self):
        """Test constructing Step from valid dictionary."""
        d = {
            "step_no": 1,
            "phase": "REMEDIATION",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "DELETE_RECORD",
            "state": "ABSENT",
            "evidence_id": "",
        }
        step = Step.from_dict(d)
        assert step.step_no == 1
        assert step.operation == "DELETE_RECORD"

    def test_from_dict_rejects_non_dict(self):
        """Input must be a mapping."""
        with pytest.raises(StepFieldTypeError, match="Input data must be a dictionary"):
            Step.from_dict(["not", "a", "dict"])  # type: ignore

    @pytest.mark.parametrize("field_to_remove", REQUIRED_STEP_FIELDS)
    def test_from_dict_rejects_missing_field(self, field_to_remove):
        """Each of the 7 contract fields is strictly required."""
        d = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_01",
        }
        del d[field_to_remove]
        with pytest.raises(StepFieldMissingError, match="Missing required step fields"):
            Step.from_dict(d)

    def test_from_dict_rejects_extra_fields_by_default(self):
        """Unrecognized fields must be rejected to prevent schema leakage."""
        d = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_01",
            "confidence": 0.99,  # Extraneous field
            "reason": "debug note",  # Extraneous field
        }
        with pytest.raises(ExtraFieldsError, match="Unrecognized fields in step data"):
            Step.from_dict(d)

    def test_from_dict_allow_extra_when_explicitly_requested(self):
        """allow_extra=True allows ignoring extra fields when requested."""
        d = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_01",
            "extra_metadata": "ignored",
        }
        step = Step.from_dict(d, allow_extra=True)
        assert step.step_no == 1
        # Extraneous field is not attached to step
        assert not hasattr(step, "extra_metadata")

    def test_from_json_valid_and_invalid(self):
        """Test parsing JSON strings."""
        valid_json = json.dumps({
            "step_no": 2,
            "phase": "REMEDIATION",
            "system_id": "integration_service",
            "resource_id": "data_flow_9522",
            "operation": "DISABLE_DATA_FLOW",
            "state": "DISABLED",
            "evidence_id": "",
        })
        step = Step.from_json(valid_json)
        assert step.step_no == 2
        assert step.operation == "DISABLE_DATA_FLOW"

        # Malformed JSON
        with pytest.raises(StepValidationError, match="Invalid JSON string"):
            Step.from_json("{not valid json")


class TestSerializationContract:
    """Tests ensuring deterministic serialization to the exact 7 contract fields."""

    def test_to_dict_exact_keys_and_types(self):
        """to_dict must return exactly the 7 contract fields without extraneous metadata."""
        step = Step(
            step_no=1,
            phase="VERIFICATION",
            system_id="account_service",
            resource_id="account_005",
            operation="VERIFY_RECORD_ABSENT",
            state="ABSENT",
            evidence_id="evidence_99",
        )
        serialized = step.to_dict()
        assert tuple(serialized.keys()) == REQUIRED_STEP_FIELDS
        assert serialized == {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "evidence_99",
        }

    def test_to_json_round_trip(self):
        """Round-trip: Step -> JSON string -> Step must preserve all fields deterministically."""
        original = Step(
            step_no=5,
            phase="REMEDIATION",
            system_id="backup_service",
            resource_id="snapshot_001",
            operation="BLOCK_RESTORE",
            state="BLOCKED",
            evidence_id="",
        )
        json_str = original.to_json()
        reconstituted = Step.from_json(json_str)
        assert original == reconstituted
        assert reconstituted.to_dict() == original.to_dict()

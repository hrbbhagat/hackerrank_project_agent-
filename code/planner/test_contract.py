"""Exhaustive tests for Phase 8 Chunk 8.6: Strict Operation, State, and Phase Contract Enforcement.

Tests:
1. Exact vocabulary enumeration (3 phases, 15 operations, 7 states, 15 combinations, 7 fields).
2. All 15 permitted challenge combinations accepted.
3. All 300 invalid combinations from valid vocabularies rejected.
4. Correct operation with incorrect state rejected.
5. Correct operation/state with incorrect phase rejected.
6. Unknown operations rejected (including invented operations, casing, whitespace).
7. Unknown states rejected (including casing, whitespace).
8. Unknown phases rejected (including casing, whitespace).
9. Missing required fields (each of the 7 fields tested individually and combined).
10. Unexpected output fields rejected.
11. Invalid evidence_id types rejected.
12. Invalid step_no types and values (bool, 0, negative, float, str).
13. Invalid system_id and resource_id (empty, whitespace, non-str).
14. Canonical operation order and lookup helper methods.
"""

from __future__ import annotations

import itertools
from pathlib import Path
import sys
import pytest

# Setup path imports safely
CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from planner.contract import (
    StepPhase,
    StepOperation,
    StepState,
    REQUIRED_STEP_FIELDS,
    PERMITTED_PHASES,
    PERMITTED_OPERATIONS,
    PERMITTED_STATES,
    PERMITTED_COMBINATIONS,
    OPERATION_TO_PHASE,
    OPERATION_TO_STATE,
    PHASE_TO_OPERATIONS,
    OPERATION_CANONICAL_INDEX,
    StepValidationError,
    StepFieldMissingError,
    StepFieldTypeError,
    StepNumberError,
    InvalidPhaseError,
    InvalidOperationError,
    InvalidStateError,
    InvalidOperationStateError,
    ExtraFieldsError,
    ContractValidationResult,
    StepContractValidator,
)
from planner.models import Step
from planner.validator import StepValidator, ValidationResult


# =============================================================================
# 1. Authoritative Vocabulary Counts and Invariants
# =============================================================================

class TestContractVocabularyInvariants:
    """Verify that the contract contains exactly the official challenge elements."""

    def test_exact_phase_count(self):
        assert len(StepPhase) == 3
        assert set(PERMITTED_PHASES) == {"FINDING", "REMEDIATION", "VERIFICATION"}

    def test_exact_operation_count(self):
        assert len(StepOperation) == 15
        assert len(PERMITTED_OPERATIONS) == 15
        # 4 findings, 5 remediations, 6 verifications
        assert len(PHASE_TO_OPERATIONS["FINDING"]) == 4
        assert len(PHASE_TO_OPERATIONS["REMEDIATION"]) == 5
        assert len(PHASE_TO_OPERATIONS["VERIFICATION"]) == 6

    def test_exact_state_count(self):
        assert len(StepState) == 7
        assert set(PERMITTED_STATES) == {
            "PRESENT",
            "ACTIVE",
            "DISABLED",
            "BLOCKED",
            "ABSENT",
            "REDACTED",
            "ANONYMIZED",
        }

    def test_exact_permitted_combinations_count(self):
        assert len(PERMITTED_COMBINATIONS) == 15

    def test_exact_required_step_fields(self):
        assert REQUIRED_STEP_FIELDS == (
            "step_no",
            "phase",
            "system_id",
            "resource_id",
            "operation",
            "state",
            "evidence_id",
        )

    def test_every_operation_has_unique_phase_and_state(self):
        """Every single challenge operation maps to exactly one phase and one state."""
        for op in PERMITTED_OPERATIONS:
            assert op in OPERATION_TO_PHASE
            assert op in OPERATION_TO_STATE
            expected_phase = OPERATION_TO_PHASE[op]
            expected_state = OPERATION_TO_STATE[op]
            assert (expected_phase, op, expected_state) in PERMITTED_COMBINATIONS


# =============================================================================
# 2. Acceptance of All 15 Permitted Combinations
# =============================================================================

class TestPermittedCombinationsAcceptance:
    """Ensure all 15 official challenge combinations are accepted by all validation interfaces."""

    @pytest.mark.parametrize("phase,operation,state", sorted(list(PERMITTED_COMBINATIONS)))
    def test_validator_accepts_permitted_combination(self, phase, operation, state):
        # 1. Direct predicate check
        assert StepContractValidator.is_valid_combination(phase, operation, state) is True
        assert StepValidator.is_valid_combination(phase, operation, state) is True

        # 2. Semantic combination validation returns no errors
        errors = StepContractValidator.validate_semantic_combination(phase, operation, state)
        assert errors == []

        # 3. Full step validation succeeds
        step_dict = {
            "step_no": 1,
            "phase": phase,
            "system_id": "account_service",
            "resource_id": "account_001",
            "operation": operation,
            "state": state,
            "evidence_id": "evidence_01" if phase == "FINDING" else "",
        }
        res = StepContractValidator.validate_step(step_dict)
        assert res.is_valid is True
        assert res.errors == []

        # 4. Step instantiation succeeds
        step = Step(**step_dict)
        assert step.phase == phase
        assert step.operation == operation
        assert step.state == state


# =============================================================================
# 3. Exhaustive Rejection of All 300 Invalid Semantic Combinations
# =============================================================================

# Cartesian product of 3 phases * 15 operations * 7 states = 315 combinations
ALL_POSSIBLE_COMBINATIONS = set(
    itertools.product(
        sorted(list(PERMITTED_PHASES)),
        sorted(list(PERMITTED_OPERATIONS)),
        sorted(list(PERMITTED_STATES)),
    )
)
INVALID_COMBINATIONS = sorted(list(ALL_POSSIBLE_COMBINATIONS - set(PERMITTED_COMBINATIONS)))


class TestExhaustiveInvalidCombinationsRejection:
    """Tests all 300 invalid combinations from valid vocabularies."""

    def test_invalid_combinations_count_is_300(self):
        assert len(INVALID_COMBINATIONS) == 300

    @pytest.mark.parametrize("phase,operation,state", INVALID_COMBINATIONS)
    def test_reject_every_unsupported_semantic_combination(self, phase, operation, state):
        # 1. Direct predicate check must return False
        assert StepContractValidator.is_valid_combination(phase, operation, state) is False
        assert StepValidator.is_valid_combination(phase, operation, state) is False

        # 2. Semantic combination validation must return non-empty errors
        errors = StepContractValidator.validate_semantic_combination(phase, operation, state)
        assert len(errors) > 0

        # 3. Full step validation must return failure
        step_dict = {
            "step_no": 1,
            "phase": phase,
            "system_id": "sys",
            "resource_id": "res",
            "operation": operation,
            "state": state,
            "evidence_id": "",
        }
        res = StepContractValidator.validate_step(step_dict)
        assert res.is_valid is False
        assert len(res.errors) > 0

        # 4. Step instantiation must raise InvalidOperationStateError
        with pytest.raises(InvalidOperationStateError):
            Step(**step_dict)


# =============================================================================
# 4. Specific Mismatch Scenarios: Operation vs Phase vs State
# =============================================================================

class TestSpecificMismatchDiagnostics:
    """Verify informative, deterministic diagnostics for targeted mismatches."""

    def test_correct_operation_with_wrong_phase(self):
        """A finding operation placed in REMEDIATION or VERIFICATION."""
        errors = StepContractValidator.validate_semantic_combination(
            phase="REMEDIATION",
            operation="REPORT_REMAINING_RECORD",
            state="PRESENT",
        )
        assert len(errors) == 1
        assert "Phase mismatch for operation 'REPORT_REMAINING_RECORD': expected phase 'FINDING', got 'REMEDIATION'" in errors[0]

    def test_correct_operation_with_wrong_state(self):
        """A remediation operation with wrong state."""
        errors = StepContractValidator.validate_semantic_combination(
            phase="REMEDIATION",
            operation="DELETE_RECORD",
            state="PRESENT",  # DELETE_RECORD requires ABSENT
        )
        assert len(errors) == 1
        assert "State mismatch for operation 'DELETE_RECORD': expected state 'ABSENT', got 'PRESENT'" in errors[0]

    def test_correct_operation_with_both_phase_and_state_wrong(self):
        """Operation with both phase and state mismatched."""
        errors = StepContractValidator.validate_semantic_combination(
            phase="VERIFICATION",
            operation="DISABLE_DATA_FLOW",
            state="ACTIVE",  # Requires REMEDIATION and DISABLED
        )
        assert len(errors) == 1
        assert "Operation 'DISABLE_DATA_FLOW' requires phase 'REMEDIATION' and state 'DISABLED', got phase 'VERIFICATION' and state 'ACTIVE'" in errors[0]


# =============================================================================
# 5. Unknown, Invented, or Mutated Vocabulary
# =============================================================================

class TestUnknownAndMutatedVocabulary:
    """Verify that unknown, lowercase, whitespace-padded, or invented values are rejected."""

    @pytest.mark.parametrize("unknown_op", [
        "RESTORE_RECORD",  # Common trap: not in challenge
        "UNKNOWN_OPERATION",
        "GET_RECORD",
        "UPDATE_PII",
        "PURGE_DATA",
        "",
        " ",
        "report_remaining_record",  # lowercase
        "Report_Remaining_Record",  # mixed case
        " REPORT_REMAINING_RECORD ",  # whitespace padded
        "REPORT_REMAINING_RECORD\n",
    ])
    def test_reject_unknown_operation(self, unknown_op):
        assert StepContractValidator.is_valid_operation(unknown_op) is False
        errors = StepContractValidator.validate_operation(unknown_op)
        assert len(errors) > 0
        assert "Invalid operation" in errors[0]

        with pytest.raises(InvalidOperationStateError):
            Step(
                step_no=1,
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation=unknown_op,
                state="PRESENT",
                evidence_id="",
            )

    @pytest.mark.parametrize("unknown_state", [
        "COMPLETED",
        "DONE",
        "SUCCESS",
        "FAILED",
        "PENDING",
        "",
        " ",
        "present",  # lowercase
        "Present",  # mixed case
        " PRESENT ",  # whitespace padded
    ])
    def test_reject_unknown_state(self, unknown_state):
        assert StepContractValidator.is_valid_state(unknown_state) is False
        errors = StepContractValidator.validate_state(unknown_state)
        assert len(errors) > 0
        assert "Invalid state" in errors[0]

        with pytest.raises(InvalidOperationStateError):
            Step(
                step_no=1,
                phase="FINDING",
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state=unknown_state,
                evidence_id="",
            )

    @pytest.mark.parametrize("unknown_phase", [
        "AUDIT",
        "DISCOVERY",
        "EXECUTION",
        "REMEDIATE",
        "",
        " ",
        "finding",  # lowercase
        "Finding",  # mixed case
        " FINDING ",  # whitespace padded
    ])
    def test_reject_unknown_phase(self, unknown_phase):
        assert StepContractValidator.is_valid_phase(unknown_phase) is False
        errors = StepContractValidator.validate_phase(unknown_phase)
        assert len(errors) > 0
        assert "Invalid phase" in errors[0]

        with pytest.raises(InvalidPhaseError):
            Step(
                step_no=1,
                phase=unknown_phase,
                system_id="sys",
                resource_id="res",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                evidence_id="",
            )


# =============================================================================
# 6. Missing Required Fields Rejection
# =============================================================================

class TestMissingFieldsRejection:
    """Verify rejection when any of the 7 contract fields is omitted."""

    @pytest.mark.parametrize("missing_field", list(REQUIRED_STEP_FIELDS))
    def test_reject_individual_missing_field(self, missing_field):
        base_step = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_01",
        }
        del base_step[missing_field]

        # Validator checks
        errors = StepContractValidator.validate_step_fields(base_step)
        assert len(errors) == 1
        assert f"Missing required step fields: ['{missing_field}']" in errors[0]

        # Step.from_dict checks
        with pytest.raises(StepFieldMissingError) as exc_info:
            Step.from_dict(base_step)
        assert missing_field in str(exc_info.value)

    def test_reject_empty_dict(self):
        errors = StepContractValidator.validate_step_fields({})
        assert len(errors) == 1
        assert "Missing required step fields" in errors[0]


# =============================================================================
# 7. Unexpected / Extra Output Fields Rejection
# =============================================================================

class TestUnexpectedFieldsRejection:
    """Verify that unexpected extra fields are rejected when allow_extra is False."""

    def test_reject_extra_fields(self):
        step_dict = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "account_005",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "evidence_01",
            "extra_field": "unauthorized",
            "timestamp": "2026-04-04T00:00:00Z",
        }

        # Validator checks
        errors = StepContractValidator.validate_step_fields(step_dict, allow_extra=False)
        assert len(errors) == 1
        assert "Unrecognized fields in step data: ['extra_field', 'timestamp']" in errors[0]

        # Step.from_dict checks
        with pytest.raises(ExtraFieldsError) as exc_info:
            Step.from_dict(step_dict, allow_extra=False)
        assert "extra_field" in str(exc_info.value)


# =============================================================================
# 8. Type Validation for step_no, evidence_id, system_id, resource_id
# =============================================================================

class TestFieldTypesValidation:
    """Verify strict type rules across all contract fields."""

    @pytest.mark.parametrize("bad_step_no", [True, False, 0, -1, -99, 1.5, "1", None, [1]])
    def test_reject_invalid_step_no(self, bad_step_no):
        step_dict = {
            "step_no": bad_step_no,
            "phase": "FINDING",
            "system_id": "sys",
            "resource_id": "res",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "ev",
        }
        errors = StepContractValidator.validate_step_fields(step_dict)
        assert len(errors) > 0
        assert any("step_no" in e for e in errors)

        with pytest.raises((StepFieldTypeError, StepNumberError)):
            Step(**step_dict)

    @pytest.mark.parametrize("bad_evidence_id", [None, 123, True, False, ["ev_1"], {"id": "ev_1"}])
    def test_reject_invalid_evidence_id_type(self, bad_evidence_id):
        step_dict = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "sys",
            "resource_id": "res",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": bad_evidence_id,
        }
        errors = StepContractValidator.validate_step_fields(step_dict)
        assert len(errors) > 0
        assert any("evidence_id must be a str" in e for e in errors)

        with pytest.raises(StepFieldTypeError):
            Step(**step_dict)

    @pytest.mark.parametrize("bad_str_field", ["", "   ", "\t\n"])
    def test_reject_empty_or_whitespace_identifiers(self, bad_str_field):
        # Empty system_id
        step_dict_sys = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": bad_str_field,
            "resource_id": "res",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "ev",
        }
        errors = StepContractValidator.validate_step_fields(step_dict_sys)
        assert any("system_id cannot be empty or whitespace" in e for e in errors)

        # Empty resource_id
        step_dict_res = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "sys",
            "resource_id": bad_str_field,
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "ev",
        }
        errors = StepContractValidator.validate_step_fields(step_dict_res)
        assert any("resource_id cannot be empty or whitespace" in e for e in errors)


# =============================================================================
# 9. Operation Canonical Order and Helpers
# =============================================================================

class TestOperationCanonicalOrderAndHelpers:
    """Test lookup helpers and canonical intra-phase indices."""

    def test_get_expected_phase_and_state(self):
        assert StepContractValidator.get_expected_phase("REPORT_REMAINING_RECORD") == "FINDING"
        assert StepContractValidator.get_expected_state("REPORT_REMAINING_RECORD") == "PRESENT"

        assert StepContractValidator.get_expected_phase("DELETE_RECORD") == "REMEDIATION"
        assert StepContractValidator.get_expected_state("DELETE_RECORD") == "ABSENT"

        assert StepContractValidator.get_expected_phase("VERIFY_RECORD_ABSENT") == "VERIFICATION"
        assert StepContractValidator.get_expected_state("VERIFY_RECORD_ABSENT") == "ABSENT"

        assert StepContractValidator.get_expected_phase("NONEXISTENT_OP") is None
        assert StepContractValidator.get_expected_state("NONEXISTENT_OP") is None

    def test_canonical_operation_indices(self):
        """Verify the 1-based canonical index matching problem_statement.md table order."""
        # Findings
        assert OPERATION_CANONICAL_INDEX["REPORT_REMAINING_RECORD"] == 1
        assert OPERATION_CANONICAL_INDEX["REPORT_EXPOSED_PII"] == 2
        assert OPERATION_CANONICAL_INDEX["REPORT_ACTIVE_DATA_FLOW"] == 3
        assert OPERATION_CANONICAL_INDEX["REPORT_RESTORE_RISK"] == 4

        # Remediation
        assert OPERATION_CANONICAL_INDEX["DISABLE_DATA_FLOW"] == 1
        assert OPERATION_CANONICAL_INDEX["BLOCK_RESTORE"] == 2
        assert OPERATION_CANONICAL_INDEX["DELETE_RECORD"] == 3
        assert OPERATION_CANONICAL_INDEX["REDACT_RECORD"] == 4
        assert OPERATION_CANONICAL_INDEX["ANONYMIZE_RECORD"] == 5

        # Verification
        assert OPERATION_CANONICAL_INDEX["VERIFY_RECORD_ABSENT"] == 1
        assert OPERATION_CANONICAL_INDEX["VERIFY_RECORD_PRESENT"] == 2
        assert OPERATION_CANONICAL_INDEX["VERIFY_RECORD_REDACTED"] == 3
        assert OPERATION_CANONICAL_INDEX["VERIFY_RECORD_ANONYMIZED"] == 4
        assert OPERATION_CANONICAL_INDEX["VERIFY_DATA_FLOW_DISABLED"] == 5
        assert OPERATION_CANONICAL_INDEX["VERIFY_RESTORE_BLOCKED"] == 6

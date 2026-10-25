"""Phase 8 Chunk 8.6: Strict Operation, State, and Phase Contract Enforcement.

Defines the centralized, authoritative single source of truth for the complete
challenge step vocabulary, allowed (phase, operation, state) combinations, and
contract validation as specified in problem_statement.md (§ "Allowed Operations")
and AGENTS.md §6.4.

Vocabulary Summary:
- Phases (3): FINDING, REMEDIATION, VERIFICATION
- Operations (15):
    FINDING (4):
      - REPORT_REMAINING_RECORD -> PRESENT
      - REPORT_EXPOSED_PII -> PRESENT
      - REPORT_ACTIVE_DATA_FLOW -> ACTIVE
      - REPORT_RESTORE_RISK -> ACTIVE
    REMEDIATION (5):
      - DISABLE_DATA_FLOW -> DISABLED
      - BLOCK_RESTORE -> BLOCKED
      - DELETE_RECORD -> ABSENT
      - REDACT_RECORD -> REDACTED
      - ANONYMIZE_RECORD -> ANONYMIZED
    VERIFICATION (6):
      - VERIFY_RECORD_ABSENT -> ABSENT
      - VERIFY_RECORD_PRESENT -> PRESENT
      - VERIFY_RECORD_REDACTED -> REDACTED
      - VERIFY_RECORD_ANONYMIZED -> ANONYMIZED
      - VERIFY_DATA_FLOW_DISABLED -> DISABLED
      - VERIFY_RESTORE_BLOCKED -> BLOCKED
- States (7):
    PRESENT, ACTIVE, DISABLED, BLOCKED, ABSENT, REDACTED, ANONYMIZED
- Exactly 15 permitted (phase, operation, state) triples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Union


# =============================================================================
# 1. Authoritative Enumerations
# =============================================================================

class StepPhase(str, Enum):
    """The three official challenge step phases."""
    FINDING = "FINDING"
    REMEDIATION = "REMEDIATION"
    VERIFICATION = "VERIFICATION"


class StepOperation(str, Enum):
    """The 15 official challenge operations permitted across phases."""
    # Findings (4)
    REPORT_REMAINING_RECORD = "REPORT_REMAINING_RECORD"
    REPORT_EXPOSED_PII = "REPORT_EXPOSED_PII"
    REPORT_ACTIVE_DATA_FLOW = "REPORT_ACTIVE_DATA_FLOW"
    REPORT_RESTORE_RISK = "REPORT_RESTORE_RISK"

    # Remediation (5)
    DISABLE_DATA_FLOW = "DISABLE_DATA_FLOW"
    BLOCK_RESTORE = "BLOCK_RESTORE"
    DELETE_RECORD = "DELETE_RECORD"
    REDACT_RECORD = "REDACT_RECORD"
    ANONYMIZE_RECORD = "ANONYMIZE_RECORD"

    # Verification (6)
    VERIFY_RECORD_ABSENT = "VERIFY_RECORD_ABSENT"
    VERIFY_RECORD_PRESENT = "VERIFY_RECORD_PRESENT"
    VERIFY_RECORD_REDACTED = "VERIFY_RECORD_REDACTED"
    VERIFY_RECORD_ANONYMIZED = "VERIFY_RECORD_ANONYMIZED"
    VERIFY_DATA_FLOW_DISABLED = "VERIFY_DATA_FLOW_DISABLED"
    VERIFY_RESTORE_BLOCKED = "VERIFY_RESTORE_BLOCKED"


class StepState(str, Enum):
    """The seven official challenge states permitted across operations."""
    PRESENT = "PRESENT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"
    ABSENT = "ABSENT"
    REDACTED = "REDACTED"
    ANONYMIZED = "ANONYMIZED"


# =============================================================================
# 2. Authoritative Sets and Field Tuples
# =============================================================================

REQUIRED_STEP_FIELDS: tuple[str, ...] = (
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
)

PERMITTED_PHASES: frozenset[str] = frozenset(p.value for p in StepPhase)
PERMITTED_OPERATIONS: frozenset[str] = frozenset(o.value for o in StepOperation)
PERMITTED_STATES: frozenset[str] = frozenset(s.value for s in StepState)

# The authoritative list of exactly 15 permitted (phase, operation, state) combinations
PERMITTED_COMBINATIONS: frozenset[tuple[str, str, str]] = frozenset({
    # Phase: FINDING (4)
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),

    # Phase: REMEDIATION (5)
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),

    # Phase: VERIFICATION (6)
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
})


# =============================================================================
# 3. Canonical Mappings & Intra-Phase Operation Ordering
# =============================================================================

# Every operation uniquely maps to exactly one valid phase
OPERATION_TO_PHASE: dict[str, str] = {
    # Findings
    "REPORT_REMAINING_RECORD": "FINDING",
    "REPORT_EXPOSED_PII": "FINDING",
    "REPORT_ACTIVE_DATA_FLOW": "FINDING",
    "REPORT_RESTORE_RISK": "FINDING",
    # Remediation
    "DISABLE_DATA_FLOW": "REMEDIATION",
    "BLOCK_RESTORE": "REMEDIATION",
    "DELETE_RECORD": "REMEDIATION",
    "REDACT_RECORD": "REMEDIATION",
    "ANONYMIZE_RECORD": "REMEDIATION",
    # Verification
    "VERIFY_RECORD_ABSENT": "VERIFICATION",
    "VERIFY_RECORD_PRESENT": "VERIFICATION",
    "VERIFY_RECORD_REDACTED": "VERIFICATION",
    "VERIFY_RECORD_ANONYMIZED": "VERIFICATION",
    "VERIFY_DATA_FLOW_DISABLED": "VERIFICATION",
    "VERIFY_RESTORE_BLOCKED": "VERIFICATION",
}

# Every operation uniquely maps to exactly one valid state
OPERATION_TO_STATE: dict[str, str] = {
    # Findings
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    # Remediation
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    # Verification
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}

PHASE_TO_OPERATIONS: dict[str, tuple[str, ...]] = {
    "FINDING": (
        "REPORT_REMAINING_RECORD",
        "REPORT_EXPOSED_PII",
        "REPORT_ACTIVE_DATA_FLOW",
        "REPORT_RESTORE_RISK",
    ),
    "REMEDIATION": (
        "DISABLE_DATA_FLOW",
        "BLOCK_RESTORE",
        "DELETE_RECORD",
        "REDACT_RECORD",
        "ANONYMIZE_RECORD",
    ),
    "VERIFICATION": (
        "VERIFY_RECORD_ABSENT",
        "VERIFY_RECORD_PRESENT",
        "VERIFY_RECORD_REDACTED",
        "VERIFY_RECORD_ANONYMIZED",
        "VERIFY_DATA_FLOW_DISABLED",
        "VERIFY_RESTORE_BLOCKED",
    ),
}

# Canonical order within each phase as defined by problem_statement.md
OPERATION_CANONICAL_INDEX: dict[str, int] = {
    # Findings (1..4)
    "REPORT_REMAINING_RECORD": 1,
    "REPORT_EXPOSED_PII": 2,
    "REPORT_ACTIVE_DATA_FLOW": 3,
    "REPORT_RESTORE_RISK": 4,
    # Remediation (1..5)
    "DISABLE_DATA_FLOW": 1,
    "BLOCK_RESTORE": 2,
    "DELETE_RECORD": 3,
    "REDACT_RECORD": 4,
    "ANONYMIZE_RECORD": 5,
    # Verification (1..6)
    "VERIFY_RECORD_ABSENT": 1,
    "VERIFY_RECORD_PRESENT": 2,
    "VERIFY_RECORD_REDACTED": 3,
    "VERIFY_RECORD_ANONYMIZED": 4,
    "VERIFY_DATA_FLOW_DISABLED": 5,
    "VERIFY_RESTORE_BLOCKED": 6,
}


# =============================================================================
# 4. Diagnostic Exceptions
# =============================================================================

class StepValidationError(ValueError):
    """Base exception for all step contract and validation failures."""
    pass


class StepFieldMissingError(StepValidationError):
    """Raised when one or more required contract fields are missing."""
    pass


class StepFieldTypeError(StepValidationError, TypeError):
    """Raised when a step field is provided with an incorrect type."""
    pass


class StepNumberError(StepValidationError):
    """Raised when step_no is not a positive integer (e.g., bool, 0, negative)."""
    pass


class InvalidPhaseError(StepValidationError):
    """Raised when phase is not one of FINDING, REMEDIATION, VERIFICATION."""
    pass


class InvalidOperationError(StepValidationError):
    """Raised when an operation is not among the 15 challenge operations."""
    pass


class InvalidStateError(StepValidationError):
    """Raised when a state is not among the 7 challenge states."""
    pass


class InvalidOperationStateError(StepValidationError):
    """Raised when a (phase, operation, state) combination is not challenge-approved."""
    pass


class ExtraFieldsError(StepValidationError):
    """Raised when unrecognized fields are provided to the step factory."""
    pass


# =============================================================================
# 5. Validation Result
# =============================================================================

@dataclass(frozen=True)
class ContractValidationResult:
    """Immutable result of validating a step against the challenge contract."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def success(cls, warnings: Optional[list[str]] = None) -> ContractValidationResult:
        """Create a successful validation result."""
        return cls(is_valid=True, errors=[], warnings=warnings or [])

    @classmethod
    def failure(cls, errors: list[str], warnings: Optional[list[str]] = None) -> ContractValidationResult:
        """Create a failed validation result."""
        return cls(is_valid=False, errors=errors, warnings=warnings or [])


# =============================================================================
# 6. Centralized Step Contract Validator
# =============================================================================

class StepContractValidator:
    """
    Authoritative, centralized contract validation engine for the HackerRank Orchestrate
    challenge 'Ghost Data Still Exists'.

    Validates:
    - Exact phase vocabulary (FINDING, REMEDIATION, VERIFICATION).
    - Exact operation vocabulary (15 permitted operations).
    - Exact state vocabulary (7 permitted states).
    - Exact 15 (phase, operation, state) combinations.
    - Exact 7 contract fields with strict type checking.
    - Zero tolerance for case drift, whitespace padding, aliases, or extra fields.
    """

    @classmethod
    def is_valid_phase(cls, phase: Any) -> bool:
        """Return True iff phase is an exact string matching one of the 3 permitted phases."""
        if isinstance(phase, Enum):
            phase = phase.value
        return isinstance(phase, str) and phase in PERMITTED_PHASES

    @classmethod
    def is_valid_operation(cls, operation: Any) -> bool:
        """Return True iff operation is an exact string matching one of the 15 permitted operations."""
        if isinstance(operation, Enum):
            operation = operation.value
        return isinstance(operation, str) and operation in PERMITTED_OPERATIONS

    @classmethod
    def is_valid_state(cls, state: Any) -> bool:
        """Return True iff state is an exact string matching one of the 7 permitted states."""
        if isinstance(state, Enum):
            state = state.value
        return isinstance(state, str) and state in PERMITTED_STATES

    @classmethod
    def is_valid_combination(cls, phase: Any, operation: Any, state: Any) -> bool:
        """Return True iff (phase, operation, state) is one of the 15 permitted challenge triples."""
        if isinstance(phase, Enum):
            phase = phase.value
        if isinstance(operation, Enum):
            operation = operation.value
        if isinstance(state, Enum):
            state = state.value
        return (phase, operation, state) in PERMITTED_COMBINATIONS

    @classmethod
    def get_expected_phase(cls, operation: str) -> Optional[str]:
        """Return the unique challenge-mandated phase for the given operation, or None."""
        if isinstance(operation, Enum):
            operation = operation.value
        return OPERATION_TO_PHASE.get(operation)

    @classmethod
    def get_expected_state(cls, operation: str) -> Optional[str]:
        """Return the unique challenge-mandated state for the given operation, or None."""
        if isinstance(operation, Enum):
            operation = operation.value
        return OPERATION_TO_STATE.get(operation)

    @classmethod
    def validate_phase(cls, phase: Any) -> list[str]:
        """Validate phase and return deterministic error messages if invalid."""
        if isinstance(phase, Enum):
            phase = phase.value
        if not isinstance(phase, str):
            return [f"phase must be a string, got {type(phase).__name__}: {phase!r}"]
        if phase not in PERMITTED_PHASES:
            return [
                f"Invalid phase '{phase}'. Must be one of {sorted(PERMITTED_PHASES)}. "
                f"No aliases, lowercase, or whitespace variations permitted."
            ]
        return []

    @classmethod
    def validate_operation(cls, operation: Any) -> list[str]:
        """Validate operation and return deterministic error messages if invalid."""
        if isinstance(operation, Enum):
            operation = operation.value
        if not isinstance(operation, str):
            return [f"operation must be a string, got {type(operation).__name__}: {operation!r}"]
        if operation not in PERMITTED_OPERATIONS:
            return [
                f"Invalid operation '{operation}'. Must be one of {sorted(PERMITTED_OPERATIONS)}. "
                f"No unsupported or invented operations permitted."
            ]
        return []

    @classmethod
    def validate_state(cls, state: Any) -> list[str]:
        """Validate state and return deterministic error messages if invalid."""
        if isinstance(state, Enum):
            state = state.value
        if not isinstance(state, str):
            return [f"state must be a string, got {type(state).__name__}: {state!r}"]
        if state not in PERMITTED_STATES:
            return [
                f"Invalid state '{state}'. Must be one of {sorted(PERMITTED_STATES)}. "
                f"No unsupported states permitted."
            ]
        return []

    @classmethod
    def validate_semantic_combination(cls, phase: Any, operation: Any, state: Any) -> list[str]:
        """
        Validate the complete (phase, operation, state) tuple against the challenge contract.

        Rejects:
        - Invalid phase, operation, or state individually.
        - Correct operation placed in the wrong phase (e.g., REPORT_REMAINING_RECORD in REMEDIATION).
        - Correct operation coupled with an invalid state (e.g., DELETE_RECORD with PRESENT).
        - Correct phase and state with mismatched operation.
        """
        if isinstance(phase, Enum):
            phase = phase.value
        if isinstance(operation, Enum):
            operation = operation.value
        if isinstance(state, Enum):
            state = state.value

        errors: list[str] = []
        phase_errors = cls.validate_phase(phase)
        op_errors = cls.validate_operation(operation)
        state_errors = cls.validate_state(state)

        if phase_errors:
            errors.extend(phase_errors)
        if op_errors:
            errors.extend(op_errors)
        if state_errors:
            errors.extend(state_errors)

        if errors:
            # If any individual component is invalid, return the vocabulary errors first
            return errors

        # All three are valid vocabulary items; check if the triple is permitted
        if (phase, operation, state) not in PERMITTED_COMBINATIONS:
            expected_phase = OPERATION_TO_PHASE.get(operation)
            expected_state = OPERATION_TO_STATE.get(operation)

            if phase != expected_phase and state == expected_state:
                errors.append(
                    f"Phase mismatch for operation '{operation}': expected phase '{expected_phase}', "
                    f"got '{phase}'."
                )
            elif phase == expected_phase and state != expected_state:
                errors.append(
                    f"State mismatch for operation '{operation}': expected state '{expected_state}', "
                    f"got '{state}'."
                )
            else:
                errors.append(
                    f"Operation '{operation}' requires phase '{expected_phase}' and state '{expected_state}', "
                    f"got phase '{phase}' and state '{state}'."
                )

        return errors

    @classmethod
    def validate_step_fields(cls, data: Mapping[str, Any], allow_extra: bool = False) -> list[str]:
        """
        Validate all 7 contract fields in a raw dictionary or mapping.

        Returns a list of deterministic error messages.
        """
        if not isinstance(data, Mapping):
            return [f"Step data must be a Mapping/dict, got {type(data).__name__}"]

        errors: list[str] = []
        provided_keys = set(data.keys())
        required_keys = set(REQUIRED_STEP_FIELDS)

        # Check for extra keys
        extra_keys = provided_keys - required_keys
        if extra_keys and not allow_extra:
            errors.append(
                f"Unrecognized fields in step data: {sorted(extra_keys)}. "
                f"Only exactly {REQUIRED_STEP_FIELDS} are permitted."
            )

        # Check for missing keys
        missing_keys = required_keys - provided_keys
        if missing_keys:
            errors.append(f"Missing required step fields: {sorted(missing_keys)}")
            # Cannot proceed with deep field validation if keys are missing
            return errors

        # 1. step_no: positive int >= 1 (strictly reject bool)
        step_no = data.get("step_no")
        if isinstance(step_no, bool) or not isinstance(step_no, int):
            errors.append(
                f"step_no must be an int (got {type(step_no).__name__}: {step_no!r})"
            )
        elif step_no < 1:
            errors.append(f"step_no must be a positive integer >= 1, got {step_no}")

        # 2. system_id: non-empty str
        system_id = data.get("system_id")
        if not isinstance(system_id, str):
            errors.append(
                f"system_id must be a str (got {type(system_id).__name__}: {system_id!r})"
            )
        elif not system_id.strip():
            errors.append("system_id cannot be empty or whitespace")

        # 3. resource_id: non-empty str
        resource_id = data.get("resource_id")
        if not isinstance(resource_id, str):
            errors.append(
                f"resource_id must be a str (got {type(resource_id).__name__}: {resource_id!r})"
            )
        elif not resource_id.strip():
            errors.append("resource_id cannot be empty or whitespace")

        # 4. evidence_id: str
        evidence_id = data.get("evidence_id")
        if not isinstance(evidence_id, str):
            errors.append(
                f"evidence_id must be a str (got {type(evidence_id).__name__}: {evidence_id!r})"
            )

        # 5, 6, 7. phase, operation, state combination
        phase = data.get("phase")
        operation = data.get("operation")
        state = data.get("state")

        combination_errors = cls.validate_semantic_combination(phase, operation, state)
        if combination_errors:
            errors.extend(combination_errors)

        return errors

    @classmethod
    def validate_step(
        cls,
        step_or_dict: Any,
        allow_extra: bool = False,
    ) -> ContractValidationResult:
        """
        Validate an individual step object or raw dictionary against the challenge contract.

        Returns a ContractValidationResult with is_valid and deterministic error messages.
        """
        # If it's a Step instance (or has to_dict)
        if hasattr(step_or_dict, "to_dict"):
            d = step_or_dict.to_dict()
        elif isinstance(step_or_dict, Mapping):
            d = step_or_dict
        else:
            return ContractValidationResult.failure(
                [f"Input must be a Step instance or Mapping, got {type(step_or_dict).__name__}"]
            )

        errors = cls.validate_step_fields(d, allow_extra=allow_extra)
        if errors:
            return ContractValidationResult.failure(errors)
        return ContractValidationResult.success()

"""Phase 8 Chunk 8.2: Strongly Typed Step Representation and Validation.

Implements the authoritative internal model for individual challenge steps,
strict structural validation, and deterministic serialization to the exact
7-field contract schema specified in problem_statement.md and AGENTS.md §6.3.

Field Contract:
- step_no: positive int >= 1 (bool is strictly rejected)
- phase: "FINDING" | "REMEDIATION" | "VERIFICATION"
- system_id: non-empty str
- resource_id: non-empty str
- operation: one of the 15 permitted StepOperation values
- state: one of the 7 permitted StepState values
- evidence_id: str (empty string or admissible evidence citation)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

# Setup path imports safely without shadowed stdlib 'code' conflict
CURRENT_DIR = Path(__file__).resolve().parent
POLICY_DIR = CURRENT_DIR.parent / "policy"
if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    from .contract import (
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
except ImportError:
    from contract import (
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


@dataclass(frozen=True)
class Step:
    """
    Immutable representation of an atomic challenge step.

    Conforms strictly to the 7-field schema:
        step_no: positive int >= 1
        phase: FINDING | REMEDIATION | VERIFICATION
        system_id: non-empty string
        resource_id: non-empty string
        operation: one of the 15 permitted challenge operations
        state: one of the 7 permitted challenge states
        evidence_id: string (empty string or admissible citation)
    """
    step_no: int
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str = ""

    def __post_init__(self) -> None:
        """Perform strict structural validation upon instantiation."""
        # 1. step_no validation
        # Python bool is a subclass of int (isinstance(True, int) is True), so check explicitly
        if isinstance(self.step_no, bool) or not isinstance(self.step_no, int):
            raise StepFieldTypeError(
                f"step_no must be an int (got {type(self.step_no).__name__}: {self.step_no!r})"
            )
        if self.step_no < 1:
            raise StepNumberError(
                f"step_no must be a positive integer >= 1, got {self.step_no}"
            )

        # 2. phase validation
        if not isinstance(self.phase, str):
            raise StepFieldTypeError(
                f"phase must be a str (got {type(self.phase).__name__}: {self.phase!r})"
            )
        valid_phases = {p.value for p in StepPhase}
        if self.phase not in valid_phases:
            raise InvalidPhaseError(
                f"Invalid phase '{self.phase}'. Must be one of {sorted(valid_phases)}"
            )

        # 3. system_id validation
        if not isinstance(self.system_id, str):
            raise StepFieldTypeError(
                f"system_id must be a str (got {type(self.system_id).__name__}: {self.system_id!r})"
            )
        if not self.system_id.strip():
            raise StepValidationError("system_id cannot be empty or whitespace")

        # 4. resource_id validation
        if not isinstance(self.resource_id, str):
            raise StepFieldTypeError(
                f"resource_id must be a str (got {type(self.resource_id).__name__}: {self.resource_id!r})"
            )
        if not self.resource_id.strip():
            raise StepValidationError("resource_id cannot be empty or whitespace")

        # 5. operation validation
        if not isinstance(self.operation, str):
            raise StepFieldTypeError(
                f"operation must be a str (got {type(self.operation).__name__}: {self.operation!r})"
            )
        valid_operations = {o.value for o in StepOperation}
        if self.operation not in valid_operations:
            raise InvalidOperationStateError(
                f"Invalid operation '{self.operation}'. Must be one of {sorted(valid_operations)}"
            )

        # 6. state validation
        if not isinstance(self.state, str):
            raise StepFieldTypeError(
                f"state must be a str (got {type(self.state).__name__}: {self.state!r})"
            )
        valid_states = {s.value for s in StepState}
        if self.state not in valid_states:
            raise InvalidOperationStateError(
                f"Invalid state '{self.state}'. Must be one of {sorted(valid_states)}"
            )

        # 7. Triple combination check (phase, operation, state)
        triple = (self.phase, self.operation, self.state)
        if triple not in PERMITTED_COMBINATIONS:
            raise InvalidOperationStateError(
                f"Invalid challenge step combination: phase='{self.phase}', "
                f"operation='{self.operation}', state='{self.state}'. "
                f"Must be one of the 15 permitted combinations defined in AGENTS.md §6.4."
            )

        # 8. evidence_id validation
        if not isinstance(self.evidence_id, str):
            raise StepFieldTypeError(
                f"evidence_id must be a str (got {type(self.evidence_id).__name__}: {self.evidence_id!r})"
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize this step to a deterministic plain dictionary with exactly the 7 contract fields.

        Guarantees no extra fields, no debug metadata, and deterministic key order.
        """
        return {
            "step_no": self.step_no,
            "phase": self.phase,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Serialize step to a JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], allow_extra: bool = False) -> Step:
        """
        Instantiate and strictly validate a Step from a dictionary.

        Args:
            data: Mapping containing step fields.
            allow_extra: If False, raises ExtraFieldsError on any unknown keys.

        Raises:
            StepFieldTypeError: If data is not a dictionary.
            ExtraFieldsError: If unrecognized fields are present and allow_extra is False.
            StepFieldMissingError: If any required field is missing.
            StepValidationError: If field values fail structural validation.
        """
        if not isinstance(data, Mapping):
            raise StepFieldTypeError(
                f"Input data must be a dictionary/mapping, got {type(data).__name__}"
            )

        provided_keys = set(data.keys())
        required_keys = set(REQUIRED_STEP_FIELDS)

        # Check for extraneous keys
        extra_keys = provided_keys - required_keys
        if extra_keys and not allow_extra:
            raise ExtraFieldsError(
                f"Unrecognized fields in step data: {sorted(extra_keys)}. "
                f"Only exactly {REQUIRED_STEP_FIELDS} are permitted."
            )

        # Check for missing keys
        missing_keys = required_keys - provided_keys
        if missing_keys:
            raise StepFieldMissingError(
                f"Missing required step fields: {sorted(missing_keys)}"
            )

        return cls(
            step_no=data["step_no"],
            phase=str(data["phase"]) if isinstance(data["phase"], Enum) else data["phase"],
            system_id=data["system_id"],
            resource_id=data["resource_id"],
            operation=str(data["operation"]) if isinstance(data["operation"], Enum) else data["operation"],
            state=str(data["state"]) if isinstance(data["state"], Enum) else data["state"],
            evidence_id=data["evidence_id"],
        )

    @classmethod
    def from_json(cls, json_str: str, allow_extra: bool = False) -> Step:
        """Parse a JSON string and construct a validated Step."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise StepValidationError(f"Invalid JSON string: {exc}") from exc
        return cls.from_dict(data, allow_extra=allow_extra)

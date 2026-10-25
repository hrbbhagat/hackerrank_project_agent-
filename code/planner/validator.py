"""Phase 8 Chunk 8.2: Step Validator (Structural and Contextual Separation).

Separates:
1. Structural validation: Determines whether an individual step satisfies the 7-field
   schema, correct data types, and allowed (phase, operation, state) combinations.
2. Contextual validation: Determines whether a step is appropriate for the case's
   deletion_status, admissible evidence cutoff, and lifecycle sequencing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

# Setup path imports safely
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    from .contract import (
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
        REQUIRED_STEP_FIELDS,
        StepValidationError,
        StepContractValidator,
        ContractValidationResult,
    )
    from .models import Step
except ImportError:
    from contract import (
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
        REQUIRED_STEP_FIELDS,
        StepValidationError,
        StepContractValidator,
        ContractValidationResult,
    )
    from models import Step


@dataclass(frozen=True)
class ValidationResult:
    """Immutable result of validating a step or step sequence."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def success(cls, warnings: Optional[list[str]] = None) -> ValidationResult:
        """Create a successful validation result."""
        return cls(is_valid=True, errors=[], warnings=warnings or [])

    @classmethod
    def failure(cls, errors: list[str], warnings: Optional[list[str]] = None) -> ValidationResult:
        """Create a failed validation result."""
        return cls(is_valid=False, errors=errors, warnings=warnings or [])


@dataclass(frozen=True)
class ContextualValidationContext:
    """
    Contextual information for validating step appropriateness.

    Attributes:
        case_id: The request identifier.
        case_status: "COMPLETE" | "INCOMPLETE" | "NOT_APPLICABLE" | None.
        audit_at: ISO-8601 audit cutoff timestamp.
        admissible_evidence_ids: Set of admissible evidence, activity, and audit IDs.
    """
    case_id: Optional[str] = None
    case_status: Optional[str] = None
    audit_at: Optional[str] = None
    admissible_evidence_ids: Optional[set[str]] = None


def validate_step_structure(step_or_dict: Union[Step, Mapping[str, Any]]) -> ValidationResult:
    """
    Perform pure structural validation on a step object or raw dictionary.

    Returns ValidationResult rather than raising exceptions.
    """
    if isinstance(step_or_dict, Step):
        # A constructed Step instance has already passed __post_init__ validation
        return ValidationResult.success()

    try:
        Step.from_dict(step_or_dict, allow_extra=False)
        return ValidationResult.success()
    except StepValidationError as exc:
        return ValidationResult.failure([str(exc)])
    except Exception as exc:
        return ValidationResult.failure([f"Unexpected structural validation error: {exc}"])


def validate_step_context(step: Step, context: ContextualValidationContext) -> ValidationResult:
    """
    Perform contextual validation on an individual structurally valid Step.

    Enforces status-specific and evidence-admissibility rules:
    - NOT_APPLICABLE: No steps may exist.
    - COMPLETE: Phase must be VERIFICATION; evidence_id must be non-empty and admissible.
    - INCOMPLETE: FINDING must have non-empty evidence_id; REMEDIATION and VERIFICATION
      must have empty evidence_id.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if context.case_status is None:
        return ValidationResult.success()

    status = context.case_status.upper()
    s_step_no = getattr(step, "step_no", None) if hasattr(step, "step_no") else step.get("step_no")
    s_phase = getattr(step, "phase", None) if hasattr(step, "phase") else step.get("phase")
    s_operation = getattr(step, "operation", None) if hasattr(step, "operation") else step.get("operation")
    s_evidence_id = str(getattr(step, "evidence_id", "") if hasattr(step, "evidence_id") else step.get("evidence_id", ""))

    # Rule 1: NOT_APPLICABLE cases cannot have steps
    if status == "NOT_APPLICABLE":
        errors.append(
            f"Case {context.case_id or ''} is NOT_APPLICABLE; no steps are permitted "
            f"(steps_json must be []), but found step {s_step_no} ({s_operation})."
        )
        return ValidationResult.failure(errors)

    # Rule 2: COMPLETE cases
    if status == "COMPLETE":
        if s_phase != StepPhase.VERIFICATION.value:
            errors.append(
                f"Case {context.case_id or ''} is COMPLETE; only VERIFICATION steps are permitted, "
                f"but step {s_step_no} has phase '{s_phase}'."
            )
        if not s_evidence_id.strip():
            errors.append(
                f"Step {s_step_no} ({s_operation}) in COMPLETE case must cite non-empty "
                f"admissible evidence, but evidence_id is empty."
            )
        elif context.admissible_evidence_ids is not None:
            if s_evidence_id not in context.admissible_evidence_ids:
                errors.append(
                    f"Step {s_step_no} cites evidence_id '{s_evidence_id}' which is not in "
                    f"the admissible evidence set for case cutoff {context.audit_at}."
                )

    # Rule 3: INCOMPLETE cases
    elif status == "INCOMPLETE":
        if s_phase == StepPhase.FINDING.value:
            if not s_evidence_id.strip():
                errors.append(
                    f"FINDING step {s_step_no} ({s_operation}) in INCOMPLETE case must cite "
                    f"proving evidence_id, but evidence_id is empty."
                )
            elif context.admissible_evidence_ids is not None:
                if s_evidence_id not in context.admissible_evidence_ids:
                    errors.append(
                        f"FINDING step {s_step_no} cites evidence_id '{s_evidence_id}' which "
                        f"is not in the admissible evidence set for case cutoff {context.audit_at}."
                    )
        elif s_phase in (StepPhase.REMEDIATION.value, StepPhase.VERIFICATION.value):
            if s_evidence_id != "":
                errors.append(
                    f"{s_phase} step {s_step_no} in INCOMPLETE case represents future action "
                    f"and must have empty evidence_id (\"\"), but found '{s_evidence_id}'."
                )

    return ValidationResult.failure(errors, warnings) if errors else ValidationResult.success(warnings)


class StepValidator:
    """Unified validator providing both structural and sequence validation."""

    @staticmethod
    def validate_structure(step_or_dict: Union[Step, Mapping[str, Any]]) -> ValidationResult:
        """Validate step structure."""
        return validate_step_structure(step_or_dict)

    @staticmethod
    def validate_contract(step_or_dict: Any, allow_extra: bool = False) -> ValidationResult:
        """Validate step fields and semantic combination against authoritative challenge contract."""
        res = StepContractValidator.validate_step(step_or_dict, allow_extra=allow_extra)
        return ValidationResult(is_valid=res.is_valid, errors=res.errors, warnings=res.warnings)

    @staticmethod
    def validate_combination(phase: Any, operation: Any, state: Any) -> list[str]:
        """Validate the (phase, operation, state) tuple against challenge contract."""
        return StepContractValidator.validate_semantic_combination(phase, operation, state)

    @staticmethod
    def is_valid_combination(phase: Any, operation: Any, state: Any) -> bool:
        """Return True iff (phase, operation, state) is a permitted challenge combination."""
        return StepContractValidator.is_valid_combination(phase, operation, state)

    @staticmethod
    def is_valid_phase(phase: Any) -> bool:
        """Return True iff phase is a valid challenge phase."""
        return StepContractValidator.is_valid_phase(phase)

    @staticmethod
    def is_valid_operation(operation: Any) -> bool:
        """Return True iff operation is a valid challenge operation."""
        return StepContractValidator.is_valid_operation(operation)

    @staticmethod
    def is_valid_state(state: Any) -> bool:
        """Return True iff state is a valid challenge state."""
        return StepContractValidator.is_valid_state(state)

    @staticmethod
    def validate_context(step: Step, context: ContextualValidationContext) -> ValidationResult:
        """Validate single step context."""
        return validate_step_context(step, context)

    @staticmethod
    def validate_sequence(
        steps: Sequence[Union[Step, Mapping[str, Any]]],
        context: Optional[Union[ContextualValidationContext, str]] = None,
    ) -> ValidationResult:
        """
        Validate a full sequence of steps for:
        1. 1-indexed consecutive numbering (1, 2, 3, ...).
        2. Strict phase sequence (FINDING -> REMEDIATION -> VERIFICATION).
        3. Contextual validity of each individual step.
        """
        errors: list[str] = []
        warnings: list[str] = []

        if isinstance(context, str):
            ctx = ContextualValidationContext(case_status=context)
        else:
            ctx = context or ContextualValidationContext()

        # Handle NOT_APPLICABLE case
        if ctx.case_status and ctx.case_status.upper() == "NOT_APPLICABLE":
            if steps:
                errors.append(
                    f"Case {ctx.case_id or ''} is NOT_APPLICABLE; expected 0 steps, got {len(steps)}."
                )
            return ValidationResult.failure(errors) if errors else ValidationResult.success()

        # Handle COMPLETE case
        if ctx.case_status and ctx.case_status.upper() == "COMPLETE":
            if not steps:
                errors.append(
                    f"Case {ctx.case_id or ''} is COMPLETE; expected at least one evidence-backed VERIFICATION step, got 0."
                )
            for step in steps:
                s_phase = getattr(step, "phase", None) if hasattr(step, "phase") else step.get("phase")
                s_step_no = getattr(step, "step_no", None) if hasattr(step, "step_no") else step.get("step_no")
                if s_phase != StepPhase.VERIFICATION.value:
                    errors.append(
                        f"Case {ctx.case_id or ''} is COMPLETE; only VERIFICATION steps are permitted, "
                        f"but found phase '{s_phase}' at step {s_step_no}."
                    )

        # Handle INCOMPLETE case
        if ctx.case_status and ctx.case_status.upper() == "INCOMPLETE":
            if not steps:
                errors.append(
                    f"Case {ctx.case_id or ''} is INCOMPLETE; expected 3-phase lifecycle "
                    f"(FINDING -> REMEDIATION -> VERIFICATION), got 0 steps."
                )
            else:
                found_phases = {
                    (getattr(step, "phase", None) if hasattr(step, "phase") else step.get("phase"))
                    for step in steps
                }
                if StepPhase.FINDING.value not in found_phases:
                    errors.append(
                        f"Case {ctx.case_id or ''} is INCOMPLETE; missing required FINDING phase."
                    )
                if StepPhase.REMEDIATION.value not in found_phases:
                    errors.append(
                        f"Case {ctx.case_id or ''} is INCOMPLETE; missing required REMEDIATION phase."
                    )
                if StepPhase.VERIFICATION.value not in found_phases:
                    errors.append(
                        f"Case {ctx.case_id or ''} is INCOMPLETE; missing required VERIFICATION phase."
                    )

        phase_order = {
            StepPhase.FINDING.value: 1,
            StepPhase.REMEDIATION.value: 2,
            StepPhase.VERIFICATION.value: 3,
        }

        last_phase_val = 0

        for i, step in enumerate(steps):
            expected_step_no = i + 1
            s_step_no = getattr(step, "step_no", None) if hasattr(step, "step_no") else step.get("step_no")
            s_phase = getattr(step, "phase", None) if hasattr(step, "phase") else step.get("phase")
            if s_step_no != expected_step_no:
                errors.append(
                    f"Step numbering gap: expected step_no={expected_step_no} at index {i}, "
                    f"got step_no={s_step_no}."
                )

            current_phase_val = phase_order.get(s_phase, 99)
            if current_phase_val < last_phase_val:
                errors.append(
                    f"Phase ordering violation at step {s_step_no}: found phase '{s_phase}' "
                    f"after later phase in sequence. Phases must follow FINDING -> REMEDIATION -> VERIFICATION."
                )
            last_phase_val = max(last_phase_val, current_phase_val)

            # Validate individual step context
            ctx_res = validate_step_context(step, ctx)
            if not ctx_res.is_valid:
                errors.extend(ctx_res.errors)

        return ValidationResult.failure(errors, warnings) if errors else ValidationResult.success(warnings)

"""Phase 8: Step Planner and Output Generation Package.

Provides strongly typed, validated step models, structural and contextual
validation, deterministic step sequencing, and CSV/JSON output generation.
"""

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
    from .models import (
        Step,
    )
    from .validator import (
        StepValidator,
        ValidationResult,
        ContextualValidationContext,
        validate_step_structure,
        validate_step_context,
    )
    from .findings import (
        FindingCandidate,
        FindingsPlan,
        FindingStepGenerator,
        is_valid_evidence_id,
    )
    from .remediation import (
        RemediationCandidate,
        RemediationPlan,
        RemediationStepGenerator,
    )
    from .verification import (
        VerificationCandidate,
        VerificationPlan,
        VerificationStepGenerator,
    )
    from .sequencer import (
        CaseStepPlan,
        StepSequencer,
        get_step_sort_key,
        load_manifest_evidence_ids,
    )
    from .orchestrator import (
        StepPlannerOrchestrator,
        StepPlannerDryRunSummary,
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
    from models import (
        Step,
    )
    from validator import (
        StepValidator,
        ValidationResult,
        ContextualValidationContext,
        validate_step_structure,
        validate_step_context,
    )
    from findings import (
        FindingCandidate,
        FindingsPlan,
        FindingStepGenerator,
        is_valid_evidence_id,
    )
    from remediation import (
        RemediationCandidate,
        RemediationPlan,
        RemediationStepGenerator,
    )
    from verification import (
        VerificationCandidate,
        VerificationPlan,
        VerificationStepGenerator,
    )
    from sequencer import (
        CaseStepPlan,
        StepSequencer,
        get_step_sort_key,
        load_manifest_evidence_ids,
    )
    from orchestrator import (
        StepPlannerOrchestrator,
        StepPlannerDryRunSummary,
    )

__all__ = [
    "Step",
    "StepPhase",
    "StepOperation",
    "StepState",
    "REQUIRED_STEP_FIELDS",
    "PERMITTED_PHASES",
    "PERMITTED_OPERATIONS",
    "PERMITTED_STATES",
    "PERMITTED_COMBINATIONS",
    "OPERATION_TO_PHASE",
    "OPERATION_TO_STATE",
    "PHASE_TO_OPERATIONS",
    "OPERATION_CANONICAL_INDEX",
    "StepValidationError",
    "StepFieldMissingError",
    "StepFieldTypeError",
    "StepNumberError",
    "InvalidPhaseError",
    "InvalidOperationError",
    "InvalidStateError",
    "InvalidOperationStateError",
    "ExtraFieldsError",
    "ContractValidationResult",
    "StepContractValidator",
    "StepValidator",
    "ValidationResult",
    "ContextualValidationContext",
    "validate_step_structure",
    "validate_step_context",
    "FindingCandidate",
    "FindingsPlan",
    "FindingStepGenerator",
    "is_valid_evidence_id",
    "RemediationCandidate",
    "RemediationPlan",
    "RemediationStepGenerator",
    "VerificationCandidate",
    "VerificationPlan",
    "VerificationStepGenerator",
    "CaseStepPlan",
    "StepSequencer",
    "get_step_sort_key",
    "load_manifest_evidence_ids",
    "StepPlannerOrchestrator",
    "StepPlannerDryRunSummary",
]

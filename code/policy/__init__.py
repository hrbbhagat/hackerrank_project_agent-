"""Phase 6: Policy Engine package init.

Exports core loader and treatment engine models.
"""

try:
    from .loader import (
        PolicyRule,
        PolicyValidationResult,
        PolicyLoader,
        REQUIRED_COLUMNS,
        SUPPORTED_ACTIONS,
        KNOWN_CATEGORIES,
    )
    from .engine import (
        TreatmentEngine,
        ResourceTreatmentDecision,
        ComplianceResult,
        RequiredAction,
        TombstoneInspectionResult,
        inspect_tombstone_fields,
        CATEGORY_TO_DEFAULT_SYSTEM,
        PREFIX_TO_CATEGORY,
        PROHIBITED_DIRECT_IDENTIFIERS,
        PERMITTED_STABLE_REFERENCES,
    )
    from .mapper import (
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
        OperationSpec,
        PolicyOperationBundle,
        PolicyOperationMapper,
    )
    from .temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
        TemporalAuditValidation,
    )
    from .service import (
        PolicyEvaluationService,
        CasePolicyEvaluationResult,
    )
except ImportError:
    from loader import (
        PolicyRule,
        PolicyValidationResult,
        PolicyLoader,
        REQUIRED_COLUMNS,
        SUPPORTED_ACTIONS,
        KNOWN_CATEGORIES,
    )
    from engine import (
        TreatmentEngine,
        ResourceTreatmentDecision,
        ComplianceResult,
        RequiredAction,
        TombstoneInspectionResult,
        inspect_tombstone_fields,
        CATEGORY_TO_DEFAULT_SYSTEM,
        PREFIX_TO_CATEGORY,
        PROHIBITED_DIRECT_IDENTIFIERS,
        PERMITTED_STABLE_REFERENCES,
    )
    from mapper import (
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
        OperationSpec,
        PolicyOperationBundle,
        PolicyOperationMapper,
    )
    from temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
        TemporalAuditValidation,
    )
    from service import (
        PolicyEvaluationService,
        CasePolicyEvaluationResult,
    )

__all__ = [
    "PolicyRule",
    "PolicyValidationResult",
    "PolicyLoader",
    "REQUIRED_COLUMNS",
    "SUPPORTED_ACTIONS",
    "KNOWN_CATEGORIES",
    "TreatmentEngine",
    "ResourceTreatmentDecision",
    "ComplianceResult",
    "RequiredAction",
    "TombstoneInspectionResult",
    "inspect_tombstone_fields",
    "CATEGORY_TO_DEFAULT_SYSTEM",
    "PREFIX_TO_CATEGORY",
    "PROHIBITED_DIRECT_IDENTIFIERS",
    "PERMITTED_STABLE_REFERENCES",
    "StepPhase",
    "StepOperation",
    "StepState",
    "PERMITTED_COMBINATIONS",
    "OperationSpec",
    "PolicyOperationBundle",
    "PolicyOperationMapper",
    "parse_iso_timestamp",
    "is_temporally_admissible",
    "validate_evidence_temporal_integrity",
    "validate_evidence_id",
    "inspect_timeline_temporal_contract",
    "TemporalAuditValidation",
    "PolicyEvaluationService",
    "CasePolicyEvaluationResult",
]

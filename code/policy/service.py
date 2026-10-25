"""Phase 6.7: Policy Evaluation Service & Integration Boundary.

Integrates Phase 6 policy rules, deterministic treatment evaluation, and challenge
operation mapping with upstream Phase 3B identity resolution, Phase 4 evidence
provenance, and Phase 5 timeline reconstruction results.

Constraints:
- Accepts existing request and Phase 5 TimelineReconstructionResult.
- Emits ONLY resource-level decisions and mapped operation bundles.
- Does NOT assign case-level deletion statuses (COMPLETE/INCOMPLETE) (Phase 7).
- Does NOT serialize JSON arrays or assign final step numbers (Phase 8).
- Strictly preserves evidence references, rule IDs, and diagnostics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union, Any

# Local package imports
try:
    from .loader import PolicyLoader, PolicyRule
    from .engine import (
        TreatmentEngine,
        ResourceTreatmentDecision,
        ComplianceResult,
        RequiredAction,
    )
    from .mapper import (
        PolicyOperationMapper,
        PolicyOperationBundle,
        OperationSpec,
        StepPhase,
        StepOperation,
        StepState,
    )
    from .temporal import parse_iso_timestamp, validate_evidence_id
except ImportError:
    from loader import PolicyLoader, PolicyRule
    from engine import (
        TreatmentEngine,
        ResourceTreatmentDecision,
        ComplianceResult,
        RequiredAction,
    )
    from mapper import (
        PolicyOperationMapper,
        PolicyOperationBundle,
        OperationSpec,
        StepPhase,
        StepOperation,
        StepState,
    )
    from temporal import parse_iso_timestamp, validate_evidence_id


@dataclass(frozen=True)
class CasePolicyEvaluationResult:
    """
    Structured policy evaluation output for all resources associated with a request.
    
    Contains typed resource-level decisions, operation bundles, active risk
    findings, and all upstream/forensic diagnostics without declaring case-level
    verdicts.
    """
    case_id: str
    user_id: Optional[str]
    audit_at: Optional[datetime]
    is_non_deletion_request: bool
    resolution_status: str
    decisions: list[ResourceTreatmentDecision] = field(default_factory=list)
    decisions_by_resource: dict[str, ResourceTreatmentDecision] = field(default_factory=dict)
    operation_bundles: list[PolicyOperationBundle] = field(default_factory=list)
    operation_bundles_by_resource: dict[str, PolicyOperationBundle] = field(default_factory=dict)
    active_data_flows: list[dict] = field(default_factory=list)
    restore_risks: list[dict] = field(default_factory=list)
    replica_drift_findings: list[dict] = field(default_factory=list)
    upstream_errors: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


class PolicyEvaluationService:
    """
    Core integration boundary for Phase 6 policy evaluation.
    
    Consumes TimelineReconstructionResult from Phase 5 and executes
    deterministic policy evaluation and operation mapping across all resources.
    """

    def __init__(
        self,
        engine: Optional[TreatmentEngine] = None,
        mapper: Optional[PolicyOperationMapper] = None,
        policy_loader: Optional[PolicyLoader] = None,
    ):
        if engine is not None:
            self.engine = engine
        else:
            self.engine = TreatmentEngine(policy_loader or PolicyLoader())
        self.mapper = mapper or PolicyOperationMapper()

    def evaluate_timeline(
        self,
        request: dict,
        timeline_result: Any,
        context: Optional[dict] = None,
    ) -> CasePolicyEvaluationResult:
        """
        Evaluate all resources in a reconstructed timeline for a deletion request.
        
        Args:
            request: The raw deletion request dict (e.g. from deletion_requests.csv)
            timeline_result: TimelineReconstructionResult produced by Phase 5
            context: Additional contextual overrides or metadata (optional)
            
        Returns:
            CasePolicyEvaluationResult containing all resource decisions and bundles.
        """
        context = dict(context or {})
        diagnostics = []

        # Extract request and timeline metadata
        case_id = str(request.get("case_id") or getattr(timeline_result, "case_id", "")).strip()
        user_id = getattr(timeline_result, "user_id", None)
        
        audit_at_val = getattr(timeline_result, "audit_at", None)
        if audit_at_val is None and request.get("audit_at"):
            audit_at_val = parse_iso_timestamp(request.get("audit_at"))
        
        is_non_del = getattr(timeline_result, "is_non_deletion_request", False)
        resolution_status = getattr(timeline_result, "resolution_status", "RESOLVED")
        
        upstream_errors = list(getattr(timeline_result, "errors", []))
        contradictions = list(getattr(timeline_result, "contradictions", []))
        active_flows = list(getattr(timeline_result, "active_data_flows", []))
        restore_risks = list(getattr(timeline_result, "restore_risks", []))
        replica_drift_findings = list(getattr(timeline_result, "replica_drift_findings", []))

        resources = getattr(timeline_result, "resources", {})
        if not resources:
            diagnostics.append(f"No resources found or resolved in timeline for case {case_id}")

        decisions_by_resource: dict[str, ResourceTreatmentDecision] = {}
        bundles_by_resource: dict[str, PolicyOperationBundle] = {}

        # 1. Evaluate all resources reconstructed in timeline
        for rid, res_timeline in resources.items():
            res_context = dict(context)
            decision = self.engine.evaluate_timeline_resource(
                res_timeline,
                audit_at=audit_at_val,
                context=res_context,
            )
            bundle = self.mapper.map_decision(decision, context=res_context)

            decisions_by_resource[rid] = decision
            bundles_by_resource[rid] = bundle

        # 2. Reconcile standalone active data flows not already keyed in resources
        for flow in active_flows:
            flow_rid = flow.get("resource_id")
            if flow_rid and flow_rid not in decisions_by_resource:
                flow_sys = flow.get("system_id", "integration_service")
                flow_ev = flow.get("evidence_id", "")
                flow_context = dict(context)
                flow_context["is_active_flow"] = True

                flow_decision = self.engine.evaluate_resource(
                    resource_id=flow_rid,
                    observed_state="ACTIVE",
                    system_id=flow_sys,
                    data_category="DATA_FLOW",
                    evidence_id=flow_ev,
                    context=flow_context,
                )
                flow_bundle = self.mapper.map_decision(flow_decision, context=flow_context)

                decisions_by_resource[flow_rid] = flow_decision
                bundles_by_resource[flow_rid] = flow_bundle
                diagnostics.append(f"Surfaced standalone active data flow '{flow_rid}'")

        # 3. Reconcile standalone restore risks not already keyed in resources
        for risk in restore_risks:
            risk_rid = risk.get("resource_id")
            if risk_rid and risk_rid not in decisions_by_resource:
                risk_sys = risk.get("system_id", "backup_service")
                risk_ev = risk.get("evidence_id", "")
                risk_context = dict(context)
                risk_context["is_restore_risk"] = True

                risk_decision = self.engine.evaluate_resource(
                    resource_id=risk_rid,
                    observed_state="ACTIVE",
                    system_id=risk_sys,
                    data_category="BACKUP_ARCHIVE",
                    evidence_id=risk_ev,
                    context=risk_context,
                )
                risk_bundle = self.mapper.map_decision(risk_decision, context=risk_context)

                decisions_by_resource[risk_rid] = risk_decision
                bundles_by_resource[risk_rid] = risk_bundle
                diagnostics.append(f"Surfaced standalone restore risk '{risk_rid}'")

        # Deterministic sorting by resource_id
        sorted_resource_ids = sorted(decisions_by_resource.keys())
        decisions_list = [decisions_by_resource[rid] for rid in sorted_resource_ids]
        bundles_list = [bundles_by_resource[rid] for rid in sorted_resource_ids]

        # Calculate summary statistics
        compliant_count = sum(1 for d in decisions_list if d.compliance_result == ComplianceResult.COMPLIANT)
        non_compliant_count = sum(1 for d in decisions_list if d.compliance_result == ComplianceResult.NON_COMPLIANT)
        indeterminate_count = sum(1 for d in decisions_list if d.compliance_result in (ComplianceResult.INDETERMINATE, ComplianceResult.NOT_APPLICABLE))

        summary = {
            "total_resources": len(decisions_list),
            "compliant_count": compliant_count,
            "non_compliant_count": non_compliant_count,
            "indeterminate_count": indeterminate_count,
            "active_flows_count": len(active_flows),
            "restore_risks_count": len(restore_risks),
            "replica_drift_count": len(replica_drift_findings),
            "upstream_error_count": len(upstream_errors),
        }

        return CasePolicyEvaluationResult(
            case_id=case_id,
            user_id=user_id,
            audit_at=audit_at_val,
            is_non_deletion_request=is_non_del,
            resolution_status=resolution_status,
            decisions=decisions_list,
            decisions_by_resource=decisions_by_resource,
            operation_bundles=bundles_list,
            operation_bundles_by_resource=bundles_by_resource,
            active_data_flows=active_flows,
            restore_risks=restore_risks,
            replica_drift_findings=replica_drift_findings,
            upstream_errors=upstream_errors,
            contradictions=contradictions,
            diagnostics=diagnostics,
            summary=summary,
        )

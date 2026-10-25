"""Phase 7 Chunk 7.6: Central Case Status Resolver.

Determines the authoritative case-level deletion status (COMPLETE, INCOMPLETE,
or NOT_APPLICABLE) by deterministically synthesizing:
1. Request applicability and intent (Chunk 7.2)
2. Resource compliance aggregation (Chunk 7.3)
3. Remaining data and residual violations assessment (Chunk 7.4)
4. Recreation, synchronization, and restore-risk assessment (Chunk 7.5)

Adheres strictly to the challenge specification and decision table:
- NOT_APPLICABLE depends on established request applicability, not on missing evidence.
- COMPLETE requires sufficient admissible evidence that all applicable deletion obligations
  are satisfied and no applicable unresolved violation or active risk remains.
- INCOMPLETE is assigned when any obligation is unmet, residual PII/record remains,
  active flow or restore risk exists, or evidence is missing/contradictory/indeterminate.
  Never silently equates uncertainty with success.
- Purely deterministic; no LLM decision-making.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

# Ensure parent and policy directories are on sys.path without standard library 'code' conflict
CURRENT_DIR = Path(__file__).resolve().parent
POLICY_DIR = CURRENT_DIR.parent / "policy"
if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    from service import CasePolicyEvaluationResult
except ImportError:
    from .service import CasePolicyEvaluationResult

from .models import (
    CaseStatusResult,
    DeletionStatus,
    RequestApplicabilityResult,
    RequestIntentCategory,
    ResourceAggregationResult,
    RemainingDataAssessmentResult,
    RecreationRiskAssessmentResult,
)
from .applicability import RequestApplicabilityEvaluator
from .aggregator import ResourceComplianceAggregator
from .remaining_data import RemainingDataAssessor
from .risk_assessment import RecreationRiskAssessor
from .explanation import DecisionExplanationBuilder


class CaseStatusResolver:
    """
    Central deterministic case status resolver.
    
    Synthesizes applicability, compliance aggregation, residual violations,
    and restoration risks into the exact challenge-permitted case status:
    COMPLETE, INCOMPLETE, or NOT_APPLICABLE.
    """

    def __init__(
        self,
        applicability_evaluator: Optional[RequestApplicabilityEvaluator] = None,
        aggregator: Optional[ResourceComplianceAggregator] = None,
        remaining_data_assessor: Optional[RemainingDataAssessor] = None,
        risk_assessor: Optional[RecreationRiskAssessor] = None,
        explanation_builder: Optional[DecisionExplanationBuilder] = None,
    ):
        self.applicability_evaluator = applicability_evaluator or RequestApplicabilityEvaluator()
        self.aggregator = aggregator or ResourceComplianceAggregator()
        self.remaining_data_assessor = remaining_data_assessor or RemainingDataAssessor()
        self.risk_assessor = risk_assessor or RecreationRiskAssessor()
        self.explanation_builder = explanation_builder or DecisionExplanationBuilder()

    def _make_result(
        self,
        case_id: str,
        deletion_status: DeletionStatus,
        reason: str,
        is_non_deletion_request: bool,
        resolution_status: str,
        applicability: RequestApplicabilityResult,
        resource_aggregation: ResourceAggregationResult,
        remaining_data: RemainingDataAssessmentResult,
        risk_assessment: RecreationRiskAssessmentResult,
        diagnostics: list[str],
        policy_result: Optional[CasePolicyEvaluationResult] = None,
        timeline_result: Optional[Any] = None,
    ) -> CaseStatusResult:
        explanation = self.explanation_builder.build_explanation(
            case_id=case_id,
            deletion_status=deletion_status,
            summary_reason=reason,
            resolution_status=resolution_status,
            applicability=applicability,
            resource_aggregation=resource_aggregation,
            remaining_data=remaining_data,
            risk_assessment=risk_assessment,
            policy_result=policy_result,
            timeline_result=timeline_result,
            cutoff_iso=applicability.audit_at,
        )
        return CaseStatusResult(
            case_id=case_id,
            deletion_status=deletion_status,
            reason=reason,
            is_non_deletion_request=is_non_deletion_request,
            resolution_status=resolution_status,
            applicability=applicability,
            resource_aggregation=resource_aggregation,
            remaining_data=remaining_data,
            risk_assessment=risk_assessment,
            diagnostics=diagnostics,
            explanation=explanation,
        )

    def resolve_case_status(
        self,
        request: dict[str, Any],
        policy_result: CasePolicyEvaluationResult,
        timeline_result: Optional[Any] = None,
        applicability_result: Optional[RequestApplicabilityResult] = None,
        aggregation_result: Optional[ResourceAggregationResult] = None,
        remaining_data_result: Optional[RemainingDataAssessmentResult] = None,
        risk_result: Optional[RecreationRiskAssessmentResult] = None,
    ) -> CaseStatusResult:
        """
        Deterministically resolve the case-level deletion status.
        
        Args:
            request: The raw deletion request record.
            policy_result: CasePolicyEvaluationResult from Phase 6.
            timeline_result: Optional TimelineReconstructionResult from Phase 5.
            applicability_result: Optional pre-evaluated applicability result.
            aggregation_result: Optional pre-evaluated aggregation result.
            remaining_data_result: Optional pre-evaluated remaining data result.
            risk_result: Optional pre-evaluated risk assessment result.
            
        Returns:
            CaseStatusResult with authoritative DeletionStatus and structured reasoning.
        """
        case_id = str(request.get("case_id") or policy_result.case_id or "").strip()
        diagnostics: list[str] = list(policy_result.diagnostics)

        # 1. Evaluate or reuse Request Applicability (Chunk 7.2)
        if applicability_result is None:
            applicability_result = self.applicability_evaluator.evaluate_request(request)
        for diag in applicability_result.diagnostics:
            if diag not in diagnostics:
                diagnostics.append(diag)

        # 2. Evaluate or reuse Resource Compliance Aggregation (Chunk 7.3)
        if aggregation_result is None:
            aggregation_result = self.aggregator.aggregate_compliance(policy_result, timeline_result)
        for diag in aggregation_result.diagnostics:
            if diag not in diagnostics:
                diagnostics.append(diag)

        # 3. Evaluate or reuse Remaining Data Assessment (Chunk 7.4)
        if remaining_data_result is None:
            remaining_data_result = self.remaining_data_assessor.assess_remaining_data(policy_result, timeline_result)
        for diag in remaining_data_result.diagnostics:
            if diag not in diagnostics:
                diagnostics.append(diag)

        # 4. Evaluate or reuse Recreation & Restore Risk Assessment (Chunk 7.5)
        if risk_result is None:
            risk_result = self.risk_assessor.assess_risks(policy_result, timeline_result)
        for diag in risk_result.diagnostics:
            if diag not in diagnostics:
                diagnostics.append(diag)

        # ---------------------------------------------------------------------
        # DECISION TABLE PRECEDENCE EVALUATION
        # ---------------------------------------------------------------------

        # PRIORITY 1: Request Applicability / Non-Deletion Intent
        # Rule: NOT_APPLICABLE depends strictly on established request intent,
        # never on missing evidence or absence of observed violations.
        if applicability_result.is_not_applicable or policy_result.is_non_deletion_request:
            reason = (
                f"Request does not authorize deletion: {applicability_result.reason}"
                if applicability_result.is_not_applicable
                else "Upstream policy evaluation marked request as non-deletion."
            )
            return self._make_result(
                case_id=case_id,
                deletion_status=DeletionStatus.NOT_APPLICABLE,
                reason=reason,
                is_non_deletion_request=True,
                resolution_status="NOT_APPLICABLE",
                applicability=applicability_result,
                resource_aggregation=aggregation_result,
                remaining_data=remaining_data_result,
                risk_assessment=risk_result,
                diagnostics=diagnostics,
                policy_result=policy_result,
                timeline_result=timeline_result,
            )

        # PRIORITY 2: Residual Personal Data Violations at Audit Cutoff
        # Rule: Any prohibited record remaining, unredacted direct PII, or replica drift
        # establishes an unmet deletion obligation -> INCOMPLETE.
        if remaining_data_result.has_remaining_data or aggregation_result.has_replica_drift:
            violation_details = []
            if remaining_data_result.remaining_record_count > 0:
                violation_details.append(
                    f"{remaining_data_result.remaining_record_count} prohibited record(s) remain present"
                )
            if remaining_data_result.exposed_pii_count > 0:
                violation_details.append(
                    f"{remaining_data_result.exposed_pii_count} record(s) contain exposed direct PII"
                )
            if remaining_data_result.replica_drift_count > 0 or aggregation_result.has_replica_drift:
                count = remaining_data_result.replica_drift_count or len(policy_result.replica_drift_findings)
                violation_details.append(
                    f"{count} replica drift finding(s) retain unpurged copies"
                )

            reason = (
                f"Deletion is INCOMPLETE: Residual personal data remains present at audit cutoff ({'; '.join(violation_details)})."
            )
            return self._make_result(
                case_id=case_id,
                deletion_status=DeletionStatus.INCOMPLETE,
                reason=reason,
                is_non_deletion_request=False,
                resolution_status="VIOLATION_PRESENT",
                applicability=applicability_result,
                resource_aggregation=aggregation_result,
                remaining_data=remaining_data_result,
                risk_assessment=risk_result,
                diagnostics=diagnostics,
                policy_result=policy_result,
                timeline_result=timeline_result,
            )

        # PRIORITY 3: Active Data Flows, Recreation, or Backup Restoration Risks
        # Rule: An active sync/pipeline or unblocked restore path threatens data privacy at cutoff -> INCOMPLETE.
        if risk_result.has_active_risks:
            risk_details = []
            if risk_result.active_flows_count > 0:
                risk_details.append(f"{risk_result.active_flows_count} active data flow(s) can copy or recreate data")
            if risk_result.restore_risks_count > 0:
                risk_details.append(f"{risk_result.restore_risks_count} unblocked backup archive(s) present restore risk")
            if risk_result.recreation_count > 0:
                risk_details.append(f"{risk_result.recreation_count} confirmed recreation event(s) occurred before cutoff")

            reason = (
                f"Deletion is INCOMPLETE: Active infrastructure risks present at audit cutoff ({'; '.join(risk_details)})."
            )
            return self._make_result(
                case_id=case_id,
                deletion_status=DeletionStatus.INCOMPLETE,
                reason=reason,
                is_non_deletion_request=False,
                resolution_status="ACTIVE_RISK_PRESENT",
                applicability=applicability_result,
                resource_aggregation=aggregation_result,
                remaining_data=remaining_data_result,
                risk_assessment=risk_result,
                diagnostics=diagnostics,
                policy_result=policy_result,
                timeline_result=timeline_result,
            )

        # Other Resource Compliance Violations
        if aggregation_result.has_violations:
            reason = (
                f"Deletion is INCOMPLETE: {len(aggregation_result.non_compliant_resources)} resource(s) failed policy compliance."
            )
            return self._make_result(
                case_id=case_id,
                deletion_status=DeletionStatus.INCOMPLETE,
                reason=reason,
                is_non_deletion_request=False,
                resolution_status="VIOLATION_PRESENT",
                applicability=applicability_result,
                resource_aggregation=aggregation_result,
                remaining_data=remaining_data_result,
                risk_assessment=risk_result,
                diagnostics=diagnostics,
                policy_result=policy_result,
                timeline_result=timeline_result,
            )

        # PRIORITY 4: Evidence Gaps, Indeterminate States, or Contradictions
        # Rule: Uncertainty, missing evidence, or contradictory records cannot be equated with success -> INCOMPLETE.
        has_evidence_gaps = (
            aggregation_result.has_indeterminate
            or len(aggregation_result.contradictions) > 0
            or len(remaining_data_result.unverified_resources) > 0
            or policy_result.resolution_status in ("AMBIGUOUS", "UNRESOLVED")
            or len(policy_result.upstream_errors) > 0
        )
        if has_evidence_gaps:
            gap_reasons = []
            if aggregation_result.has_indeterminate:
                gap_reasons.append(
                    f"{len(aggregation_result.indeterminate_resources)} resource(s) lack conclusive compliance evidence"
                )
            if aggregation_result.contradictions:
                gap_reasons.append(
                    f"{len(aggregation_result.contradictions)} contradictory evidence observation(s)"
                )
            if remaining_data_result.unverified_resources:
                gap_reasons.append(
                    f"{len(remaining_data_result.unverified_resources)} unverified resource claim(s)"
                )
            if policy_result.resolution_status in ("AMBIGUOUS", "UNRESOLVED"):
                gap_reasons.append(f"upstream resolution status is {policy_result.resolution_status}")
            if policy_result.upstream_errors:
                gap_reasons.append(f"{len(policy_result.upstream_errors)} upstream error(s)")

            reason = (
                f"Deletion is INCOMPLETE: Insufficient or contradictory evidence prevents proving required state ({'; '.join(gap_reasons)}). "
                "Forensic standard does not equate uncertainty with compliance."
            )
            return self._make_result(
                case_id=case_id,
                deletion_status=DeletionStatus.INCOMPLETE,
                reason=reason,
                is_non_deletion_request=False,
                resolution_status="INDETERMINATE_EVIDENCE",
                applicability=applicability_result,
                resource_aggregation=aggregation_result,
                remaining_data=remaining_data_result,
                risk_assessment=risk_result,
                diagnostics=diagnostics,
                policy_result=policy_result,
                timeline_result=timeline_result,
            )

        # PRIORITY 5: Empty Resource Baseline
        # Rule: If zero resources were found or evaluated, deletion cannot be verified complete.
        if aggregation_result.total_resources == 0:
            reason = (
                "Deletion is INCOMPLETE: Zero resources were identified or evaluated for this subject identity. "
                "Evidence-backed verification requires proof of compliant resource state."
            )
            return self._make_result(
                case_id=case_id,
                deletion_status=DeletionStatus.INCOMPLETE,
                reason=reason,
                is_non_deletion_request=False,
                resolution_status="NO_RESOURCES_FOUND",
                applicability=applicability_result,
                resource_aggregation=aggregation_result,
                remaining_data=remaining_data_result,
                risk_assessment=risk_result,
                diagnostics=diagnostics,
                policy_result=policy_result,
                timeline_result=timeline_result,
            )

        # PRIORITY 6: Conjunctive Compliance
        # Rule: All obligations satisfied, all resources verified, legitimate retentions compliant,
        # and zero active risks or contradictions remain.
        if (
            aggregation_result.is_all_compliant
            and not remaining_data_result.has_remaining_data
            and not risk_result.has_active_risks
            and not aggregation_result.has_indeterminate
        ):
            retained_note = ""
            if aggregation_result.has_retained_data:
                retained_note = f" (including {len(aggregation_result.retained_resources)} legitimately retained / tombstoned resource(s))"

            reason = (
                f"Deletion is COMPLETE: All {aggregation_result.total_resources} resource(s) verified compliant{retained_note}. "
                "No prohibited records, exposed direct PII, active data flows, or unblocked restore risks exist at audit cutoff."
            )
            return self._make_result(
                case_id=case_id,
                deletion_status=DeletionStatus.COMPLETE,
                reason=reason,
                is_non_deletion_request=False,
                resolution_status="VERIFIED_COMPLETE",
                applicability=applicability_result,
                resource_aggregation=aggregation_result,
                remaining_data=remaining_data_result,
                risk_assessment=risk_result,
                diagnostics=diagnostics,
                policy_result=policy_result,
                timeline_result=timeline_result,
            )

        # PRIORITY 7: Fallback Safety Net
        # Deterministic default adhering to the forensic standard: never assume completeness.
        return self._make_result(
            case_id=case_id,
            deletion_status=DeletionStatus.INCOMPLETE,
            reason="Deletion is INCOMPLETE: Unresolved evaluation state does not satisfy all criteria for COMPLETE status.",
            is_non_deletion_request=False,
            resolution_status="UNRESOLVED_SAFETY_FALLBACK",
            applicability=applicability_result,
            resource_aggregation=aggregation_result,
            remaining_data=remaining_data_result,
            risk_assessment=risk_result,
            diagnostics=diagnostics,
            policy_result=policy_result,
            timeline_result=timeline_result,
        )

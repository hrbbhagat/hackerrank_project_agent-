"""Phase 7 Chunk 7.7: Decision Explanations and Evidence Traceability.

Provides structured, auditable explanations for case-level deletion verdicts.
Preserves:
1. Exact request applicability and intent grounding.
2. Disambiguation between direct observations, policy-derived conclusions, and unresolved uncertainties.
3. Strict cutoff adherence: post-cutoff evidence is cataloged as excluded and never cited as proof of earlier state.
4. Contradictory evidence preservation instead of hiding behind a single summary.
5. Traceability of every decisive finding to authentic participant-visible evidence.
6. Deterministic ordering and stable serialization.
7. PII sanitization to avoid leaking raw personal data in logs and audit summaries.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Optional

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
    ContradictionTrace,
    DecisionExplanation,
    DeletionStatus,
    EvidenceTrace,
    FindingExplanation,
    RecreationRiskAssessmentResult,
    RemainingDataAssessmentResult,
    RequestApplicabilityResult,
    ResourceAggregationResult,
)


def sanitize_pii(text: str) -> str:
    """
    Mask email local-parts and sensitive direct identifiers in audit text.
    
    Example:
        'user.name@example.com' -> 'u***@example.com'
    """
    if not text:
        return ""
    # Mask email addresses
    def _mask_email(match: re.Match) -> str:
        local, domain = match.group(1), match.group(2)
        if len(local) <= 1:
            masked_local = "*"
        else:
            masked_local = local[0] + "***"
        return f"{masked_local}@{domain}"

    email_pattern = re.compile(r"\b([a-zA-Z0-9_.+-]+)@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b")
    sanitized = email_pattern.sub(_mask_email, text)
    return sanitized


class DecisionExplanationBuilder:
    """
    Constructs comprehensive, structured, and auditable explanations for case decisions.
    """

    def build_explanation(
        self,
        case_id: str,
        deletion_status: DeletionStatus,
        summary_reason: str,
        resolution_status: str,
        applicability: RequestApplicabilityResult,
        resource_aggregation: ResourceAggregationResult,
        remaining_data: RemainingDataAssessmentResult,
        risk_assessment: RecreationRiskAssessmentResult,
        policy_result: Optional[CasePolicyEvaluationResult] = None,
        timeline_result: Optional[Any] = None,
        cutoff_iso: Optional[str] = None,
    ) -> DecisionExplanation:
        """
        Build an immutable, structured DecisionExplanation.
        """
        # 1. Determine primary deciding factor
        primary_deciding_factor = self._determine_primary_factor(
            deletion_status=deletion_status,
            resolution_status=resolution_status,
            remaining_data=remaining_data,
            risk_assessment=risk_assessment,
            resource_aggregation=resource_aggregation,
        )

        # 2. Extract Applicability Summary
        applicability_summary = {
            "case_id": applicability.case_id,
            "is_applicable": applicability.is_applicable,
            "intent_category": applicability.intent_category.value if hasattr(applicability.intent_category, "value") else str(applicability.intent_category),
            "reason": sanitize_pii(applicability.reason),
            "detected_patterns": list(applicability.detected_patterns),
            "reported_status_claim": applicability.reported_status or "NONE",
        }

        # 3. Collect Direct Evidence Observations
        direct_observations = self._collect_direct_observations(
            resource_aggregation=resource_aggregation,
            policy_result=policy_result,
        )

        # 4. Collect Policy-Derived Conclusions
        policy_conclusions = self._collect_policy_conclusions(
            remaining_data=remaining_data,
            risk_assessment=risk_assessment,
            resource_aggregation=resource_aggregation,
            policy_result=policy_result,
        )

        # 5. Collect Unresolved Uncertainties & Contradictions
        unresolved_uncertainties = self._collect_unresolved_uncertainties(
            resource_aggregation=resource_aggregation,
            remaining_data=remaining_data,
            policy_result=policy_result,
        )

        # 6. Collect Excluded Post-Cutoff Items
        excluded_post_cutoff_items = self._collect_post_cutoff_exclusions(
            risk_assessment=risk_assessment,
            timeline_result=timeline_result,
        )

        # 7. Collect and deduplicate valid evidence citations
        evidence_citations = self._compile_evidence_citations(
            direct_observations=direct_observations,
            policy_conclusions=policy_conclusions,
        )

        # 8. Sanitize diagnostics
        all_diagnostics = list(resource_aggregation.diagnostics)
        for diag in remaining_data.diagnostics + risk_assessment.diagnostics:
            if diag not in all_diagnostics:
                all_diagnostics.append(diag)
        sanitized_diagnostics = [sanitize_pii(d) for d in all_diagnostics]

        return DecisionExplanation(
            case_id=case_id,
            deletion_status=deletion_status,
            status_value=deletion_status.value,
            summary_reason=sanitize_pii(summary_reason),
            primary_deciding_factor=primary_deciding_factor,
            cutoff_iso=cutoff_iso or applicability.audit_at,
            applicability_summary=applicability_summary,
            direct_observations=direct_observations,
            policy_conclusions=policy_conclusions,
            unresolved_uncertainties=unresolved_uncertainties,
            excluded_post_cutoff_items=excluded_post_cutoff_items,
            evidence_citations=evidence_citations,
            sanitized_diagnostics=sanitized_diagnostics,
        )

    def _determine_primary_factor(
        self,
        deletion_status: DeletionStatus,
        resolution_status: str,
        remaining_data: RemainingDataAssessmentResult,
        risk_assessment: RecreationRiskAssessmentResult,
        resource_aggregation: ResourceAggregationResult,
    ) -> str:
        if deletion_status == DeletionStatus.NOT_APPLICABLE:
            return "REQUEST_NON_DELETION_INTENT"

        if resolution_status == "VIOLATION_PRESENT":
            if (remaining_data.replica_drift_count > 0 or resource_aggregation.has_replica_drift) and (
                remaining_data.remaining_record_count == remaining_data.replica_drift_count
                and remaining_data.exposed_pii_count == 0
            ):
                return "REPLICA_DRIFT_UNPURGED"
            if remaining_data.remaining_record_count > 0:
                return "RESIDUAL_PROHIBITED_RECORD"
            if remaining_data.exposed_pii_count > 0:
                return "EXPOSED_DIRECT_PII"
            if remaining_data.replica_drift_count > 0 or resource_aggregation.has_replica_drift:
                return "REPLICA_DRIFT_UNPURGED"
            return "POLICY_COMPLIANCE_VIOLATION"

        if resolution_status == "ACTIVE_RISK_PRESENT":
            if risk_assessment.active_flows_count > 0:
                return "ACTIVE_DATA_FLOW_RISK"
            if risk_assessment.restore_risks_count > 0:
                return "UNBLOCKED_RESTORE_RISK"
            if risk_assessment.recreation_count > 0:
                return "CONFIRMED_RECREATION_EVENT"
            return "INFRASTRUCTURE_RECREATION_RISK"

        if resolution_status == "INDETERMINATE_EVIDENCE":
            if resource_aggregation.contradictions:
                return "CONTRADICTORY_EVIDENCE_CONFLICT"
            return "INSUFFICIENT_VERIFICATION_EVIDENCE"

        if resolution_status == "NO_RESOURCES_FOUND":
            return "ZERO_RESOURCES_IDENTIFIED"

        if deletion_status == DeletionStatus.COMPLETE:
            if resource_aggregation.has_retained_data:
                return "ALL_OBLIGATIONS_SATISFIED_WITH_COMPLIANT_RETENTION"
            return "ALL_OBLIGATIONS_VERIFIED_COMPLIANT"

        return "UNRESOLVED_SAFETY_FALLBACK"

    def _collect_direct_observations(
        self,
        resource_aggregation: ResourceAggregationResult,
        policy_result: Optional[CasePolicyEvaluationResult],
    ) -> list[EvidenceTrace]:
        observations: list[EvidenceTrace] = []
        seen: set[tuple[str, str]] = set()

        if policy_result and policy_result.decisions:
            for dec in policy_result.decisions:
                ev_id = str(dec.evidence_id or "").strip()
                if not ev_id:
                    continue
                key = (dec.resource_id, ev_id)
                if key in seen:
                    continue
                seen.add(key)

                # Determine evidence role
                if dec.compliance_result.value == "NON_COMPLIANT":
                    role = "VIOLATION_FINDING"
                elif dec.observed_state == "ACTIVE":
                    role = "RISK_INDICATOR"
                elif dec.compliance_result.value == "COMPLIANT":
                    role = "VERIFICATION_PROOF"
                else:
                    role = "DIRECT_OBSERVATION"

                observations.append(
                    EvidenceTrace(
                        evidence_id=ev_id,
                        resource_id=dec.resource_id,
                        system_id=dec.system_id,
                        data_category=dec.data_category,
                        observed_state=dec.observed_state,
                        evidence_role=role,
                        admissible_at_cutoff=True,
                        timestamp=None,
                        description=sanitize_pii(dec.reason),
                    )
                )

        # Sort deterministically
        observations.sort(key=lambda o: (o.system_id, o.resource_id, o.evidence_id))
        return observations

    def _collect_policy_conclusions(
        self,
        remaining_data: RemainingDataAssessmentResult,
        risk_assessment: RecreationRiskAssessmentResult,
        resource_aggregation: ResourceAggregationResult,
        policy_result: Optional[CasePolicyEvaluationResult],
    ) -> list[FindingExplanation]:
        conclusions: list[FindingExplanation] = []

        # 1. Residual personal data findings
        for f in remaining_data.findings:
            details = [sanitize_pii(d) for d in f.diagnostics]
            if f.exposed_fields:
                details.append(f"Exposed fields: {', '.join(f.exposed_fields)}")
            conclusions.append(
                FindingExplanation(
                    finding_type=f.finding_type,
                    resource_id=f.resource_id,
                    system_id=f.system_id,
                    data_category=f.data_category,
                    rule_id=f.rule_id,
                    nature="POLICY_DERIVED_CONCLUSION",
                    evidence_id=f.evidence_id,
                    summary=sanitize_pii(f.violation_reason),
                    details=details,
                )
            )

        # 2. Recreation and restore risk findings
        for r in risk_assessment.findings:
            details = [sanitize_pii(d) for d in r.diagnostics]
            if r.remediation_operation:
                details.append(f"Required remediation: {r.remediation_operation}")
            if r.verification_operation:
                details.append(f"Required post-remediation verification: {r.verification_operation}")
            conclusions.append(
                FindingExplanation(
                    finding_type=r.risk_type,
                    resource_id=r.resource_id,
                    system_id=r.system_id,
                    data_category=r.data_category,
                    rule_id=None,
                    nature="POLICY_DERIVED_CONCLUSION",
                    evidence_id=r.evidence_id,
                    summary=sanitize_pii(r.risk_reason),
                    details=details,
                )
            )

        # 3. Verified compliant records (especially when case is COMPLETE or resources verified)
        if policy_result and policy_result.decisions:
            for dec in policy_result.decisions:
                if dec.compliance_result.value == "COMPLIANT" and dec.evidence_id:
                    # Distinguish retained vs deleted vs redacted
                    if dec.required_action == "RETAIN":
                        f_type = "VERIFY_RECORD_PRESENT"
                        summary = f"Legitimately retained under rule {dec.rule_id}."
                    elif dec.required_action == "REDACT" or dec.data_category == "ACCOUNT_TOMBSTONE":
                        f_type = "VERIFY_RECORD_REDACTED"
                        summary = f"Direct PII removed; compliant tombstone/redacted record under rule {dec.rule_id}."
                    elif dec.required_action == "ANONYMIZE":
                        f_type = "VERIFY_RECORD_ANONYMIZED"
                        summary = f"Anonymized per rule {dec.rule_id}."
                    elif dec.observed_state == "DISABLED":
                        f_type = "VERIFY_DATA_FLOW_DISABLED"
                        summary = "Data flow verified inactive."
                    elif dec.observed_state == "BLOCKED":
                        f_type = "VERIFY_RESTORE_BLOCKED"
                        summary = "Restore path verified blocked."
                    else:
                        f_type = "VERIFY_RECORD_ABSENT"
                        summary = f"Record absent and verified compliant under rule {dec.rule_id}."

                    conclusions.append(
                        FindingExplanation(
                            finding_type=f_type,
                            resource_id=dec.resource_id,
                            system_id=dec.system_id,
                            data_category=dec.data_category,
                            rule_id=dec.rule_id,
                            nature="VERIFICATION_PROOF",
                            evidence_id=dec.evidence_id,
                            summary=summary,
                            details=[sanitize_pii(dec.reason)],
                        )
                    )

        # Sort deterministically
        conclusions.sort(key=lambda c: (c.system_id, c.resource_id, c.finding_type))
        return conclusions

    def _collect_unresolved_uncertainties(
        self,
        resource_aggregation: ResourceAggregationResult,
        remaining_data: RemainingDataAssessmentResult,
        policy_result: Optional[CasePolicyEvaluationResult],
    ) -> list[ContradictionTrace]:
        uncertainties: list[ContradictionTrace] = []

        # 1. Direct timeline contradictions
        for contra in resource_aggregation.contradictions:
            uncertainties.append(
                ContradictionTrace(
                    resource_id="CASE_GLOBAL",
                    conflicting_claims=[sanitize_pii(contra)],
                    evidence_ids=[],
                    nature="UNRESOLVED_UNCERTAINTY",
                    impact="Evidence contradiction forces case status to INCOMPLETE.",
                )
            )

        # 2. Indeterminate resources lacking proof
        for ind_res in resource_aggregation.indeterminate_resources:
            reason = resource_aggregation.violations_by_resource.get(
                ind_res, "Lacks affirmative evidence of required deletion state."
            )
            uncertainties.append(
                ContradictionTrace(
                    resource_id=ind_res,
                    conflicting_claims=[f"Resource '{ind_res}': {sanitize_pii(reason)}"],
                    evidence_ids=[],
                    nature="UNRESOLVED_UNCERTAINTY",
                    impact="Absence of admissible proof prevents proving COMPLETE; forces status to INCOMPLETE.",
                )
            )

        # 3. Unverified resources from remaining data assessor
        for unv in remaining_data.unverified_resources:
            if not any(u.resource_id == unv for u in uncertainties):
                uncertainties.append(
                    ContradictionTrace(
                        resource_id=unv,
                        conflicting_claims=[f"Unverified resource claim for '{unv}' without supporting evidence."],
                        evidence_ids=[],
                        nature="UNRESOLVED_UNCERTAINTY",
                        impact="Unverified resource state cannot be presumed compliant.",
                    )
                )

        # Sort deterministically
        uncertainties.sort(key=lambda u: u.resource_id)
        return uncertainties

    def _collect_post_cutoff_exclusions(
        self,
        risk_assessment: RecreationRiskAssessmentResult,
        timeline_result: Optional[Any],
    ) -> list[str]:
        exclusions = list(risk_assessment.post_cutoff_events_excluded)

        if timeline_result and hasattr(timeline_result, "resources"):
            for rid, r_timeline in getattr(timeline_result, "resources", {}).items():
                if hasattr(r_timeline, "post_cutoff_events"):
                    for ev in getattr(r_timeline, "post_cutoff_events", []):
                        ev_type = getattr(ev, "event_type", "EVENT")
                        ts = getattr(ev, "timestamp", "")
                        desc = f"Resource '{rid}': Event '{ev_type}' at {ts} excluded (exceeds audit cutoff)."
                        if desc not in exclusions:
                            exclusions.append(desc)

        exclusions.sort()
        return [sanitize_pii(e) for e in exclusions]

    def _compile_evidence_citations(
        self,
        direct_observations: list[EvidenceTrace],
        policy_conclusions: list[FindingExplanation],
    ) -> list[str]:
        citations: set[str] = set()

        for obs in direct_observations:
            if obs.admissible_at_cutoff and obs.evidence_id.strip():
                citations.add(obs.evidence_id.strip())

        for concl in policy_conclusions:
            if concl.evidence_id and concl.evidence_id.strip():
                citations.add(concl.evidence_id.strip())

        return sorted(list(citations))

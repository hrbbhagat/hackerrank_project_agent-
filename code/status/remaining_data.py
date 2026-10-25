"""Phase 7: Remaining Data and Residual Violation Assessment.

Assesses participant-visible evidence indicating that personal data subject to
a deletion request remains present, exposed, or unredacted at the audit cutoff.
"""

from typing import Optional, Any
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
POLICY_DIR = CURRENT_DIR.parent / "policy"

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))

try:
    from .models import (
        ResidualFinding,
        RemainingDataAssessmentResult,
    )
except ImportError:
    from models import (
        ResidualFinding,
        RemainingDataAssessmentResult,
    )

try:
    from engine import ComplianceResult, ResourceTreatmentDecision
    from service import CasePolicyEvaluationResult
    from mapper import StepOperation
except ImportError:
    from .engine import ComplianceResult, ResourceTreatmentDecision
    from .service import CasePolicyEvaluationResult
    from .mapper import StepOperation


class RemainingDataAssessor:
    """
    Forensic assessor for residual personal data and policy violations.
    
    Distinguishes:
    1. Prohibited records that should have been deleted but remain present (REPORT_REMAINING_RECORD).
    2. Records permitted to exist where required direct PII remains exposed (REPORT_EXPOSED_PII).
    3. Legitimate retained records (SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD, compliant tombstones).
    4. Confirmed replica drift where replicas retain records after primary deletion.
    5. Deduplicates repeated sightings while preserving evidence provenance.
    """

    def assess_remaining_data(
        self,
        policy_result: CasePolicyEvaluationResult,
        timeline_result: Optional[Any] = None,
    ) -> RemainingDataAssessmentResult:
        """
        Assess residual data violations for a case at the audit cutoff.
        
        Args:
            policy_result: CasePolicyEvaluationResult produced by Phase 6.
            timeline_result: Optional TimelineReconstructionResult from Phase 5.
            
        Returns:
            RemainingDataAssessmentResult containing all structured residual findings.
        """
        case_id = str(policy_result.case_id or "").strip()
        diagnostics = list(policy_result.diagnostics)
        findings_map: dict[str, ResidualFinding] = {}
        legitimately_retained = []
        unverified_resources = []

        # 1. Evaluate all resource treatment decisions
        for dec in policy_result.decisions:
            rid = dec.resource_id
            cat = dec.data_category
            action = dec.required_action or ""
            observed = dec.observed_state

            # Handle Compliant Retained Data
            if dec.compliance_result == ComplianceResult.COMPLIANT:
                if cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD") or (cat == "ACCOUNT_TOMBSTONE" and observed in ("REDACTED", "PRESENT")):
                    legitimately_retained.append(rid)
                continue

            # Handle Indeterminate / Missing State
            if dec.compliance_result in (ComplianceResult.INDETERMINATE, ComplianceResult.NOT_APPLICABLE):
                unverified_resources.append(rid)
                diagnostics.append(f"Resource '{rid}' state at cutoff unverified: {dec.reason}")
                continue

            # Handle Non-Compliant Residual Findings
            if dec.compliance_result == ComplianceResult.NON_COMPLIANT:
                # Exclude pure infrastructure flow/restore risks (handled by flow risk aggregator)
                if cat in ("DATA_FLOW", "BACKUP_ARCHIVE"):
                    continue

                evidence_id = dec.evidence_id or ""
                # Cross-reference with timeline_result if evidence_id is blank
                if not evidence_id and timeline_result:
                    res_timeline = getattr(timeline_result, "resources", {}).get(rid)
                    if res_timeline:
                        evidence_id = getattr(res_timeline, "latest_admissible_evidence_id", "")

                # Determine finding type: REPORT_REMAINING_RECORD vs REPORT_EXPOSED_PII
                finding_type = StepOperation.REPORT_REMAINING_RECORD.value
                exposed_fields = []

                if cat == "ACCOUNT_TOMBSTONE":
                    finding_type = StepOperation.REPORT_EXPOSED_PII.value
                    exposed_fields = [f for f in ["name", "email", "phone", "email_hash"] if f in dec.reason.lower()]
                elif action in ("REDACT", "ANONYMIZE") or cat in ("SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG", "ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
                    finding_type = StepOperation.REPORT_EXPOSED_PII.value
                elif action == "DELETE" or cat in ("USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY", "USER_EXPORT", "MARKETING_PROFILE", "SUPPORT_ATTACHMENT"):
                    finding_type = StepOperation.REPORT_REMAINING_RECORD.value

                # Check if evidence is missing
                if not evidence_id:
                    diagnostics.append(f"Remaining data finding for '{rid}' lacks participant-visible evidence ID.")

                finding = ResidualFinding(
                    finding_type=finding_type,
                    system_id=dec.system_id,
                    resource_id=rid,
                    data_category=cat,
                    rule_id=dec.rule_id,
                    observed_state="PRESENT",
                    evidence_id=evidence_id,
                    violation_reason=dec.reason,
                    exposed_fields=exposed_fields,
                    is_replica_drift=False,
                    diagnostics=list(dec.diagnostics),
                )
                findings_map[rid] = finding

        # 2. Incorporate Replica Drift Findings
        for drift in policy_result.replica_drift_findings:
            drift_rid = drift.get("resource_id", "replica_record")
            drift_sys = drift.get("system_id", "replica_service")
            drift_ev = drift.get("evidence_id", "")
            
            # Replicas retaining records after primary deletion are REPORT_REMAINING_RECORD
            if drift_rid not in findings_map:
                drift_finding = ResidualFinding(
                    finding_type=StepOperation.REPORT_REMAINING_RECORD.value,
                    system_id=drift_sys,
                    resource_id=drift_rid,
                    data_category=drift.get("data_category", "USER_PROFILE"),
                    rule_id=drift.get("rule_id", "rule_01"),
                    observed_state="PRESENT",
                    evidence_id=drift_ev,
                    violation_reason="Primary record deletion claimed, but replica retains personal data at cutoff.",
                    exposed_fields=[],
                    is_replica_drift=True,
                    diagnostics=["Replica drift detected."],
                )
                findings_map[drift_rid] = drift_finding
            else:
                # Mark existing finding as replica drift
                existing = findings_map[drift_rid]
                findings_map[drift_rid] = ResidualFinding(
                    finding_type=existing.finding_type,
                    system_id=existing.system_id,
                    resource_id=existing.resource_id,
                    data_category=existing.data_category,
                    rule_id=existing.rule_id,
                    observed_state=existing.observed_state,
                    evidence_id=existing.evidence_id or drift_ev,
                    violation_reason=existing.violation_reason,
                    exposed_fields=existing.exposed_fields,
                    is_replica_drift=True,
                    diagnostics=existing.diagnostics + ["Replica drift detected."],
                )

        # 3. Deterministic Ordering by (finding_type, system_id, resource_id)
        # Order findings: REPORT_REMAINING_RECORD then REPORT_EXPOSED_PII per challenge specification
        type_priority = {
            StepOperation.REPORT_REMAINING_RECORD.value: 1,
            StepOperation.REPORT_EXPOSED_PII.value: 2,
        }

        sorted_findings = sorted(
            findings_map.values(),
            key=lambda f: (
                type_priority.get(f.finding_type, 99),
                f.system_id,
                f.resource_id,
            )
        )

        remaining_count = sum(1 for f in sorted_findings if f.finding_type == StepOperation.REPORT_REMAINING_RECORD.value)
        exposed_count = sum(1 for f in sorted_findings if f.finding_type == StepOperation.REPORT_EXPOSED_PII.value)
        drift_count = sum(1 for f in sorted_findings if f.is_replica_drift)

        return RemainingDataAssessmentResult(
            case_id=case_id,
            has_remaining_data=len(sorted_findings) > 0,
            total_residual_findings=len(sorted_findings),
            findings=sorted_findings,
            findings_by_resource={f.resource_id: f for f in sorted_findings},
            remaining_record_count=remaining_count,
            exposed_pii_count=exposed_count,
            replica_drift_count=drift_count,
            unverified_resources=sorted(list(set(unverified_resources))),
            legitimately_retained_resources=sorted(list(set(legitimately_retained))),
            diagnostics=diagnostics,
        )

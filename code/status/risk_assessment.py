"""Phase 7: Recreation, Synchronization, and Restore-Risk Assessor.

Forensically evaluates evidence of recreation after deletion, unpurged replicas,
active synchronization flows, and backup restore risks at the audit cutoff.
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
        RecreationRiskFinding,
        RecreationRiskAssessmentResult,
    )
except ImportError:
    from models import (
        RecreationRiskFinding,
        RecreationRiskAssessmentResult,
    )

try:
    from engine import ComplianceResult, ResourceTreatmentDecision
    from service import CasePolicyEvaluationResult
    from mapper import StepOperation, StepState
except ImportError:
    from .engine import ComplianceResult, ResourceTreatmentDecision
    from .service import CasePolicyEvaluationResult
    from .mapper import StepOperation, StepState


class RecreationRiskAssessor:
    """
    Assesses recreation, synchronization, and restore risks.
    
    Adheres strictly to challenge constraints:
    1. Distinguishes pre-cutoff events from post-cutoff events (post-cutoff events do not retroactively prove earlier violation).
    2. A failed restore attempt does not prove that data was restored.
    3. A backup archive is compliant if restore access is blocked (rule_14).
    4. Separates distinct resources and risk mechanisms.
    5. Does not create unsupported operations such as RESTORE_RECORD.
    """

    def assess_risks(
        self,
        policy_result: CasePolicyEvaluationResult,
        timeline_result: Optional[Any] = None,
    ) -> RecreationRiskAssessmentResult:
        """
        Evaluate all recreation, sync flow, and restore risks for a case at cutoff.
        
        Args:
            policy_result: CasePolicyEvaluationResult produced by Phase 6.
            timeline_result: Optional TimelineReconstructionResult from Phase 5.
            
        Returns:
            RecreationRiskAssessmentResult containing correlated risk findings.
        """
        case_id = str(policy_result.case_id or "").strip()
        diagnostics = list(policy_result.diagnostics)
        findings_map: dict[str, RecreationRiskFinding] = {}

        post_cutoff_excluded = []
        failed_restores_verified = []
        blocked_backups = []

        # 1. Inspect timeline_result for post-cutoff events and failed attempts
        if timeline_result:
            resources = getattr(timeline_result, "resources", {})
            for rid, r_timeline in resources.items():
                # Inspect post-cutoff events
                post_events = getattr(r_timeline, "post_cutoff_events", [])
                for ev in post_events:
                    post_cutoff_excluded.append(
                        f"Resource '{rid}': Event '{ev.event_type}' at {ev.timestamp} excluded (exceeds audit cutoff)."
                    )

                # Inspect failed attempts
                attempts = getattr(r_timeline, "deletion_attempts", [])
                for att in attempts:
                    if att.get("reported_result") == "FAILED":
                        failed_restores_verified.append(
                            f"Resource '{rid}': Failed operation '{att.get('event_type')}' verified; did not change state."
                        )

            # Check top-level failed attempts
            failed_attempts = getattr(timeline_result, "failed_attempts", [])
            for att in failed_attempts:
                failed_restores_verified.append(f"Recorded failed attempt: {att}")

        # 2. Evaluate Active Data Flows (REPORT_ACTIVE_DATA_FLOW)
        active_flows = list(policy_result.active_data_flows)
        # Also check resources categorized as DATA_FLOW
        for dec in policy_result.decisions:
            if dec.data_category == "DATA_FLOW":
                if dec.observed_state == "ACTIVE":
                    if not any(f.get("resource_id") == dec.resource_id for f in active_flows):
                        active_flows.append({
                            "resource_id": dec.resource_id,
                            "system_id": dec.system_id,
                            "evidence_id": dec.evidence_id or "",
                        })
                elif dec.observed_state in ("DISABLED", "BLOCKED"):
                    diagnostics.append(f"Data flow '{dec.resource_id}' is verified DISABLED at cutoff.")

        for flow in active_flows:
            flow_rid = flow.get("resource_id", "data_flow_unknown")
            flow_sys = flow.get("system_id", "integration_service")
            flow_ev = flow.get("evidence_id", "")
            
            # Cross-reference timeline evidence if blank
            if not flow_ev and timeline_result:
                r_tl = getattr(timeline_result, "resources", {}).get(flow_rid)
                if r_tl:
                    flow_ev = getattr(r_tl, "latest_admissible_evidence_id", "")

            finding = RecreationRiskFinding(
                risk_type=StepOperation.REPORT_ACTIVE_DATA_FLOW.value,
                system_id=flow_sys,
                resource_id=flow_rid,
                data_category="DATA_FLOW",
                observed_state=StepState.ACTIVE.value,
                evidence_id=flow_ev,
                risk_reason="Active synchronization process can replicate or recreate personal data.",
                is_pre_cutoff=True,
                remediation_operation=StepOperation.DISABLE_DATA_FLOW.value,
                verification_operation=StepOperation.VERIFY_DATA_FLOW_DISABLED.value,
                diagnostics=["Active data flow detected."],
            )
            findings_map[flow_rid] = finding

        # 3. Evaluate Restore Risks (REPORT_RESTORE_RISK)
        restore_risks = list(policy_result.restore_risks)
        # Also check resources categorized as BACKUP_ARCHIVE
        for dec in policy_result.decisions:
            if dec.data_category == "BACKUP_ARCHIVE":
                if dec.observed_state == "ACTIVE":
                    if not any(r.get("resource_id") == dec.resource_id for r in restore_risks):
                        restore_risks.append({
                            "resource_id": dec.resource_id,
                            "system_id": dec.system_id,
                            "evidence_id": dec.evidence_id or "",
                        })
                elif dec.observed_state == "BLOCKED":
                    blocked_backups.append(dec.resource_id)
                    diagnostics.append(f"Backup archive '{dec.resource_id}' restore access is verified BLOCKED (compliant with rule_14).")

        for risk in restore_risks:
            risk_rid = risk.get("resource_id", "backup_unknown")
            if risk.get("is_restore_blocked") is True or risk.get("observed_state") == "BLOCKED":
                if risk_rid not in blocked_backups:
                    blocked_backups.append(risk_rid)
                    diagnostics.append(f"Backup archive '{risk_rid}' restore access is verified BLOCKED (compliant with rule_14).")
                continue

            risk_sys = risk.get("system_id", "backup_service")
            risk_ev = risk.get("evidence_id", "")

            # Cross-reference timeline evidence if blank
            if not risk_ev and timeline_result:
                r_tl = getattr(timeline_result, "resources", {}).get(risk_rid)
                if r_tl:
                    risk_ev = getattr(r_tl, "latest_admissible_evidence_id", "")

            finding = RecreationRiskFinding(
                risk_type=StepOperation.REPORT_RESTORE_RISK.value,
                system_id=risk_sys,
                resource_id=risk_rid,
                data_category="BACKUP_ARCHIVE",
                observed_state=StepState.ACTIVE.value,
                evidence_id=risk_ev,
                risk_reason="Backup archive restore access is active; restore path can bring deleted data back.",
                is_pre_cutoff=True,
                remediation_operation=StepOperation.BLOCK_RESTORE.value,
                verification_operation=StepOperation.VERIFY_RESTORE_BLOCKED.value,
                diagnostics=["Restore risk detected."],
            )
            findings_map[risk_rid] = finding

        # 4. Evaluate Pre-Cutoff Recreation Events on Data Resources
        recreation_findings = []
        if timeline_result:
            rec_list = getattr(timeline_result, "recreation_findings", [])
            for rec in rec_list:
                rec_rid = rec.get("resource_id", "")
                if rec_rid and rec_rid not in findings_map:
                    # Note: Pre-cutoff recreation on a data record forces the record to be PRESENT
                    # which triggers REPORT_REMAINING_RECORD in RemainingDataAssessor.
                    # Here we also catalog the recreation mechanism.
                    rec_ev = rec.get("evidence_id", "")
                    finding = RecreationRiskFinding(
                        risk_type="RECREATION_EVENT",
                        system_id=rec.get("system_id", "sync_service"),
                        resource_id=rec_rid,
                        data_category=rec.get("data_category", "USER_PROFILE"),
                        observed_state="PRESENT",
                        evidence_id=rec_ev,
                        risk_reason=f"Data recreated before cutoff via {rec.get('event_type', 'SYNC_RECORD')}.",
                        is_pre_cutoff=True,
                        remediation_operation=StepOperation.DELETE_RECORD.value,
                        verification_operation=StepOperation.VERIFY_RECORD_ABSENT.value,
                        diagnostics=["Pre-cutoff data recreation event."],
                    )
                    findings_map[rec_rid] = finding
                    recreation_findings.append(finding)

        # 5. Evaluate Replica Drift Findings
        drift_findings = []
        for drift in policy_result.replica_drift_findings:
            drift_rid = drift.get("resource_id", "replica_record")
            if drift_rid not in findings_map:
                drift_sys = drift.get("system_id", "replica_service")
                drift_ev = drift.get("evidence_id", "")
                finding = RecreationRiskFinding(
                    risk_type="REPLICA_DRIFT",
                    system_id=drift_sys,
                    resource_id=drift_rid,
                    data_category=drift.get("data_category", "USER_PROFILE"),
                    observed_state="PRESENT",
                    evidence_id=drift_ev,
                    risk_reason="Replica drift: primary record deletion claimed, but replica retained data at cutoff.",
                    is_pre_cutoff=True,
                    remediation_operation=StepOperation.DELETE_RECORD.value,
                    verification_operation=StepOperation.VERIFY_RECORD_ABSENT.value,
                    diagnostics=["Replica drift detected."],
                )
                findings_map[drift_rid] = finding
                drift_findings.append(finding)

        # 6. Deterministic Sorting: REPORT_ACTIVE_DATA_FLOW, REPORT_RESTORE_RISK, then system_id, resource_id
        type_priority = {
            StepOperation.REPORT_ACTIVE_DATA_FLOW.value: 1,
            StepOperation.REPORT_RESTORE_RISK.value: 2,
            "REPLICA_DRIFT": 3,
            "RECREATION_EVENT": 4,
        }

        sorted_findings = sorted(
            findings_map.values(),
            key=lambda f: (
                type_priority.get(f.risk_type, 99),
                f.system_id,
                f.resource_id,
            )
        )

        flow_count = sum(1 for f in sorted_findings if f.risk_type == StepOperation.REPORT_ACTIVE_DATA_FLOW.value)
        restore_count = sum(1 for f in sorted_findings if f.risk_type == StepOperation.REPORT_RESTORE_RISK.value)
        rec_count = sum(1 for f in sorted_findings if f.risk_type == "RECREATION_EVENT")
        drift_count = sum(1 for f in sorted_findings if f.risk_type == "REPLICA_DRIFT")

        return RecreationRiskAssessmentResult(
            case_id=case_id,
            has_active_risks=len(sorted_findings) > 0,
            total_risk_findings=len(sorted_findings),
            findings=sorted_findings,
            findings_by_resource={f.resource_id: f for f in sorted_findings},
            active_flows_count=flow_count,
            restore_risks_count=restore_count,
            recreation_count=rec_count,
            replica_drift_count=drift_count,
            post_cutoff_events_excluded=sorted(post_cutoff_excluded),
            failed_restores_verified_unrestored=sorted(failed_restores_verified),
            blocked_backups_compliant=sorted(list(set(blocked_backups))),
            diagnostics=diagnostics,
        )

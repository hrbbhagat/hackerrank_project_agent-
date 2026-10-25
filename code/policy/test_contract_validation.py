"""Phase 6.9: End-to-End Policy Integration and Contract Validation Test Suite.

Exercises the complete in-memory pipeline from request through Phase 3B/4/5
into Phase 6 policy evaluation.

Validates the Phase 6 contract across all 9 representative scenarios:
1. Non-deletion requests
2. Prohibited record that remains
3. Compliant deletion with admissible evidence
4. Required redaction or anonymization
5. Permitted account tombstone
6. Mandatory retention
7. Replica drift
8. Active sync flow and restoration risk
9. Missing, conflicting, or temporally inadmissible evidence

Validates downstream compatibility without crossing phase boundaries.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

POLICY_DIR = Path(__file__).resolve().parent
ROOT_DIR = POLICY_DIR.parent.parent
IDENTITY_DIR = ROOT_DIR / "code" / "identity"
TIMELINE_DIR = ROOT_DIR / "code" / "timeline"
EVIDENCE_DIR = ROOT_DIR / "code" / "evidence"

for p in [POLICY_DIR, IDENTITY_DIR, TIMELINE_DIR, EVIDENCE_DIR]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from .loader import PolicyLoader
    from .engine import (
        TreatmentEngine,
        ComplianceResult,
        RequiredAction,
        ResourceTreatmentDecision,
    )
    from .mapper import (
        PolicyOperationMapper,
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
    )
    from .service import (
        PolicyEvaluationService,
        CasePolicyEvaluationResult,
    )
except ImportError:
    from loader import PolicyLoader
    from engine import (
        TreatmentEngine,
        ComplianceResult,
        RequiredAction,
        ResourceTreatmentDecision,
    )
    from mapper import (
        PolicyOperationMapper,
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
    )
    from service import (
        PolicyEvaluationService,
        CasePolicyEvaluationResult,
    )

from resolver import IdentityResolver
from integration import EvidenceIntegrator
from reconstructor import (
    TimelineReconstructor,
    TimelineReconstructionResult,
    ResourceTimeline,
    TimelineEvent,
)


class TestPhase6ContractValidation(unittest.TestCase):
    """End-to-end contract validation suite for Phase 6 policy evaluation."""

    @classmethod
    def setUpClass(cls):
        dataset_dir = ROOT_DIR / "dataset"
        cls.resolver = IdentityResolver.from_directory(dataset_dir)
        cls.integrator = EvidenceIntegrator()
        cls.reconstructor = TimelineReconstructor()
        cls.policy_service = PolicyEvaluationService()
        cls.audit_cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # -------------------------------------------------------------
    # Scenario 1: Non-deletion requests
    # -------------------------------------------------------------
    def test_01_non_deletion_request_contract(self):
        """Non-deletion requests are tagged as is_non_deletion_request=True by upstream."""
        request = {
            "case_id": "case_533",
            "email": "customer@example.com",
            "requested_at": "2026-05-01T10:00:00Z",
            "reported_status": "NOT_STARTED",
            "reported_at": "2026-05-01T10:00:00Z",
            "audit_at": "2026-06-01T12:00:00Z",
            "request_text": "Please provide a portable format copy of all my invoices. Do not close or delete my account.",
        }
        recon = self.reconstructor.reconstruct_for_request(request, self.resolver, self.integrator)
        self.assertTrue(recon.is_non_deletion_request)

        result = self.policy_service.evaluate_timeline(request, recon)
        self.assertTrue(result.is_non_deletion_request)
        self.assertEqual(result.case_id, "case_533")
        # In later phases: non-deletion requests receive NOT_APPLICABLE and steps_json=[]

    # -------------------------------------------------------------
    # Scenario 2: A record that must be deleted but remains
    # -------------------------------------------------------------
    def test_02_prohibited_record_remains(self):
        """Prohibited record remaining PRESENT at cutoff evaluates to NON_COMPLIANT."""
        ev = TimelineEvent(
            event_id="ev_01",
            timestamp=datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc),
            source_type="evidence_record",
            evidence_id="evidence_db_01",
            system_id="account_service",
            resource_id="account_005",
            event_type="DATABASE_RECORD",
            action_category="ACTION_EVIDENCE_SIGHTING",
            reported_result="PRESENT",
            details="User row present in customer table",
            matched_identifier="user@example.com",
            is_admissible=True,
            exclusion_reason=None,
        )
        timeline = ResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            events=[ev],
            post_cutoff_events=[],
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_db_01",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=[],
            evidence_provenance=["evidence_db_01"],
        )
        recon = TimelineReconstructionResult(
            case_id="case_002",
            user_id="usr_002",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            resources={"account_005": timeline},
            recreation_findings=[],
            active_data_flows=[],
            restore_risks=[],
            unassociated_events=[],
            contradictions=[],
            errors=[],
            summary={"total_resources": 1},
        )
        request = {"case_id": "case_002", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon)
        self.assertEqual(len(result.decisions), 1)
        dec = result.decisions[0]
        bundle = result.operation_bundles[0]

        self.assertEqual(dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(dec.required_action, "DELETE")
        self.assertEqual(dec.observed_state, "PRESENT")
        self.assertEqual(dec.evidence_id, "evidence_db_01")
        self.assertEqual(bundle.finding_operation, StepOperation.REPORT_REMAINING_RECORD)
        self.assertEqual(bundle.remediation_operation, StepOperation.DELETE_RECORD)
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_ABSENT)

    # -------------------------------------------------------------
    # Scenario 3: A compliant deletion with admissible evidence
    # -------------------------------------------------------------
    def test_03_compliant_deletion_with_admissible_evidence(self):
        """Record verified ABSENT at cutoff evaluates to COMPLIANT."""
        ev = TimelineEvent(
            event_id="act_501",
            timestamp=datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
            source_type="system_activity",
            evidence_id="act_501",
            system_id="account_service",
            resource_id="account_005",
            event_type="DELETE_RECORD",
            action_category="ACTION_DELETE",
            reported_result="SUCCESS",
            details="Profile deleted",
            matched_identifier="user@example.com",
            is_admissible=True,
            exclusion_reason=None,
        )
        timeline = ResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            events=[ev],
            post_cutoff_events=[],
            state_at_cutoff="ABSENT",
            latest_admissible_evidence_id="act_501",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=[],
            evidence_provenance=["act_501"],
            has_corroborated_deletion=True,
        )
        recon = TimelineReconstructionResult(
            case_id="case_003",
            user_id="usr_003",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            resources={"account_005": timeline},
            recreation_findings=[],
            active_data_flows=[],
            restore_risks=[],
            unassociated_events=[],
            contradictions=[],
            errors=[],
            summary={"total_resources": 1},
        )
        request = {"case_id": "case_003", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon)
        dec = result.decisions[0]
        bundle = result.operation_bundles[0]

        self.assertEqual(dec.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec.observed_state, "ABSENT")
        self.assertEqual(dec.evidence_id, "act_501")
        self.assertIsNone(bundle.finding_operation)
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_ABSENT)

    # -------------------------------------------------------------
    # Scenario 4: Required redaction or anonymization
    # -------------------------------------------------------------
    def test_04_required_redaction_and_anonymization(self):
        """Support message (REDACT) and analytics profile (ANONYMIZE) evaluations."""
        timeline_msg = ResourceTimeline(
            resource_id="support_471",
            system_id="support_platform",
            resource_category="SUPPORT_MESSAGE",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="REDACTED",
            latest_admissible_evidence_id="evidence_sup_01",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=[],
            evidence_provenance=["evidence_sup_01"],
        )
        timeline_anon = ResourceTimeline(
            resource_id="analytics_99",
            system_id="analytics_platform",
            resource_category="ANALYTICS_PROFILE",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="ANONYMIZED",
            latest_admissible_evidence_id="evidence_an_01",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=[],
            evidence_provenance=["evidence_an_01"],
        )
        recon = TimelineReconstructionResult(
            case_id="case_004",
            user_id="usr_004",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            resources={"support_471": timeline_msg, "analytics_99": timeline_anon},
            recreation_findings=[],
            active_data_flows=[],
            restore_risks=[],
            unassociated_events=[],
            contradictions=[],
            errors=[],
            summary={"total_resources": 2},
        )
        request = {"case_id": "case_004", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon)
        dec_msg = result.decisions_by_resource["support_471"]
        dec_anon = result.decisions_by_resource["analytics_99"]

        self.assertEqual(dec_msg.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec_msg.required_action, "REDACT")
        self.assertEqual(result.operation_bundles_by_resource["support_471"].verification_operation, StepOperation.VERIFY_RECORD_REDACTED)

        self.assertEqual(dec_anon.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec_anon.required_action, "ANONYMIZE")
        self.assertEqual(result.operation_bundles_by_resource["analytics_99"].verification_operation, StepOperation.VERIFY_RECORD_ANONYMIZED)

    # -------------------------------------------------------------
    # Scenario 5: Permitted account tombstone
    # -------------------------------------------------------------
    def test_05_permitted_account_tombstone(self):
        """Account tombstone with stable user ID preserved and direct identifiers redacted."""
        tombstone_data = {
            "user_id": "usr_005",
            "account_status": "DELETED",
            "name": None,
            "email": None,
            "phone": None,
        }
        timeline = ResourceTimeline(
            resource_id="tombstone_005",
            system_id="identity_service",
            resource_category="ACCOUNT_TOMBSTONE",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="REDACTED",
            latest_admissible_evidence_id="evidence_tb_01",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=[],
            evidence_provenance=["evidence_tb_01"],
        )
        recon = TimelineReconstructionResult(
            case_id="case_005",
            user_id="usr_005",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            resources={"tombstone_005": timeline},
            recreation_findings=[],
            active_data_flows=[],
            restore_risks=[],
            unassociated_events=[],
            contradictions=[],
            errors=[],
            summary={"total_resources": 1},
        )
        request = {"case_id": "case_005", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon, context={"record_data": tombstone_data})
        dec = result.decisions[0]
        bundle = result.operation_bundles[0]

        self.assertEqual(dec.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec.required_action, "REDACT")
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_REDACTED)

    # -------------------------------------------------------------
    # Scenario 6: Mandatory retention
    # -------------------------------------------------------------
    def test_06_mandatory_retention_contract(self):
        """Security audit log within retention period is compliant when PRESENT."""
        timeline = ResourceTimeline(
            resource_id="audit_record_99",
            system_id="security_service",
            resource_category="SECURITY_AUDIT_LOG",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_audit_01",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=[],
            evidence_provenance=["evidence_audit_01"],
        )
        recon = TimelineReconstructionResult(
            case_id="case_006",
            user_id="usr_006",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            resources={"audit_record_99": timeline},
            recreation_findings=[],
            active_data_flows=[],
            restore_risks=[],
            unassociated_events=[],
            contradictions=[],
            errors=[],
            summary={"total_resources": 1},
        )
        request = {"case_id": "case_006", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon, context={"within_retention_period": True})
        dec = result.decisions[0]
        bundle = result.operation_bundles[0]

        self.assertEqual(dec.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec.required_action, "RETAIN")
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_PRESENT)

    # -------------------------------------------------------------
    # Scenario 7: Replica drift
    # -------------------------------------------------------------
    def test_07_replica_drift_contract(self):
        """Replica retains record while primary was deleted $\to$ evaluated as PRESENT and NON_COMPLIANT."""
        timeline = ResourceTimeline(
            resource_id="account_005",
            system_id="reporting_replica",
            resource_category="USER_PROFILE",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_rep_sql",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=["Primary deletion reported SUCCESS, but replica snapshot retains record"],
            evidence_provenance=["evidence_rep_sql"],
            replica_drift=True,
        )
        recon = TimelineReconstructionResult(
            case_id="case_007",
            user_id="usr_007",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            resources={"account_005": timeline},
            recreation_findings=[],
            active_data_flows=[],
            restore_risks=[],
            unassociated_events=[],
            contradictions=timeline.contradictions,
            errors=[],
            summary={"total_resources": 1},
            replica_drift_findings=[{"resource_id": "account_005", "replica_system": "reporting_replica"}],
        )
        request = {"case_id": "case_007", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon)
        dec = result.decisions[0]
        bundle = result.operation_bundles[0]

        self.assertEqual(dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(dec.observed_state, "PRESENT")
        self.assertEqual(bundle.finding_operation, StepOperation.REPORT_REMAINING_RECORD)
        self.assertEqual(bundle.remediation_operation, StepOperation.DELETE_RECORD)
        self.assertEqual(len(result.replica_drift_findings), 1)

    # -------------------------------------------------------------
    # Scenario 8: Active sync and restoration risk
    # -------------------------------------------------------------
    def test_08_active_sync_and_restore_risk_contract(self):
        """Active sync and restore risks surfaced even if primary record is absent."""
        flow = ResourceTimeline(
            resource_id="data_flow_901",
            system_id="integration_service",
            resource_category="DATA_FLOW",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="ACTIVE",
            latest_admissible_evidence_id="evidence_flow_01",
            is_recreated=False,
            is_active_flow=True,
            is_restore_risk=False,
            contradictions=[],
            evidence_provenance=["evidence_flow_01"],
        )
        backup = ResourceTimeline(
            resource_id="backup_arc_01",
            system_id="backup_service",
            resource_category="BACKUP_ARCHIVE",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="ACTIVE",
            latest_admissible_evidence_id="evidence_bak_01",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=True,
            contradictions=[],
            evidence_provenance=["evidence_bak_01"],
        )
        recon = TimelineReconstructionResult(
            case_id="case_008",
            user_id="usr_008",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            resources={"data_flow_901": flow, "backup_arc_01": backup},
            recreation_findings=[],
            active_data_flows=[{"resource_id": "data_flow_901"}],
            restore_risks=[{"resource_id": "backup_arc_01"}],
            unassociated_events=[],
            contradictions=[],
            errors=[],
            summary={"total_resources": 2},
        )
        request = {"case_id": "case_008", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon)
        flow_dec = result.decisions_by_resource["data_flow_901"]
        flow_bundle = result.operation_bundles_by_resource["data_flow_901"]
        backup_dec = result.decisions_by_resource["backup_arc_01"]
        backup_bundle = result.operation_bundles_by_resource["backup_arc_01"]

        self.assertEqual(flow_dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(flow_bundle.finding_operation, StepOperation.REPORT_ACTIVE_DATA_FLOW)
        self.assertEqual(flow_bundle.remediation_operation, StepOperation.DISABLE_DATA_FLOW)

        self.assertEqual(backup_dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(backup_bundle.finding_operation, StepOperation.REPORT_RESTORE_RISK)
        self.assertEqual(backup_bundle.remediation_operation, StepOperation.BLOCK_RESTORE)

    # -------------------------------------------------------------
    # Scenario 9: Missing, conflicting, or inadmissible evidence
    # -------------------------------------------------------------
    def test_09_missing_conflicting_or_inadmissible_evidence(self):
        """Missing or conflicting evidence produces INDETERMINATE without crashing."""
        timeline_unknown = ResourceTimeline(
            resource_id="cache_entry_44",
            system_id="cache_service",
            resource_category="CACHE_ENTRY",
            events=[],
            post_cutoff_events=[],
            state_at_cutoff="UNKNOWN",
            latest_admissible_evidence_id="",
            is_recreated=False,
            is_active_flow=False,
            is_restore_risk=False,
            contradictions=["Evidence captured post-cutoff excluded; no admissible state sighting"],
            evidence_provenance=[],
        )
        recon = TimelineReconstructionResult(
            case_id="case_009",
            user_id="usr_009",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="AMBIGUOUS",
            resources={"cache_entry_44": timeline_unknown},
            recreation_findings=[],
            active_data_flows=[],
            restore_risks=[],
            unassociated_events=[],
            contradictions=timeline_unknown.contradictions,
            errors=["Parser error in evidence archive"],
            summary={"total_resources": 1},
        )
        request = {"case_id": "case_009", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon)
        dec = result.decisions[0]

        self.assertEqual(dec.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertEqual(result.resolution_status, "AMBIGUOUS")
        self.assertEqual(len(result.upstream_errors), 1)
        self.assertEqual(len(result.contradictions), 1)

    # -------------------------------------------------------------
    # Downstream Contract & Permitted Combinations Verification
    # -------------------------------------------------------------
    def test_10_downstream_permitted_combinations_strict_enforcement(self):
        """Every operation bundle produced by Phase 6 conforms to the 15 challenge permitted triples."""
        # Test across diverse mock categories
        from test_service import MockResourceTimeline, MockTimelineReconstructionResult
        t_del = MockResourceTimeline("acc_01", "account_service", "USER_PROFILE", "PRESENT", "evidence_db")
        t_red = MockResourceTimeline("sup_01", "support_platform", "SUPPORT_MESSAGE", "PRESENT", "evidence_sup")
        t_anon = MockResourceTimeline("ana_01", "analytics_platform", "ANALYTICS_PROFILE", "PRESENT", "evidence_ana")
        t_flow = MockResourceTimeline("flow_01", "integration_service", "DATA_FLOW", "ACTIVE", "evidence_flow", is_active_flow=True)
        t_risk = MockResourceTimeline("bak_01", "backup_service", "BACKUP_ARCHIVE", "ACTIVE", "evidence_bak", is_restore_risk=True)

        recon = MockTimelineReconstructionResult(
            case_id="case_perm_01",
            resources={"acc_01": t_del, "sup_01": t_red, "ana_01": t_anon, "flow_01": t_flow, "bak_01": t_risk},
        )
        request = {"case_id": "case_perm_01", "audit_at": "2026-06-01T12:00:00Z"}

        result = self.policy_service.evaluate_timeline(request, recon)

        for bundle in result.operation_bundles:
            for op_spec in bundle.findings:
                self.assertIn((op_spec.phase, op_spec.operation, op_spec.state), PERMITTED_COMBINATIONS)
            for op_spec in bundle.remediations:
                self.assertIn((op_spec.phase, op_spec.operation, op_spec.state), PERMITTED_COMBINATIONS)
            for op_spec in bundle.verifications:
                self.assertIn((op_spec.phase, op_spec.operation, op_spec.state), PERMITTED_COMBINATIONS)


if __name__ == "__main__":
    unittest.main()

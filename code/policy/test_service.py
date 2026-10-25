"""Tests for Phase 6.7: Policy Evaluation Service Integration.

Tests the full integration between:
- Upstream Phase 5 TimelineReconstructionResult
- Phase 6 PolicyEvaluationService
- Deterministic policy evaluation & challenge operation mapping
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

POLICY_DIR = Path(__file__).resolve().parent
ROOT_DIR = POLICY_DIR.parent.parent

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))

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
    )
    from service import (
        PolicyEvaluationService,
        CasePolicyEvaluationResult,
    )


class MockTimelineEvent:
    def __init__(
        self,
        event_id: str,
        timestamp: datetime,
        evidence_id: str = "",
        event_type: str = "DATABASE_RECORD",
        action_category: str = "ACTION_EVIDENCE_SIGHTING",
        is_admissible: bool = True,
    ):
        self.event_id = event_id
        self.timestamp = timestamp
        self.evidence_id = evidence_id
        self.event_type = event_type
        self.action_category = action_category
        self.is_admissible = is_admissible


class MockResourceTimeline:
    def __init__(
        self,
        resource_id: str,
        system_id: str,
        resource_category: str,
        state_at_cutoff: str,
        latest_admissible_evidence_id: str = "",
        events: list = None,
        post_cutoff_events: list = None,
        is_recreated: bool = False,
        is_active_flow: bool = False,
        is_restore_risk: bool = False,
        replica_drift: bool = False,
        contradictions: list = None,
        evidence_provenance: list = None,
        has_corroborated_deletion: bool = False,
    ):
        self.resource_id = resource_id
        self.system_id = system_id
        self.resource_category = resource_category
        self.state_at_cutoff = state_at_cutoff
        self.latest_admissible_evidence_id = latest_admissible_evidence_id
        self.events = events or []
        self.post_cutoff_events = post_cutoff_events or []
        self.is_recreated = is_recreated
        self.is_active_flow = is_active_flow
        self.is_restore_risk = is_restore_risk
        self.replica_drift = replica_drift
        self.contradictions = contradictions or []
        self.evidence_provenance = evidence_provenance or []
        self.has_corroborated_deletion = has_corroborated_deletion


class MockTimelineReconstructionResult:
    def __init__(
        self,
        case_id: str,
        user_id: str = "user_101",
        audit_at: datetime = None,
        is_non_deletion_request: bool = False,
        resolution_status: str = "RESOLVED",
        resources: dict = None,
        recreation_findings: list = None,
        active_data_flows: list = None,
        restore_risks: list = None,
        replica_drift_findings: list = None,
        errors: list = None,
        contradictions: list = None,
    ):
        self.case_id = case_id
        self.user_id = user_id
        self.audit_at = audit_at or datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        self.is_non_deletion_request = is_non_deletion_request
        self.resolution_status = resolution_status
        self.resources = resources or {}
        self.recreation_findings = recreation_findings or []
        self.active_data_flows = active_data_flows or []
        self.restore_risks = restore_risks or []
        self.replica_drift_findings = replica_drift_findings or []
        self.errors = errors or []
        self.contradictions = contradictions or []


class TestPolicyEvaluationServiceIntegration(unittest.TestCase):
    """Integration test suite for PolicyEvaluationService."""

    def setUp(self):
        self.service = PolicyEvaluationService()
        self.cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.request = {
            "case_id": "case_test_001",
            "email": "user@example.com",
            "requested_at": "2026-05-01T10:00:00Z",
            "reported_status": "PARTIALLY_COMPLETE",
            "reported_at": "2026-05-15T10:00:00Z",
            "audit_at": "2026-06-01T12:00:00Z",
            "request_text": "Please delete all my personal data from your platform.",
        }

    def test_prohibited_record_that_remains(self):
        """A prohibited record (USER_PROFILE) that remains PRESENT at cutoff."""
        timeline = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_db_01",
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"account_005": timeline},
        )

        result = self.service.evaluate_timeline(self.request, recon)
        self.assertIn("account_005", result.decisions_by_resource)
        dec = result.decisions_by_resource["account_005"]
        bundle = result.operation_bundles_by_resource["account_005"]

        self.assertEqual(dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(dec.required_action, "DELETE")
        self.assertEqual(dec.observed_state, "PRESENT")
        self.assertEqual(dec.evidence_id, "evidence_db_01")

        # Verify challenge operations mapped
        self.assertEqual(bundle.finding_operation, StepOperation.REPORT_REMAINING_RECORD)
        self.assertEqual(bundle.finding_state, StepState.PRESENT)
        self.assertEqual(bundle.remediation_operation, StepOperation.DELETE_RECORD)
        self.assertEqual(bundle.remediation_state, StepState.ABSENT)
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_ABSENT)
        self.assertEqual(bundle.verification_state, StepState.ABSENT)

    def test_correctly_redacted_record(self):
        """A correctly redacted support message record."""
        timeline = MockResourceTimeline(
            resource_id="support_msg_88",
            system_id="support_platform",
            resource_category="SUPPORT_MESSAGE",
            state_at_cutoff="REDACTED",
            latest_admissible_evidence_id="evidence_sup_02",
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"support_msg_88": timeline},
        )

        result = self.service.evaluate_timeline(self.request, recon)
        dec = result.decisions_by_resource["support_msg_88"]
        bundle = result.operation_bundles_by_resource["support_msg_88"]

        self.assertEqual(dec.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec.required_action, "REDACT")
        self.assertEqual(dec.observed_state, "REDACTED")
        self.assertIsNone(bundle.finding_operation)
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_REDACTED)
        self.assertEqual(bundle.verification_state, StepState.REDACTED)

    def test_policy_required_retained_record(self):
        """A security audit log required to be retained by policy."""
        timeline = MockResourceTimeline(
            resource_id="audit_record_99",
            system_id="security_service",
            resource_category="SECURITY_AUDIT_LOG",
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_audit_01",
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"audit_record_99": timeline},
        )

        result = self.service.evaluate_timeline(self.request, recon)
        dec = result.decisions_by_resource["audit_record_99"]
        bundle = result.operation_bundles_by_resource["audit_record_99"]

        self.assertEqual(dec.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec.required_action, "RETAIN")
        self.assertEqual(dec.observed_state, "PRESENT")
        self.assertIsNone(bundle.finding_operation)
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_PRESENT)
        self.assertEqual(bundle.verification_state, StepState.PRESENT)

    def test_permitted_tombstone(self):
        """A permitted account tombstone with stable user ID only."""
        timeline = MockResourceTimeline(
            resource_id="tombstone_user_101",
            system_id="identity_service",
            resource_category="ACCOUNT_TOMBSTONE",
            state_at_cutoff="REDACTED",
            latest_admissible_evidence_id="evidence_tb_01",
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"tombstone_user_101": timeline},
        )

        result = self.service.evaluate_timeline(self.request, recon)
        dec = result.decisions_by_resource["tombstone_user_101"]
        bundle = result.operation_bundles_by_resource["tombstone_user_101"]

        self.assertEqual(dec.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(dec.required_action, "REDACT")
        self.assertIsNone(bundle.finding_operation)
        self.assertEqual(bundle.verification_operation, StepOperation.VERIFY_RECORD_REDACTED)

    def test_replica_drift_scenario(self):
        """Primary record deleted, but replica retains record at cutoff."""
        timeline = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_replica_db",
            replica_drift=True,
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"account_005": timeline},
            replica_drift_findings=[{"resource_id": "account_005", "replica_system": "reporting_replica"}],
        )

        result = self.service.evaluate_timeline(self.request, recon)
        dec = result.decisions_by_resource["account_005"]
        bundle = result.operation_bundles_by_resource["account_005"]

        self.assertEqual(dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(dec.observed_state, "PRESENT")
        self.assertEqual(bundle.finding_operation, StepOperation.REPORT_REMAINING_RECORD)
        self.assertEqual(len(result.replica_drift_findings), 1)

    def test_recreation_and_active_sync_scenario(self):
        """Active sync/data flow surfaced even if primary record is absent."""
        primary_timeline = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="ABSENT",
            latest_admissible_evidence_id="act_501",
            has_corroborated_deletion=True,
        )
        flow_timeline = MockResourceTimeline(
            resource_id="data_flow_301",
            system_id="integration_service",
            resource_category="DATA_FLOW",
            state_at_cutoff="ACTIVE",
            latest_admissible_evidence_id="evidence_flow_01",
            is_active_flow=True,
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"account_005": primary_timeline, "data_flow_301": flow_timeline},
            active_data_flows=[{"resource_id": "data_flow_301", "system_id": "integration_service"}],
        )

        result = self.service.evaluate_timeline(self.request, recon)
        # Primary is compliant
        self.assertEqual(result.decisions_by_resource["account_005"].compliance_result, ComplianceResult.COMPLIANT)
        # Active data flow is non-compliant
        flow_dec = result.decisions_by_resource["data_flow_301"]
        flow_bundle = result.operation_bundles_by_resource["data_flow_301"]
        self.assertEqual(flow_dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(flow_dec.observed_state, "ACTIVE")
        self.assertEqual(flow_bundle.finding_operation, StepOperation.REPORT_ACTIVE_DATA_FLOW)
        self.assertEqual(flow_bundle.remediation_operation, StepOperation.DISABLE_DATA_FLOW)

    def test_restore_risk_scenario(self):
        """Active restore risk surfaced even if primary record is absent."""
        primary_timeline = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="ABSENT",
            latest_admissible_evidence_id="act_501",
            has_corroborated_deletion=True,
        )
        backup_timeline = MockResourceTimeline(
            resource_id="backup_archive_22",
            system_id="backup_service",
            resource_category="BACKUP_ARCHIVE",
            state_at_cutoff="ACTIVE",
            latest_admissible_evidence_id="evidence_bak_01",
            is_restore_risk=True,
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"account_005": primary_timeline, "backup_archive_22": backup_timeline},
            restore_risks=[{"resource_id": "backup_archive_22", "system_id": "backup_service"}],
        )

        result = self.service.evaluate_timeline(self.request, recon)
        risk_dec = result.decisions_by_resource["backup_archive_22"]
        risk_bundle = result.operation_bundles_by_resource["backup_archive_22"]

        self.assertEqual(risk_dec.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(risk_dec.observed_state, "ACTIVE")
        self.assertEqual(risk_bundle.finding_operation, StepOperation.REPORT_RESTORE_RISK)
        self.assertEqual(risk_bundle.remediation_operation, StepOperation.BLOCK_RESTORE)

    def test_no_admissible_evidence(self):
        """Resource state is UNKNOWN due to missing admissible evidence."""
        timeline = MockResourceTimeline(
            resource_id="export_991",
            system_id="export_service",
            resource_category="USER_EXPORT",
            state_at_cutoff="UNKNOWN",
            latest_admissible_evidence_id="",
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"export_991": timeline},
        )

        result = self.service.evaluate_timeline(self.request, recon)
        dec = result.decisions_by_resource["export_991"]
        self.assertEqual(dec.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertEqual(dec.observed_state, "UNKNOWN")

    def test_unresolved_policy_match(self):
        """A resource with an unknown category without a matching policy rule."""
        timeline = MockResourceTimeline(
            resource_id="custom_device_01",
            system_id="hardware_service",
            resource_category="UNKNOWN_DEVICE_TYPE",
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_hw_01",
        )
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resources={"custom_device_01": timeline},
        )

        result = self.service.evaluate_timeline(self.request, recon)
        dec = result.decisions_by_resource["custom_device_01"]
        self.assertEqual(dec.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertIsNone(dec.rule_id)

    def test_upstream_parsing_or_resolution_diagnostic(self):
        """Upstream errors from identity resolution or evidence parsing are preserved."""
        recon = MockTimelineReconstructionResult(
            case_id="case_test_001",
            resolution_status="AMBIGUOUS",
            errors=["Multiple user accounts match request email", "Evidence file 32 corrupt"],
            contradictions=["Timestamp inversion in audit log"],
        )

        result = self.service.evaluate_timeline(self.request, recon)
        self.assertEqual(result.resolution_status, "AMBIGUOUS")
        self.assertEqual(len(result.upstream_errors), 2)
        self.assertIn("Multiple user accounts match request email", result.upstream_errors)
        self.assertIn("Timestamp inversion in audit log", result.contradictions)


if __name__ == "__main__":
    unittest.main()

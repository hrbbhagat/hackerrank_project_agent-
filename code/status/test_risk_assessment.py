"""Phase 7.5 Unit Tests: Recreation, Synchronization, and Restore-Risk Assessment.

Tests:
1. Active synchronization data flow detected (REPORT_ACTIVE_DATA_FLOW).
2. Disabled data flow is verified compliant (not an active risk).
3. Active restore risk on backup archive detected (REPORT_RESTORE_RISK).
4. Blocked backup archive is compliant per rule_14 (not an active risk).
5. Failed restoration attempt does not prove data was restored.
6. Pre-cutoff recreation event detected and correlated.
7. Post-cutoff events excluded from cutoff decisions (does not retroactively prove earlier violation).
8. Replica drift surfaced as active pre-cutoff risk.
9. Deterministic ordering: REPORT_ACTIVE_DATA_FLOW before REPORT_RESTORE_RISK, then system_id, resource_id.
10. Repeat-run determinism across 50 iterations.
"""

from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
POLICY_DIR = ROOT_DIR / "code" / "policy"

for p in [CURRENT_DIR, POLICY_DIR]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from .models import (
        RecreationRiskFinding,
        RecreationRiskAssessmentResult,
    )
    from .risk_assessment import RecreationRiskAssessor
except ImportError:
    from models import (
        RecreationRiskFinding,
        RecreationRiskAssessmentResult,
    )
    from risk_assessment import RecreationRiskAssessor

from engine import ComplianceResult, ResourceTreatmentDecision
from service import CasePolicyEvaluationResult


class MockTimelineEvent:
    """Mock timeline event for testing."""
    def __init__(self, event_type: str, timestamp: datetime, details: str = "", reported_result: str = "SUCCESS"):
        self.event_type = event_type
        self.timestamp = timestamp
        self.details = details
        self.reported_result = reported_result


class MockResourceTimeline:
    """Mock Phase 5 ResourceTimeline."""
    def __init__(
        self,
        resource_id: str,
        events: list = None,
        post_cutoff_events: list = None,
        deletion_attempts: list = None,
        latest_admissible_evidence_id: str = "",
    ):
        self.resource_id = resource_id
        self.events = events or []
        self.post_cutoff_events = post_cutoff_events or []
        self.deletion_attempts = deletion_attempts or []
        self.latest_admissible_evidence_id = latest_admissible_evidence_id


class MockTimelineResult:
    """Mock Phase 5 TimelineReconstructionResult."""
    def __init__(
        self,
        resources: dict = None,
        recreation_findings: list = None,
        failed_attempts: list = None,
    ):
        self.resources = resources or {}
        self.recreation_findings = recreation_findings or []
        self.failed_attempts = failed_attempts or []


class TestRecreationRiskAssessor(unittest.TestCase):
    """Test suite for RecreationRiskAssessor."""

    @classmethod
    def setUpClass(cls):
        cls.assessor = RecreationRiskAssessor()
        cls.audit_cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Active synchronization data flow detected (REPORT_ACTIVE_DATA_FLOW)
    def test_01_active_data_flow_detected(self):
        d_flow = ResourceTreatmentDecision(
            resource_id="data_flow_9522",
            system_id="integration_service",
            data_category="DATA_FLOW",
            rule_id=None,
            required_action=None,
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Active sync process can copy user data",
            evidence_id="evidence_03",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_11",
            user_id="usr_11",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_flow],
            decisions_by_resource={"data_flow_9522": d_flow},
            active_data_flows=[{"resource_id": "data_flow_9522", "system_id": "integration_service", "evidence_id": "evidence_03"}],
        )
        res = self.assessor.assess_risks(pol_res)

        self.assertTrue(res.has_active_risks)
        self.assertEqual(res.active_flows_count, 1)
        finding = res.findings_by_resource["data_flow_9522"]
        self.assertEqual(finding.risk_type, "REPORT_ACTIVE_DATA_FLOW")
        self.assertEqual(finding.observed_state, "ACTIVE")
        self.assertEqual(finding.remediation_operation, "DISABLE_DATA_FLOW")
        self.assertEqual(finding.verification_operation, "VERIFY_DATA_FLOW_DISABLED")
        self.assertEqual(finding.evidence_id, "evidence_03")

    # 2. Disabled data flow is verified compliant (not an active risk)
    def test_02_disabled_data_flow_compliant(self):
        d_disabled = ResourceTreatmentDecision(
            resource_id="data_flow_6244",
            system_id="integration_service",
            data_category="DATA_FLOW",
            rule_id=None,
            required_action=None,
            observed_state="DISABLED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Data flow verified disabled",
            evidence_id="evidence_92",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_26",
            user_id="usr_26",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_disabled],
            decisions_by_resource={"data_flow_6244": d_disabled},
            active_data_flows=[],
        )
        res = self.assessor.assess_risks(pol_res)

        self.assertFalse(res.has_active_risks)
        self.assertEqual(res.active_flows_count, 0)
        self.assertEqual(res.total_risk_findings, 0)

    # 3. Active restore risk on backup archive detected (REPORT_RESTORE_RISK)
    def test_03_active_restore_risk_detected(self):
        d_backup = ResourceTreatmentDecision(
            resource_id="backup_4978",
            system_id="backup_service",
            data_category="BACKUP_ARCHIVE",
            rule_id="rule_14",
            required_action="RETAIN",
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Backup archive restore access is active",
            evidence_id="evidence_93",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_09",
            user_id="usr_09",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_backup],
            decisions_by_resource={"backup_4978": d_backup},
            restore_risks=[{"resource_id": "backup_4978", "system_id": "backup_service", "evidence_id": "evidence_93"}],
        )
        res = self.assessor.assess_risks(pol_res)

        self.assertTrue(res.has_active_risks)
        self.assertEqual(res.restore_risks_count, 1)
        finding = res.findings_by_resource["backup_4978"]
        self.assertEqual(finding.risk_type, "REPORT_RESTORE_RISK")
        self.assertEqual(finding.observed_state, "ACTIVE")
        self.assertEqual(finding.remediation_operation, "BLOCK_RESTORE")
        self.assertEqual(finding.verification_operation, "VERIFY_RESTORE_BLOCKED")
        self.assertEqual(finding.evidence_id, "evidence_93")

    # 4. Blocked backup archive is compliant per rule_14 (not an active risk)
    def test_04_blocked_backup_archive_compliant(self):
        d_blocked = ResourceTreatmentDecision(
            resource_id="backup_3120",
            system_id="backup_service",
            data_category="BACKUP_ARCHIVE",
            rule_id="rule_14",
            required_action="RETAIN",
            observed_state="BLOCKED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Restore access blocked",
            evidence_id="evidence_92",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_26",
            user_id="usr_26",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_blocked],
            decisions_by_resource={"backup_3120": d_blocked},
            restore_risks=[],
        )
        res = self.assessor.assess_risks(pol_res)

        self.assertFalse(res.has_active_risks)
        self.assertEqual(res.restore_risks_count, 0)
        self.assertIn("backup_3120", res.blocked_backups_compliant)

    # 5. Failed restoration attempt does not prove data was restored
    def test_05_failed_restoration_attempt_not_restored(self):
        mock_timeline = MockResourceTimeline(
            resource_id="backup_failed_arc",
            deletion_attempts=[{"event_type": "RESTORE_BACKUP", "reported_result": "FAILED"}],
        )
        mock_tl_res = MockTimelineResult(
            resources={"backup_failed_arc": mock_timeline},
            failed_attempts=[{"event_type": "RESTORE_BACKUP", "reported_result": "FAILED"}],
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_fail_rec",
            user_id="usr_fail",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[],
            decisions_by_resource={},
            restore_risks=[],
        )
        res = self.assessor.assess_risks(pol_res, timeline_result=mock_tl_res)

        # A failed restore attempt must not be treated as a successful restore or active risk
        self.assertFalse(res.has_active_risks)
        self.assertEqual(res.restore_risks_count, 0)
        self.assertTrue(len(res.failed_restores_verified_unrestored) > 0)

    # 6. Pre-cutoff recreation event detected and correlated
    def test_06_pre_cutoff_recreation_event(self):
        mock_tl_res = MockTimelineResult(
            recreation_findings=[
                {
                    "resource_id": "account_recreated",
                    "system_id": "sync_service",
                    "data_category": "USER_PROFILE",
                    "event_type": "SYNC_RECORD",
                    "evidence_id": "evidence_sync_01",
                }
            ]
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_rec",
            user_id="usr_rec",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[],
            decisions_by_resource={},
        )
        res = self.assessor.assess_risks(pol_res, timeline_result=mock_tl_res)

        self.assertTrue(res.has_active_risks)
        self.assertEqual(res.recreation_count, 1)
        rec_finding = res.findings_by_resource["account_recreated"]
        self.assertEqual(rec_finding.risk_type, "RECREATION_EVENT")
        self.assertTrue(rec_finding.is_pre_cutoff)

    # 7. Post-cutoff events excluded from cutoff decisions
    def test_07_post_cutoff_events_excluded(self):
        post_event = MockTimelineEvent(
            event_type="SYNC_RECORD",
            timestamp=datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc),
            details="Sync occurred one month after cutoff",
        )
        mock_timeline = MockResourceTimeline(
            resource_id="account_001",
            post_cutoff_events=[post_event],
        )
        mock_tl_res = MockTimelineResult(
            resources={"account_001": mock_timeline},
        )
        d_clean = ResourceTreatmentDecision(
            resource_id="account_001",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Record was absent at cutoff",
            evidence_id="evidence_54",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_post",
            user_id="usr_post",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_clean],
            decisions_by_resource={"account_001": d_clean},
        )
        res = self.assessor.assess_risks(pol_res, timeline_result=mock_tl_res)

        # Future recreation event does NOT retroactively make cutoff decision an active risk
        self.assertFalse(res.has_active_risks)
        self.assertEqual(res.total_risk_findings, 0)
        self.assertEqual(len(res.post_cutoff_events_excluded), 1)

    # 8. Replica drift surfaced as active risk
    def test_08_replica_drift_surfaced(self):
        pol_res = CasePolicyEvaluationResult(
            case_id="case_drift",
            user_id="usr_drift",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[],
            decisions_by_resource={},
            replica_drift_findings=[
                {
                    "resource_id": "account_replica_01",
                    "system_id": "account_service_replica",
                    "data_category": "USER_PROFILE",
                    "evidence_id": "evidence_rep_01",
                }
            ],
        )
        res = self.assessor.assess_risks(pol_res)

        self.assertTrue(res.has_active_risks)
        self.assertEqual(res.replica_drift_count, 1)
        drift = res.findings_by_resource["account_replica_01"]
        self.assertEqual(drift.risk_type, "REPLICA_DRIFT")
        self.assertEqual(drift.evidence_id, "evidence_rep_01")

    # 9. Deterministic ordering: REPORT_ACTIVE_DATA_FLOW before REPORT_RESTORE_RISK
    def test_09_deterministic_ordering(self):
        d_risk = ResourceTreatmentDecision(
            resource_id="backup_001",
            system_id="backup_service",
            data_category="BACKUP_ARCHIVE",
            rule_id="rule_14",
            required_action="RETAIN",
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Active restore",
            evidence_id="evidence_bak",
        )
        d_flow = ResourceTreatmentDecision(
            resource_id="data_flow_001",
            system_id="integration_service",
            data_category="DATA_FLOW",
            rule_id=None,
            required_action=None,
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Active flow",
            evidence_id="evidence_flow",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_order",
            user_id="usr_ord",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_risk, d_flow],
            decisions_by_resource={"backup_001": d_risk, "data_flow_001": d_flow},
            active_data_flows=[{"resource_id": "data_flow_001", "system_id": "integration_service", "evidence_id": "evidence_flow"}],
            restore_risks=[{"resource_id": "backup_001", "system_id": "backup_service", "evidence_id": "evidence_bak"}],
        )
        res = self.assessor.assess_risks(pol_res)

        self.assertEqual(res.total_risk_findings, 2)
        # Order: REPORT_ACTIVE_DATA_FLOW before REPORT_RESTORE_RISK
        self.assertEqual(res.findings[0].risk_type, "REPORT_ACTIVE_DATA_FLOW")
        self.assertEqual(res.findings[1].risk_type, "REPORT_RESTORE_RISK")

    # 10. Repeat-run determinism across 50 iterations
    def test_10_repeat_run_determinism(self):
        d_flow = ResourceTreatmentDecision(
            resource_id="data_flow_001",
            system_id="integration_service",
            data_category="DATA_FLOW",
            rule_id=None,
            required_action=None,
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Active flow",
            evidence_id="evidence_flow",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_det",
            user_id="usr_det",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_flow],
            decisions_by_resource={"data_flow_001": d_flow},
            active_data_flows=[{"resource_id": "data_flow_001", "system_id": "integration_service", "evidence_id": "evidence_flow"}],
        )
        first = self.assessor.assess_risks(pol_res)
        for _ in range(50):
            subsequent = self.assessor.assess_risks(pol_res)
            self.assertEqual(first.has_active_risks, subsequent.has_active_risks)
            self.assertEqual(first.total_risk_findings, subsequent.total_risk_findings)
            self.assertEqual([f.resource_id for f in first.findings], [f.resource_id for f in subsequent.findings])
            self.assertEqual([f.risk_type for f in first.findings], [f.risk_type for f in subsequent.findings])


if __name__ == "__main__":
    unittest.main()

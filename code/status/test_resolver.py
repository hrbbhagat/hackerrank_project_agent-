"""Phase 7.6 Unit and Integration Tests: Central Case Status Resolver.

Tests:
1. Pure COMPLETE case where all obligations are proven satisfied by admissible evidence.
2. Pure NOT_APPLICABLE case where request text does not authorize deletion.
3. NOT_APPLICABLE precedence: non-deletion request text preserves NOT_APPLICABLE even if violations exist.
4. INCOMPLETE due to remaining prohibited record (REPORT_REMAINING_RECORD).
5. INCOMPLETE due to exposed direct PII in tombstone (REPORT_EXPOSED_PII).
6. COMPLETE with legitimate retention (SECURITY_AUDIT_LOG) and compliant tombstone.
7. INCOMPLETE due to active data flow risk (REPORT_ACTIVE_DATA_FLOW).
8. INCOMPLETE due to unblocked backup archive restore risk (REPORT_RESTORE_RISK).
9. COMPLETE with blocked restore backup (rule_14 compliant).
10. INCOMPLETE due to replica drift (unpurged replica copy).
11. INCOMPLETE with mixed resources (single compliant cannot mask non-compliant).
12. INCOMPLETE due to indeterminate / missing evidence (never equates uncertainty with success).
13. INCOMPLETE due to contradictory evidence observations.
14. INCOMPLETE due to zero resources evaluated baseline.
15. Reported status workflow claim does not override actual admissible evidence.
16. Post-cutoff events excluded from pre-cutoff status determination.
17. Determinism: identical normalized inputs produce identical decisions over 50 iterations.
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
        CaseStatusResult,
        DeletionStatus,
        RequestIntentCategory,
    )
    from .resolver import CaseStatusResolver
except ImportError:
    from models import (
        CaseStatusResult,
        DeletionStatus,
        RequestIntentCategory,
    )
    from resolver import CaseStatusResolver

from engine import (
    ComplianceResult,
    ResourceTreatmentDecision,
)
from service import CasePolicyEvaluationResult
from mapper import (
    PolicyOperationBundle,
    OperationSpec,
    StepPhase,
    StepOperation,
    StepState,
)


class MockTimelineEvent:
    """Mock Phase 5 TimelineEvent."""
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


class TestCaseStatusResolver(unittest.TestCase):
    """Test suite for CaseStatusResolver adhering to the Phase 7 decision table."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = CaseStatusResolver()
        cls.audit_cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Pure COMPLETE Case
    def test_01_pure_complete_case_all_obligations_satisfied(self):
        req = {
            "case_id": "case_01",
            "request_text": "Please delete all my personal data and close my account permanently.",
            "email": "user01@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_001",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Account deleted cleanly.",
            evidence_id="evidence_file_01",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="ticket_001",
            system_id="support_service",
            data_category="CUSTOMER_SUPPORT_TICKET",
            required_action="DELETE",
            rule_id="rule_02",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Ticket deleted cleanly.",
            evidence_id="evidence_file_02",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_01",
            user_id="user_01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        self.assertTrue(res.is_complete)
        self.assertFalse(res.is_incomplete)
        self.assertFalse(res.is_not_applicable)
        self.assertEqual(res.resolution_status, "VERIFIED_COMPLETE")
        self.assertIn("verified compliant", res.reason)

    # 2. Pure NOT_APPLICABLE Case (Non-deletion request)
    def test_02_pure_not_applicable_non_deletion_request(self):
        req = {
            "case_id": "case_02",
            "request_text": "I would like an export of my account data under GDPR data portability.",
            "email": "user02@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        policy_res = CasePolicyEvaluationResult(
            case_id="case_02",
            user_id="user_02",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=True,
            resolution_status="NOT_APPLICABLE",
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE)
        self.assertTrue(res.is_not_applicable)
        self.assertFalse(res.is_complete)
        self.assertEqual(res.resolution_status, "NOT_APPLICABLE")
        self.assertIn("does not authorize deletion", res.reason)

    # 3. NOT_APPLICABLE Precedence over Observed Violations
    def test_03_not_applicable_precedence_over_violations(self):
        req = {
            "case_id": "case_03",
            "request_text": "Please unsubscribe me from marketing emails and newsletter updates.",
            "email": "user03@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="marketing_001",
            system_id="marketing_service",
            data_category="MARKETING_PREFERENCES",
            required_action="DELETE",
            rule_id="rule_04",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Record still present.",
            evidence_id="evidence_file_03",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_03",
            user_id="user_03",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE)
        self.assertTrue(res.is_not_applicable)
        self.assertEqual(res.applicability.intent_category, RequestIntentCategory.NON_DELETION_OPT_OUT)

    # 4. INCOMPLETE due to Remaining Prohibited Record
    def test_04_incomplete_due_to_remaining_prohibited_record(self):
        req = {
            "case_id": "case_04",
            "request_text": "Please erase my profile and all associated data.",
            "email": "user04@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_004",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Account record still present in database.",
            evidence_id="evidence_file_04",
        )
        bundle1 = PolicyOperationBundle(
            resource_id="account_004",
            system_id="account_service",
            data_category="USER_PROFILE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            findings=[
                OperationSpec(
                    phase=StepPhase.FINDING,
                    operation=StepOperation.REPORT_REMAINING_RECORD,
                    system_id="account_service",
                    resource_id="account_004",
                    state=StepState.PRESENT,
                    evidence_id="evidence_file_04",
                )
            ],
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_04",
            user_id="user_04",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            operation_bundles=[bundle1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertTrue(res.is_incomplete)
        self.assertEqual(res.resolution_status, "VIOLATION_PRESENT")
        self.assertIn("prohibited record(s) remain present", res.reason)

    # 5. INCOMPLETE due to Exposed Direct PII in Tombstone
    def test_05_incomplete_due_to_exposed_direct_pii_in_tombstone(self):
        req = {
            "case_id": "case_05",
            "request_text": "Please delete my account under GDPR Article 17.",
            "email": "user05@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_005",
            system_id="account_service",
            data_category="ACCOUNT_TOMBSTONE",
            required_action="REDACT",
            rule_id="rule_15",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Tombstone retains cleartext email and phone.",
            evidence_id="evidence_file_05",
        )
        bundle1 = PolicyOperationBundle(
            resource_id="account_005",
            system_id="account_service",
            data_category="ACCOUNT_TOMBSTONE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            findings=[
                OperationSpec(
                    phase=StepPhase.FINDING,
                    operation=StepOperation.REPORT_EXPOSED_PII,
                    system_id="account_service",
                    resource_id="account_005",
                    state=StepState.PRESENT,
                    evidence_id="evidence_file_05",
                )
            ],
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_05",
            user_id="user_05",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            operation_bundles=[bundle1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "VIOLATION_PRESENT")
        self.assertIn("exposed direct PII", res.reason)

    # 6. COMPLETE with Legitimate Retention and Compliant Tombstone
    def test_06_complete_with_legitimate_retention_and_compliant_tombstone(self):
        req = {
            "case_id": "case_06",
            "request_text": "Please delete my profile and forget my data.",
            "email": "user06@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_006",
            system_id="account_service",
            data_category="ACCOUNT_TOMBSTONE",
            required_action="REDACT",
            rule_id="rule_15",
            observed_state="REDACTED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Compliant tombstone: direct PII removed, internal ID retained.",
            evidence_id="ev_tombstone",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="audit_log_006",
            system_id="audit_service",
            data_category="SECURITY_AUDIT_LOG",
            required_action="RETAIN",
            rule_id="rule_12",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Legitimate retention for security audit log.",
            evidence_id="ev_audit",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_06",
            user_id="user_06",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        self.assertTrue(res.is_complete)
        self.assertEqual(res.resolution_status, "VERIFIED_COMPLETE")
        self.assertIn("legitimately retained / tombstoned resource(s)", res.reason)

    # 7. INCOMPLETE due to Active Data Flow Risk
    def test_07_incomplete_due_to_active_data_flow(self):
        req = {
            "case_id": "case_07",
            "request_text": "Please erase all my personal information.",
            "email": "user07@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_007",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Cleanly deleted.",
            evidence_id="ev_07",
        )
        d_flow = ResourceTreatmentDecision(
            resource_id="data_flow_9522",
            system_id="integration_service",
            data_category="DATA_FLOW",
            rule_id=None,
            required_action=None,
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Active sync process can copy user data",
            evidence_id="ev_flow_07",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_07",
            user_id="user_07",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d_flow],
            decisions_by_resource={"account_007": d1, "data_flow_9522": d_flow},
            active_data_flows=[{"resource_id": "data_flow_9522", "system_id": "integration_service", "evidence_id": "ev_flow_07"}],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "ACTIVE_RISK_PRESENT")
        self.assertIn("active data flow", res.reason)

    # 8. INCOMPLETE due to Unblocked Backup Archive Restore Risk
    def test_08_incomplete_due_to_unblocked_restore_risk(self):
        req = {
            "case_id": "case_08",
            "request_text": "Please delete all personal records.",
            "email": "user08@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_008",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_08",
        )
        d_backup = ResourceTreatmentDecision(
            resource_id="backup_4978",
            system_id="backup_service",
            data_category="BACKUP_ARCHIVE",
            rule_id="rule_14",
            required_action="RETAIN",
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Backup archive restore access is active",
            evidence_id="ev_backup_08",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_08",
            user_id="user_08",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d_backup],
            decisions_by_resource={"account_008": d1, "backup_4978": d_backup},
            restore_risks=[{"resource_id": "backup_4978", "system_id": "backup_service", "evidence_id": "ev_backup_08"}],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "ACTIVE_RISK_PRESENT")
        self.assertIn("restore risk", res.reason)

    # 9. COMPLETE with Blocked Restore Backup (rule_14 compliant)
    def test_09_complete_with_blocked_restore_backup(self):
        req = {
            "case_id": "case_09",
            "request_text": "Please delete all personal data.",
            "email": "user09@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_009",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Cleanly deleted.",
            evidence_id="ev_09",
        )
        d_blocked = ResourceTreatmentDecision(
            resource_id="backup_3120",
            system_id="backup_service",
            data_category="BACKUP_ARCHIVE",
            rule_id="rule_14",
            required_action="RETAIN",
            observed_state="BLOCKED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Restore access blocked",
            evidence_id="ev_backup_09",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_09",
            user_id="user_09",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d_blocked],
            decisions_by_resource={"account_009": d1, "backup_3120": d_blocked},
            restore_risks=[],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        self.assertTrue(res.is_complete)

    # 10. INCOMPLETE due to Replica Drift
    def test_10_incomplete_due_to_replica_drift(self):
        req = {
            "case_id": "case_10",
            "request_text": "Please delete all my account records.",
            "email": "user10@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="primary_account_010",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted on primary.",
            evidence_id="ev_primary",
        )
        drift = {
            "system_id": "analytics_replica",
            "resource_id": "replica_account_010",
            "data_category": "USER_PROFILE",
            "operation": "REPORT_REMAINING_RECORD",
            "evidence_id": "ev_replica",
            "reason": "Read replica retains copy after primary deletion.",
        }
        policy_res = CasePolicyEvaluationResult(
            case_id="case_10",
            user_id="user_10",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            replica_drift_findings=[drift],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "VIOLATION_PRESENT")
        self.assertIn("replica drift", res.reason)

    # 11. INCOMPLETE with Mixed Resources (Single compliant cannot mask violation)
    def test_11_incomplete_mixed_resources_single_compliant_cannot_mask(self):
        req = {
            "case_id": "case_11",
            "request_text": "Please erase all my records completely.",
            "email": "user11@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="res_01",
            system_id="sys_1",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_01",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="res_02",
            system_id="sys_2",
            data_category="CUSTOMER_SUPPORT_TICKET",
            required_action="DELETE",
            rule_id="rule_02",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_02",
        )
        d3 = ResourceTreatmentDecision(
            resource_id="res_03",
            system_id="sys_3",
            data_category="MARKETING_PREFERENCES",
            required_action="DELETE",
            rule_id="rule_03",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_03",
        )
        d4 = ResourceTreatmentDecision(
            resource_id="res_04",
            system_id="sys_4",
            data_category="SEARCH_INDEX_ENTRY",
            required_action="DELETE",
            rule_id="rule_05",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Search index entry remains present.",
            evidence_id="ev_04",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_11",
            user_id="user_11",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2, d3, d4],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "VIOLATION_PRESENT")

    # 12. INCOMPLETE due to Indeterminate / Missing Evidence
    def test_12_incomplete_due_to_indeterminate_missing_evidence(self):
        req = {
            "case_id": "case_12",
            "request_text": "Please delete my account data.",
            "email": "user12@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="res_01",
            system_id="sys_1",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_01",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="res_02",
            system_id="sys_2",
            data_category="CUSTOMER_SUPPORT_TICKET",
            required_action="DELETE",
            rule_id="rule_02",
            observed_state="INDETERMINATE",
            compliance_result=ComplianceResult.INDETERMINATE,
            reason="No admissible evidence proving ticket was purged.",
            evidence_id=None,
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_12",
            user_id="user_12",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "INDETERMINATE_EVIDENCE")
        self.assertIn("does not equate uncertainty with compliance", res.reason)

    # 13. INCOMPLETE due to Contradictory Evidence
    def test_13_incomplete_due_to_contradictory_evidence(self):
        req = {
            "case_id": "case_13",
            "request_text": "Please delete my account.",
            "email": "user13@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="res_01",
            system_id="sys_1",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Log says deleted.",
            evidence_id="ev_01",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_13",
            user_id="user_13",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            contradictions=["Activity log says deleted, but storage snapshot confirms presence."],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "INDETERMINATE_EVIDENCE")
        self.assertIn("contradictory evidence observation(s)", res.reason)

    # 14. INCOMPLETE due to Zero Resources Found (Baseline check)
    def test_14_incomplete_due_to_zero_resources(self):
        req = {
            "case_id": "case_14",
            "request_text": "Please delete everything.",
            "email": "user14@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        policy_res = CasePolicyEvaluationResult(
            case_id="case_14",
            user_id="user_14",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "NO_RESOURCES_FOUND")
        self.assertIn("Zero resources were identified", res.reason)

    # 15. Reported Status Workflow Claim Does Not Override Evidence
    def test_15_reported_status_claim_does_not_override_evidence(self):
        req = {
            "case_id": "case_15",
            "request_text": "Please delete my account.",
            "email": "user15@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_015",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Record still present in database despite reported status COMPLETE.",
            evidence_id="ev_db",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_15",
            user_id="user_15",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)

    # 16. Post-Cutoff Events Excluded from Pre-Cutoff Determination
    def test_16_post_cutoff_events_excluded(self):
        req = {
            "case_id": "case_16",
            "request_text": "Please delete my account.",
            "email": "user16@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_016",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Cleanly deleted.",
            evidence_id="ev_16",
        )
        post_event = MockTimelineEvent(
            event_type="SYNC_RECORD",
            timestamp=datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc),
            details="Sync occurred one month after cutoff",
        )
        mock_timeline = MockResourceTimeline(
            resource_id="account_016",
            post_cutoff_events=[post_event],
        )
        mock_tl_res = MockTimelineResult(
            resources={"account_016": mock_timeline},
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_16",
            user_id="user_16",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res, timeline_result=mock_tl_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        self.assertIn("exceeds audit cutoff", res.risk_assessment.post_cutoff_events_excluded[0])

    # 17. Determinism across 50 Repeated Runs
    def test_17_repeat_run_determinism(self):
        req = {
            "case_id": "case_17",
            "request_text": "Please delete all my personal information.",
            "email": "user17@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "PARTIALLY_COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_017",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Account still present.",
            evidence_id="ev_17",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_17",
            user_id="user_17",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        base_res = self.resolver.resolve_case_status(req, policy_res)
        for _ in range(50):
            run_res = self.resolver.resolve_case_status(req, policy_res)
            self.assertEqual(run_res.deletion_status, base_res.deletion_status)
            self.assertEqual(run_res.resolution_status, base_res.resolution_status)
            self.assertEqual(run_res.reason, base_res.reason)


if __name__ == "__main__":
    unittest.main()

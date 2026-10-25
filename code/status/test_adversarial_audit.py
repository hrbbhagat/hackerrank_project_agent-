"""Phase 7.8 Adversarial and Comprehensive Stress Test Suite.

Performs rigorous adversarial validation of Phase 7 case-status resolution:
1. Operational workflow claims contradiction (reported COMPLETE vs empirical violation).
2. Non-deletion requests that must NEVER produce COMPLETE or INCOMPLETE (GDPR portability, opt-out, rectification, help, empty).
3. Mixed resource dominance (9 compliant + 1 non-compliant -> INCOMPLETE).
4. Missing evidence without observed violation -> INCOMPLETE (never silently equates uncertainty with success).
5. Conflicting observations for the same resource -> INCOMPLETE with explicit contradiction trace.
6. Post-cutoff recreation invariance -> historical status at cutoff preserved.
7. Replica drift detection across primary vs read-replicas.
8. Active data sync flow recreation risk.
9. Backup restoration risk: unblocked vs rule_14 blocked archive.
10. Account tombstone treatment: compliant (internal ID kept, direct PII stripped) vs non-compliant (exposed PII).
11. Mandatory retention exceptions (SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD).
12. Duplicate evidence references and repeated sighting deduplication.
13. Malformed and edge-case inputs resiliency.
14. Repeat-run determinism under multi-factor stress.
"""

from pathlib import Path
import json
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
        DecisionExplanation,
    )
    from .resolver import CaseStatusResolver
    from .explanation import sanitize_pii
except ImportError:
    from models import (
        CaseStatusResult,
        DeletionStatus,
        RequestIntentCategory,
        DecisionExplanation,
    )
    from resolver import CaseStatusResolver
    from explanation import sanitize_pii

from engine import (
    ComplianceResult,
    ResourceTreatmentDecision,
)
from service import CasePolicyEvaluationResult


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


class TestPhase7AdversarialAudit(unittest.TestCase):
    """Adversarial test suite challenging Phase 7 Case Status Resolver."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = CaseStatusResolver()
        cls.cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Workflow claims COMPLETE, but database snapshot shows record PRESENT
    def test_01_workflow_complete_claim_contradicted_by_evidence(self):
        req = {
            "case_id": "case_adv_01",
            "request_text": "Please delete my account and erase all associated data.",
            "email": "user01@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",  # Operational workflow claims full success
        }
        d1 = ResourceTreatmentDecision(
            resource_id="user_account_99",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",       # Empirical evidence catches unpurged record
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Record still present in database snapshot despite reported status COMPLETE.",
            evidence_id="evidence_db_snap_01",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_01",
            user_id="usr_adv_01",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertTrue(res.is_incomplete)
        self.assertFalse(res.is_complete)
        self.assertEqual(res.resolution_status, "VIOLATION_PRESENT")
        self.assertEqual(res.explanation.primary_deciding_factor, "RESIDUAL_PROHIBITED_RECORD")
        self.assertIn("evidence_db_snap_01", res.explanation.evidence_citations)

    # 2. Request was never for deletion: password reset or support help
    def test_02_non_deletion_support_help_never_incomplete_or_complete(self):
        req = {
            "case_id": "case_adv_02",
            "request_text": "Can't access my profile. Please help me resetting the login password.",
            "email": "lost_password@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        # Even if upstream erroneously generated an unpurged record finding
        d1 = ResourceTreatmentDecision(
            resource_id="account_lost",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Account exists.",
            evidence_id="ev_02",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_02",
            user_id="usr_02",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE)
        self.assertTrue(res.is_not_applicable)
        self.assertEqual(res.explanation.primary_deciding_factor, "REQUEST_NON_DELETION_INTENT")
        self.assertEqual(res.applicability.intent_category, RequestIntentCategory.NON_DELETION_SUPPORT_HELP)

    # 3. Request was never for deletion: explicit retention demand
    def test_03_explicit_account_retention_demand(self):
        req = {
            "case_id": "case_adv_03",
            "request_text": "Please keep my account open and active, do not close or delete it.",
            "email": "keep_me@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "NOT_STARTED",
        }
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_03",
            user_id="usr_03",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE)
        self.assertEqual(res.applicability.intent_category, RequestIntentCategory.NON_DELETION_ACCOUNT_RETENTION)

    # 4. Mixed resources dominance: 9 compliant resources + 1 non-compliant resource
    def test_04_mixed_resources_single_non_compliant_forces_incomplete(self):
        req = {
            "case_id": "case_adv_04",
            "request_text": "Please erase all my data completely.",
            "email": "user04@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "PARTIALLY_COMPLETE",
        }
        decisions = []
        # 9 compliant resources
        for i in range(1, 10):
            decisions.append(
                ResourceTreatmentDecision(
                    resource_id=f"clean_record_{i:02d}",
                    system_id=f"service_{i:02d}",
                    data_category="USER_PROFILE",
                    required_action="DELETE",
                    rule_id="rule_01",
                    observed_state="ABSENT",
                    compliance_result=ComplianceResult.COMPLIANT,
                    reason=f"Resource {i} deleted cleanly.",
                    evidence_id=f"ev_clean_{i:02d}",
                )
            )
        # 1 non-compliant resource (e.g. search index entry remaining)
        decisions.append(
            ResourceTreatmentDecision(
                resource_id="search_index_bad",
                system_id="search_service",
                data_category="SEARCH_INDEX_ENTRY",
                required_action="DELETE",
                rule_id="rule_05",
                observed_state="PRESENT",
                compliance_result=ComplianceResult.NON_COMPLIANT,
                reason="Search index entry remains indexed.",
                evidence_id="ev_search_bad",
            )
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_04",
            user_id="usr_04",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=decisions,
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertTrue(res.is_incomplete)
        self.assertEqual(res.resolution_status, "VIOLATION_PRESENT")
        self.assertEqual(res.resource_aggregation.total_resources, 10)
        self.assertEqual(len(res.resource_aggregation.compliant_resources), 9)
        self.assertEqual(len(res.resource_aggregation.non_compliant_resources), 1)

    # 5. Missing evidence without observed violation -> INCOMPLETE (no silent success)
    def test_05_missing_evidence_without_violation_forces_incomplete(self):
        req = {
            "case_id": "case_adv_05",
            "request_text": "Please delete my account data.",
            "email": "user05@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        # Resource is claimed deleted, but evidence is completely absent / indeterminate
        d1 = ResourceTreatmentDecision(
            resource_id="account_unverified",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="INDETERMINATE",
            compliance_result=ComplianceResult.INDETERMINATE,
            reason="No admissible evidence captured proving that the record was removed.",
            evidence_id=None,
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_05",
            user_id="usr_05",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "INDETERMINATE_EVIDENCE")
        self.assertEqual(res.explanation.primary_deciding_factor, "INSUFFICIENT_VERIFICATION_EVIDENCE")

    # 6. Conflicting observations for the same resource
    def test_06_conflicting_observations_forces_incomplete(self):
        req = {
            "case_id": "case_adv_06",
            "request_text": "Please delete all my details.",
            "email": "user06@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="profile_contradicted",
            system_id="profile_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Service log indicates deletion success.",
            evidence_id="ev_log_06",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_06",
            user_id="usr_06",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            contradictions=["Service log reports ABSENT at 10:00, but SQL export demonstrates PRESENT at 11:30."],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "INDETERMINATE_EVIDENCE")
        self.assertEqual(res.explanation.primary_deciding_factor, "CONTRADICTORY_EVIDENCE_CONFLICT")
        self.assertTrue(len(res.explanation.unresolved_uncertainties) >= 1)

    # 7. Post-cutoff recreation invariance
    def test_07_post_cutoff_recreation_invariance(self):
        req = {
            "case_id": "case_adv_07",
            "request_text": "Please purge all my records.",
            "email": "user07@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_clean",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted on primary before cutoff.",
            evidence_id="ev_pre_07",
        )
        # Event occurs 30 days AFTER cutoff
        post_event = MockTimelineEvent(
            event_type="RESTORE_BACKUP",
            timestamp=datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc),
            details="Backup restored 1 month after cutoff.",
        )
        mock_timeline = MockResourceTimeline(
            resource_id="account_clean",
            post_cutoff_events=[post_event],
        )
        mock_tl_res = MockTimelineResult(
            resources={"account_clean": mock_timeline},
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_07",
            user_id="usr_07",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res, timeline_result=mock_tl_res)
        # Must resolve to COMPLETE at cutoff time!
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        self.assertTrue(res.is_complete)
        self.assertEqual(len(res.risk_assessment.post_cutoff_events_excluded), 1)

    # 8. Replica drift detection
    def test_08_replica_drift_forces_incomplete(self):
        req = {
            "case_id": "case_adv_08",
            "request_text": "Please delete my account data.",
            "email": "user08@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="pg_primary_account",
            system_id="postgres_primary",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted on primary node.",
            evidence_id="ev_primary_08",
        )
        drift = {
            "system_id": "postgres_replica_analytics",
            "resource_id": "replica_account_08",
            "data_category": "USER_PROFILE",
            "operation": "REPORT_REMAINING_RECORD",
            "evidence_id": "ev_replica_08",
            "reason": "Replica lagged behind primary and retains copy.",
        }
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_08",
            user_id="usr_08",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            replica_drift_findings=[drift],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "VIOLATION_PRESENT")
        self.assertEqual(res.explanation.primary_deciding_factor, "REPLICA_DRIFT_UNPURGED")

    # 9. Active data sync flow recreation risk
    def test_09_active_data_flow_forces_incomplete(self):
        req = {
            "case_id": "case_adv_09",
            "request_text": "Please delete all personal data.",
            "email": "user09@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_09",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Cleanly deleted.",
            evidence_id="ev_09",
        )
        flow = {
            "system_id": "integration_hub",
            "resource_id": "sync_pipeline_8831",
            "data_category": "DATA_FLOW",
            "operation": "REPORT_ACTIVE_DATA_FLOW",
            "evidence_id": "ev_flow_09",
            "reason": "Active CRM sync pipeline can re-insert user data.",
            "timestamp": datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc),
        }
        policy_res = CasePolicyEvaluationResult(
            case_id="case_adv_09",
            user_id="usr_09",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            active_data_flows=[flow],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res.resolution_status, "ACTIVE_RISK_PRESENT")
        self.assertEqual(res.explanation.primary_deciding_factor, "ACTIVE_DATA_FLOW_RISK")

    # 10. Backup restoration risk: unblocked vs blocked archive
    def test_10_backup_restore_risk_unblocked_vs_blocked(self):
        req = {
            "case_id": "case_adv_10",
            "request_text": "Please delete all data.",
            "email": "user10@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_10",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_10",
        )
        # 10a: Unblocked backup -> INCOMPLETE
        unblocked = {
            "system_id": "backup_service",
            "resource_id": "backup_archive_unblocked",
            "data_category": "BACKUP_ARCHIVE",
            "operation": "REPORT_RESTORE_RISK",
            "evidence_id": "ev_backup_unblocked",
            "is_restore_blocked": False,
            "timestamp": datetime(2026, 5, 15, 0, 0, 0, tzinfo=timezone.utc),
        }
        policy_res_unblocked = CasePolicyEvaluationResult(
            case_id="case_adv_10",
            user_id="usr_10",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            restore_risks=[unblocked],
        )
        res_unblocked = self.resolver.resolve_case_status(req, policy_res_unblocked)
        self.assertEqual(res_unblocked.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res_unblocked.explanation.primary_deciding_factor, "UNBLOCKED_RESTORE_RISK")

        # 10b: Blocked backup (rule_14 compliant) -> COMPLETE
        blocked = {
            "system_id": "backup_service",
            "resource_id": "backup_archive_blocked",
            "data_category": "BACKUP_ARCHIVE",
            "operation": "REPORT_RESTORE_RISK",
            "evidence_id": "ev_backup_blocked",
            "is_restore_blocked": True,
            "timestamp": datetime(2026, 5, 15, 0, 0, 0, tzinfo=timezone.utc),
        }
        policy_res_blocked = CasePolicyEvaluationResult(
            case_id="case_adv_10",
            user_id="usr_10",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            restore_risks=[blocked],
        )
        res_blocked = self.resolver.resolve_case_status(req, policy_res_blocked)
        self.assertEqual(res_blocked.deletion_status, DeletionStatus.COMPLETE)
        self.assertTrue(res_blocked.is_complete)

    # 11. Account tombstone: compliant (direct PII stripped) vs non-compliant (exposed PII)
    def test_11_tombstone_direct_pii_redaction(self):
        req = {
            "case_id": "case_adv_11",
            "request_text": "Please delete my profile under GDPR Article 17.",
            "email": "tombstone@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        # 11a: Non-compliant tombstone (retains email)
        d_viol = ResourceTreatmentDecision(
            resource_id="tomb_viol",
            system_id="identity_service",
            data_category="ACCOUNT_TOMBSTONE",
            required_action="REDACT",
            rule_id="rule_15",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Tombstone retains cleartext email: tombstone@adv.org",
            evidence_id="ev_tomb_viol",
        )
        pol_viol = CasePolicyEvaluationResult(
            case_id="case_adv_11",
            user_id="usr_11",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_viol],
        )
        res_viol = self.resolver.resolve_case_status(req, pol_viol)
        self.assertEqual(res_viol.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertEqual(res_viol.explanation.primary_deciding_factor, "EXPOSED_DIRECT_PII")

        # 11b: Compliant tombstone (direct PII removed, stable user_id kept)
        d_comp = ResourceTreatmentDecision(
            resource_id="tomb_comp",
            system_id="identity_service",
            data_category="ACCOUNT_TOMBSTONE",
            required_action="REDACT",
            rule_id="rule_15",
            observed_state="REDACTED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Compliant tombstone: direct PII removed, stable reference kept.",
            evidence_id="ev_tomb_comp",
        )
        pol_comp = CasePolicyEvaluationResult(
            case_id="case_adv_11",
            user_id="usr_11",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_comp],
        )
        res_comp = self.resolver.resolve_case_status(req, pol_comp)
        self.assertEqual(res_comp.deletion_status, DeletionStatus.COMPLETE)

    # 12. Mandatory retention exceptions (SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD)
    def test_12_mandatory_retention_exceptions_compliant(self):
        req = {
            "case_id": "case_adv_12",
            "request_text": "Please delete my account.",
            "email": "retain@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d_del = ResourceTreatmentDecision(
            resource_id="account_12",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_del_12",
        )
        d_sec = ResourceTreatmentDecision(
            resource_id="sec_log_12",
            system_id="security_service",
            data_category="SECURITY_AUDIT_LOG",
            required_action="RETAIN",
            rule_id="rule_12",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Retained within legal compliance window.",
            evidence_id="ev_sec_12",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_adv_12",
            user_id="usr_12",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_del, d_sec],
        )
        res = self.resolver.resolve_case_status(req, pol_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        self.assertTrue(res.resource_aggregation.has_retained_data)
        self.assertIn("sec_log_12", res.resource_aggregation.retained_resources)

    # 13. Duplicate evidence references and repeated sighting deduplication
    def test_13_duplicate_evidence_deduplication(self):
        req = {
            "case_id": "case_adv_13",
            "request_text": "Please delete my account records.",
            "email": "dup@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        # Two resources sharing the same evidence snapshot
        d1 = ResourceTreatmentDecision(
            resource_id="acc_01",
            system_id="acc_sys",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="shared_evidence_54",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="acc_02",
            system_id="acc_sys",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="shared_evidence_54",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_adv_13",
            user_id="usr_13",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
        )
        res = self.resolver.resolve_case_status(req, pol_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        # Deduplicated citations
        self.assertEqual(res.explanation.evidence_citations, ["shared_evidence_54"])

    # 14. Malformed and empty inputs resiliency
    def test_14_malformed_and_empty_inputs(self):
        # Empty dict
        req_empty = {}
        pol_empty = CasePolicyEvaluationResult(
            case_id="",
            user_id=None,
            audit_at=None,
            is_non_deletion_request=False,
            resolution_status="UNRESOLVED",
            decisions=[],
        )
        res_empty = self.resolver.resolve_case_status(req_empty, pol_empty)
        self.assertEqual(res_empty.deletion_status, DeletionStatus.NOT_APPLICABLE)

        # Missing request_text with reported_status COMPLETE
        req_missing_text = {"case_id": "case_no_text", "reported_status": "COMPLETE"}
        res_missing = self.resolver.resolve_case_status(req_missing_text, pol_empty)
        self.assertEqual(res_missing.deletion_status, DeletionStatus.NOT_APPLICABLE)

    # 15. Stress determinism across 50 iterations with complex mixed inputs
    def test_15_stress_determinism_across_50_runs(self):
        req = {
            "case_id": "case_stress_15",
            "request_text": "Please delete all personal data and close my account.",
            "email": "stress@adv.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "PARTIALLY_COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="acc_01",
            system_id="acc_sys",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Deleted.",
            evidence_id="ev_01",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="acc_02",
            system_id="acc_sys",
            data_category="ACCOUNT_TOMBSTONE",
            required_action="REDACT",
            rule_id="rule_15",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Tombstone contains cleartext email.",
            evidence_id="ev_02",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_stress_15",
            user_id="usr_15",
            audit_at=self.cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
        )

        base_res = self.resolver.resolve_case_status(req, pol_res)
        base_dict = base_res.explanation.to_dict()
        base_status = base_res.deletion_status

        for _ in range(50):
            run_res = self.resolver.resolve_case_status(req, pol_res)
            self.assertEqual(run_res.deletion_status, base_status)
            self.assertEqual(run_res.explanation.to_dict(), base_dict)


if __name__ == "__main__":
    unittest.main()

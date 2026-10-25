"""Phase 7.7 Unit and Integration Tests: Decision Explanations and Evidence Traceability.

Tests:
1. Explanation completeness for COMPLETE status (all obligations satisfied with evidence).
2. Explanation completeness for INCOMPLETE status (residual record, exposed PII, active risk).
3. Explanation completeness for NOT_APPLICABLE status (request intent grounding, no fabricated findings).
4. Evidence-reference authenticity: citations contain only admissible participant-visible evidence IDs.
5. Missing references / indeterminate evidence cataloged under unresolved uncertainties.
6. Contradictory evidence preserved explicitly without concealment.
7. Post-cutoff evidence correctly excluded and never cited as proof of pre-cutoff state.
8. Linkage between decision, resource findings, and applicable policy rules.
9. PII sanitization in explanation texts and audit markdown.
10. Serialization and determinism: to_dict() and to_audit_markdown() stable across 50 iterations.
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
        EvidenceTrace,
        FindingExplanation,
        ContradictionTrace,
    )
    from .resolver import CaseStatusResolver
    from .explanation import DecisionExplanationBuilder, sanitize_pii
except ImportError:
    from models import (
        CaseStatusResult,
        DeletionStatus,
        RequestIntentCategory,
        DecisionExplanation,
        EvidenceTrace,
        FindingExplanation,
        ContradictionTrace,
    )
    from resolver import CaseStatusResolver
    from explanation import DecisionExplanationBuilder, sanitize_pii

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


class TestDecisionExplanationAndTraceability(unittest.TestCase):
    """Test suite for DecisionExplanationBuilder and evidence traceability."""

    @classmethod
    def setUpClass(cls):
        cls.resolver = CaseStatusResolver()
        cls.builder = DecisionExplanationBuilder()
        cls.audit_cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Explanation completeness for COMPLETE status
    def test_01_complete_status_explanation(self):
        req = {
            "case_id": "case_c01",
            "request_text": "Please delete all my personal data and close my account permanently.",
            "email": "user01@company.org",
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
            reason="Account cleanly deleted from database snapshot.",
            evidence_id="ev_sql_01",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="tombstone_001",
            system_id="identity_service",
            data_category="ACCOUNT_TOMBSTONE",
            required_action="REDACT",
            rule_id="rule_15",
            observed_state="REDACTED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Tombstone preserved with stable internal ID; cleartext direct PII redacted.",
            evidence_id="ev_tomb_01",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_c01",
            user_id="usr_01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        self.assertIsNotNone(res.explanation)

        exp = res.explanation
        self.assertEqual(exp.case_id, "case_c01")
        self.assertEqual(exp.deletion_status, DeletionStatus.COMPLETE)
        self.assertEqual(exp.primary_deciding_factor, "ALL_OBLIGATIONS_SATISFIED_WITH_COMPLIANT_RETENTION")
        self.assertEqual(exp.evidence_citations, ["ev_sql_01", "ev_tomb_01"])
        self.assertEqual(len(exp.direct_observations), 2)
        self.assertEqual(len(exp.policy_conclusions), 2)
        self.assertEqual(len(exp.unresolved_uncertainties), 0)

        # Markdown representation contains audit sections
        md = exp.to_audit_markdown()
        self.assertIn("Forensic Decision Audit: Case `case_c01`", md)
        self.assertIn("**Authoritative Status:** `COMPLETE`", md)
        self.assertIn("ev_sql_01", md)
        self.assertIn("ev_tomb_01", md)

    # 2. Explanation completeness for INCOMPLETE status (Residual records)
    def test_02_incomplete_status_explanation_residual_data(self):
        req = {
            "case_id": "case_inc01",
            "request_text": "Please delete all my account records.",
            "email": "victim@example.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_991",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Record remains present in customer database snapshot.",
            evidence_id="ev_db_snapshot",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_inc01",
            user_id="usr_inc01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        self.assertIsNotNone(res.explanation)

        exp = res.explanation
        self.assertEqual(exp.primary_deciding_factor, "RESIDUAL_PROHIBITED_RECORD")
        self.assertIn("Residual personal data remains present", exp.summary_reason)
        self.assertEqual(exp.evidence_citations, ["ev_db_snapshot"])

        # Check policy conclusion structure
        self.assertEqual(len(exp.policy_conclusions), 1)
        concl = exp.policy_conclusions[0]
        self.assertEqual(concl.finding_type, "REPORT_REMAINING_RECORD")
        self.assertEqual(concl.resource_id, "account_991")
        self.assertEqual(concl.system_id, "account_service")
        self.assertEqual(concl.nature, "POLICY_DERIVED_CONCLUSION")
        self.assertEqual(concl.evidence_id, "ev_db_snapshot")

    # 3. Explanation completeness for NOT_APPLICABLE status
    def test_03_not_applicable_explanation_grounding(self):
        req = {
            "case_id": "case_na01",
            "request_text": "I request a complete copy and export of my personal data under GDPR Article 20 data portability.",
            "email": "exporter@domain.com",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        policy_res = CasePolicyEvaluationResult(
            case_id="case_na01",
            user_id="usr_na01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=True,
            resolution_status="NOT_APPLICABLE",
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE)
        self.assertIsNotNone(res.explanation)

        exp = res.explanation
        self.assertEqual(exp.primary_deciding_factor, "REQUEST_NON_DELETION_INTENT")
        self.assertFalse(exp.applicability_summary["is_applicable"])
        self.assertEqual(exp.applicability_summary["intent_category"], "NON_DELETION_PORTABILITY")
        self.assertIn("data portability", exp.applicability_summary["detected_patterns"])
        self.assertEqual(len(exp.evidence_citations), 0)

    # 4. Evidence reference authenticity: citations never fabricate non-existent references
    def test_04_evidence_authenticity_no_fabrication(self):
        req = {
            "case_id": "case_auth01",
            "request_text": "Please delete my account profile.",
            "email": "user@test.org",
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
            reason="Cleanly deleted.",
            evidence_id="evidence_valid_101",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_auth01",
            user_id="usr_auth01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        exp = res.explanation
        # The citations must only contain evidence_valid_101
        self.assertEqual(exp.evidence_citations, ["evidence_valid_101"])
        for obs in exp.direct_observations:
            self.assertEqual(obs.evidence_id, "evidence_valid_101")

    # 5. Missing references & indeterminate evidence cataloged under unresolved uncertainties
    def test_05_missing_references_and_indeterminate_evidence(self):
        req = {
            "case_id": "case_indet01",
            "request_text": "Please delete my profile and logs.",
            "email": "user@sample.org",
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
            reason="Cleanly deleted.",
            evidence_id="ev_01",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="audit_log_99",
            system_id="audit_service",
            data_category="AUDIT_TRAIL",
            required_action="DELETE",
            rule_id="rule_03",
            observed_state="INDETERMINATE",
            compliance_result=ComplianceResult.INDETERMINATE,
            reason="Log retention cannot be confirmed; missing log export evidence.",
            evidence_id=None,
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_indet01",
            user_id="usr_indet01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        exp = res.explanation

        self.assertEqual(exp.primary_deciding_factor, "INSUFFICIENT_VERIFICATION_EVIDENCE")
        self.assertTrue(len(exp.unresolved_uncertainties) >= 1)
        uncertainty = [u for u in exp.unresolved_uncertainties if u.resource_id == "audit_log_99"][0]
        self.assertEqual(uncertainty.nature, "UNRESOLVED_UNCERTAINTY")
        self.assertIn("audit_log_99", uncertainty.conflicting_claims[0])

    # 6. Contradictory evidence explicitly preserved without concealment
    def test_06_contradictory_evidence_preservation(self):
        req = {
            "case_id": "case_contra01",
            "request_text": "Please delete my account.",
            "email": "user@contra.org",
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
            reason="Deleted.",
            evidence_id="ev_01",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_contra01",
            user_id="usr_contra01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
            contradictions=["Activity log confirms DELETE operation, but SQLite primary snapshot exhibits record presence."],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        self.assertEqual(res.deletion_status, DeletionStatus.INCOMPLETE)
        exp = res.explanation

        self.assertEqual(exp.primary_deciding_factor, "CONTRADICTORY_EVIDENCE_CONFLICT")
        self.assertTrue(len(exp.unresolved_uncertainties) >= 1)
        contra = exp.unresolved_uncertainties[0]
        self.assertIn("Activity log confirms DELETE operation", contra.conflicting_claims[0])
        self.assertIn("forces case status to INCOMPLETE", contra.impact)

    # 7. Post-cutoff evidence correctly excluded and never cited as proof of pre-cutoff state
    def test_07_post_cutoff_evidence_exclusion(self):
        req = {
            "case_id": "case_post01",
            "request_text": "Please delete my account.",
            "email": "user@post.org",
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
            reason="Cleanly deleted.",
            evidence_id="ev_pre_cutoff",
        )
        post_event = MockTimelineEvent(
            event_type="SYNC_RECORD",
            timestamp=datetime(2026, 7, 15, 0, 0, 0, tzinfo=timezone.utc),
            details="Replication synched 6 weeks after cutoff",
        )
        mock_timeline = MockResourceTimeline(
            resource_id="account_001",
            post_cutoff_events=[post_event],
        )
        mock_tl_res = MockTimelineResult(
            resources={"account_001": mock_timeline},
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_post01",
            user_id="usr_post01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res, timeline_result=mock_tl_res)
        self.assertEqual(res.deletion_status, DeletionStatus.COMPLETE)
        exp = res.explanation

        # Post-cutoff event must be in excluded_post_cutoff_items
        self.assertTrue(len(exp.excluded_post_cutoff_items) >= 1)
        self.assertIn("exceeds audit cutoff", exp.excluded_post_cutoff_items[0])
        # And evidence citations must only contain the pre-cutoff evidence
        self.assertEqual(exp.evidence_citations, ["ev_pre_cutoff"])

    # 8. Linkage between decision, resource findings, and applicable policy rules
    def test_08_finding_to_rule_linkage(self):
        req = {
            "case_id": "case_link01",
            "request_text": "Please erase my profile.",
            "email": "user@link.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="tombstone_77",
            system_id="identity_service",
            data_category="ACCOUNT_TOMBSTONE",
            required_action="REDACT",
            rule_id="rule_15",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Tombstone retains cleartext email.",
            evidence_id="ev_tomb_77",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_link01",
            user_id="usr_link01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        exp = res.explanation
        concl = exp.policy_conclusions[0]
        self.assertEqual(concl.resource_id, "tombstone_77")
        self.assertEqual(concl.system_id, "identity_service")
        self.assertEqual(concl.data_category, "ACCOUNT_TOMBSTONE")
        self.assertEqual(concl.rule_id, "rule_15")
        self.assertEqual(concl.evidence_id, "ev_tomb_77")

    # 9. PII sanitization in explanation texts and audit markdown
    def test_09_pii_sanitization(self):
        raw_text = "Contact user john.doe@secure-vault.com regarding account closure."
        sanitized = sanitize_pii(raw_text)
        self.assertNotIn("john.doe@secure-vault.com", sanitized)
        self.assertIn("j***@secure-vault.com", sanitized)

        # In complete explanation
        req = {
            "case_id": "case_pii01",
            "request_text": "Please delete data for alice.smith@confidential.net.",
            "email": "alice.smith@confidential.net",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_001",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Profile for alice.smith@confidential.net still active.",
            evidence_id="ev_sql_pii",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_pii01",
            user_id="usr_pii01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        res = self.resolver.resolve_case_status(req, policy_res)
        exp = res.explanation
        md = exp.to_audit_markdown()
        self.assertNotIn("alice.smith@confidential.net", md)
        self.assertIn("a***@confidential.net", md)

    # 10. Serialization and repeat-run determinism across 50 iterations
    def test_10_serialization_and_determinism(self):
        req = {
            "case_id": "case_det01",
            "request_text": "Please delete all my personal records.",
            "email": "user@det.org",
            "audit_at": "2026-06-01T12:00:00Z",
            "reported_status": "PARTIALLY_COMPLETE",
        }
        d1 = ResourceTreatmentDecision(
            resource_id="account_001",
            system_id="account_service",
            data_category="USER_PROFILE",
            required_action="DELETE",
            rule_id="rule_01",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Still present in database.",
            evidence_id="ev_01",
        )
        policy_res = CasePolicyEvaluationResult(
            case_id="case_det01",
            user_id="usr_det01",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1],
        )

        base_res = self.resolver.resolve_case_status(req, policy_res)
        base_dict = base_res.explanation.to_dict()
        base_md = base_res.explanation.to_audit_markdown()

        # Check JSON serializability
        serialized_json = json.dumps(base_dict, sort_keys=True)
        self.assertIsInstance(serialized_json, str)

        for _ in range(50):
            run_res = self.resolver.resolve_case_status(req, policy_res)
            self.assertEqual(run_res.explanation.to_dict(), base_dict)
            self.assertEqual(run_res.explanation.to_audit_markdown(), base_md)


if __name__ == "__main__":
    unittest.main()

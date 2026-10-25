"""Phase 7.4 Unit Tests: Remaining Data and Residual Violation Assessment.

Tests:
1. Prohibited record that remains present (USER_PROFILE -> REPORT_REMAINING_RECORD).
2. Legitimate retained record is not marked as violation (SECURITY_AUDIT_LOG).
3. Prohibited PII exposed in account tombstone (ACCOUNT_TOMBSTONE -> REPORT_EXPOSED_PII).
4. Compliant redacted and anonymized records produce zero residual findings.
5. Confirmed replica drift creates a REPORT_REMAINING_RECORD with is_replica_drift=True.
6. Deduplication of repeated evidence sightings for the same resource.
7. Missing state evidence / indeterminate records tracked in unverified_resources.
8. Deterministic ordering: REPORT_REMAINING_RECORD before REPORT_EXPOSED_PII, then system_id, resource_id.
9. Participant-visible evidence_id preservation.
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
        ResidualFinding,
        RemainingDataAssessmentResult,
    )
    from .remaining_data import RemainingDataAssessor
except ImportError:
    from models import (
        ResidualFinding,
        RemainingDataAssessmentResult,
    )
    from remaining_data import RemainingDataAssessor

from engine import ComplianceResult, ResourceTreatmentDecision
from service import CasePolicyEvaluationResult


class TestRemainingDataAssessor(unittest.TestCase):
    """Test suite for RemainingDataAssessor."""

    @classmethod
    def setUpClass(cls):
        cls.assessor = RemainingDataAssessor()
        cls.audit_cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Prohibited record remains present (REPORT_REMAINING_RECORD)
    def test_01_prohibited_record_remains_present(self):
        d_viol = ResourceTreatmentDecision(
            resource_id="account_005",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="User profile remains present in customer database",
            evidence_id="evidence_54",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_05",
            user_id="usr_05",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_viol],
            decisions_by_resource={"account_005": d_viol},
        )
        res = self.assessor.assess_remaining_data(pol_res)

        self.assertTrue(res.has_remaining_data)
        self.assertEqual(res.total_residual_findings, 1)
        self.assertEqual(res.remaining_record_count, 1)
        self.assertEqual(res.exposed_pii_count, 0)
        finding = res.findings[0]
        self.assertEqual(finding.finding_type, "REPORT_REMAINING_RECORD")
        self.assertEqual(finding.resource_id, "account_005")
        self.assertEqual(finding.system_id, "account_service")
        self.assertEqual(finding.observed_state, "PRESENT")
        self.assertEqual(finding.evidence_id, "evidence_54")

    # 2. Legitimate retained record is not marked as violation
    def test_02_legitimate_retained_data_not_violation(self):
        d_retained = ResourceTreatmentDecision(
            resource_id="audit_record_2016",
            system_id="security_service",
            data_category="SECURITY_AUDIT_LOG",
            rule_id="rule_12",
            required_action="RETAIN",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Within mandatory security retention window",
            evidence_id="evidence_94",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_retain",
            user_id="usr_retain",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_retained],
            decisions_by_resource={"audit_record_2016": d_retained},
        )
        res = self.assessor.assess_remaining_data(pol_res)

        self.assertFalse(res.has_remaining_data)
        self.assertEqual(res.total_residual_findings, 0)
        self.assertIn("audit_record_2016", res.legitimately_retained_resources)

    # 3. Prohibited PII exposed in account tombstone (REPORT_EXPOSED_PII)
    def test_03_prohibited_pii_in_tombstone(self):
        d_tomb_viol = ResourceTreatmentDecision(
            resource_id="tombstone_9178",
            system_id="identity_service",
            data_category="ACCOUNT_TOMBSTONE",
            rule_id="rule_15",
            required_action="REDACT",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Tombstone contains prohibited direct PII: name, email, phone",
            evidence_id="evidence_51",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_32",
            user_id="usr_32",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_tomb_viol],
            decisions_by_resource={"tombstone_9178": d_tomb_viol},
        )
        res = self.assessor.assess_remaining_data(pol_res)

        self.assertTrue(res.has_remaining_data)
        self.assertEqual(res.exposed_pii_count, 1)
        self.assertEqual(res.remaining_record_count, 0)
        finding = res.findings[0]
        self.assertEqual(finding.finding_type, "REPORT_EXPOSED_PII")
        self.assertEqual(finding.resource_id, "tombstone_9178")
        self.assertEqual(finding.system_id, "identity_service")
        self.assertEqual(finding.evidence_id, "evidence_51")
        self.assertIn("name", finding.exposed_fields)
        self.assertIn("email", finding.exposed_fields)

    # 4. Compliant redacted and anonymized records produce zero residual findings
    def test_04_compliant_redacted_and_anonymized(self):
        d_red = ResourceTreatmentDecision(
            resource_id="support_4715",
            system_id="support_platform",
            data_category="SUPPORT_MESSAGE",
            rule_id="rule_05",
            required_action="REDACT",
            observed_state="REDACTED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="PII redacted from support conversation",
            evidence_id="evidence_92",
        )
        d_anon = ResourceTreatmentDecision(
            resource_id="analytics_4566",
            system_id="analytics_platform",
            data_category="ANALYTICS_PROFILE",
            rule_id="rule_07",
            required_action="ANONYMIZE",
            observed_state="ANONYMIZED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Profile attributes unlinked",
            evidence_id="evidence_92",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_clean",
            user_id="usr_clean",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_red, d_anon],
            decisions_by_resource={"support_4715": d_red, "analytics_4566": d_anon},
        )
        res = self.assessor.assess_remaining_data(pol_res)

        self.assertFalse(res.has_remaining_data)
        self.assertEqual(res.total_residual_findings, 0)

    # 5. Confirmed replica drift creates a REPORT_REMAINING_RECORD
    def test_05_replica_drift_finding(self):
        d_primary = ResourceTreatmentDecision(
            resource_id="account_primary",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Primary database absent",
            evidence_id="evidence_db_01",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_drift",
            user_id="usr_drift",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_primary],
            decisions_by_resource={"account_primary": d_primary},
            replica_drift_findings=[
                {
                    "resource_id": "account_replica_02",
                    "system_id": "account_service_replica",
                    "data_category": "USER_PROFILE",
                    "evidence_id": "evidence_rep_02",
                }
            ],
        )
        res = self.assessor.assess_remaining_data(pol_res)

        self.assertTrue(res.has_remaining_data)
        self.assertEqual(res.replica_drift_count, 1)
        drift_finding = res.findings_by_resource["account_replica_02"]
        self.assertTrue(drift_finding.is_replica_drift)
        self.assertEqual(drift_finding.finding_type, "REPORT_REMAINING_RECORD")
        self.assertEqual(drift_finding.evidence_id, "evidence_rep_02")

    # 6. Deduplication of repeated evidence sightings for the same resource
    def test_06_repeated_evidence_deduplication(self):
        d1 = ResourceTreatmentDecision(
            resource_id="search_052",
            system_id="search_service",
            data_category="SEARCH_INDEX_ENTRY",
            rule_id="rule_03",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Search sighting 1",
            evidence_id="evidence_03",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="search_052",
            system_id="search_service",
            data_category="SEARCH_INDEX_ENTRY",
            rule_id="rule_03",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Search sighting 2",
            evidence_id="evidence_03",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_11",
            user_id="usr_11",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2],
            decisions_by_resource={"search_052": d2},
        )
        res = self.assessor.assess_remaining_data(pol_res)

        self.assertEqual(res.total_residual_findings, 1)
        self.assertEqual(len(res.findings), 1)
        self.assertEqual(res.findings[0].resource_id, "search_052")

    # 7. Missing state evidence / indeterminate records
    def test_07_indeterminate_records_unverified(self):
        d_unknown = ResourceTreatmentDecision(
            resource_id="cache_99",
            system_id="cache_service",
            data_category="CACHE_ENTRY",
            rule_id="rule_04",
            required_action="DELETE",
            observed_state="UNKNOWN",
            compliance_result=ComplianceResult.INDETERMINATE,
            reason="Evidence captured post-cutoff excluded; state unknown",
            evidence_id=None,
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_unknown",
            user_id="usr_unknown",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="AMBIGUOUS",
            decisions=[d_unknown],
            decisions_by_resource={"cache_99": d_unknown},
        )
        res = self.assessor.assess_remaining_data(pol_res)

        # Indeterminate state is not fabricated as a present record finding
        self.assertFalse(res.has_remaining_data)
        self.assertEqual(res.total_residual_findings, 0)
        self.assertIn("cache_99", res.unverified_resources)

    # 8. Deterministic Ordering: REPORT_REMAINING_RECORD before REPORT_EXPOSED_PII, then system_id, resource_id
    def test_08_deterministic_ordering(self):
        d_pii_1 = ResourceTreatmentDecision(
            resource_id="support_864",
            system_id="support_platform",
            data_category="SUPPORT_MESSAGE",
            rule_id="rule_05",
            required_action="REDACT",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="PII in message",
            evidence_id="evidence_03",
        )
        d_pii_2 = ResourceTreatmentDecision(
            resource_id="analytics_2034",
            system_id="analytics_platform",
            data_category="ANALYTICS_PROFILE",
            rule_id="rule_07",
            required_action="ANONYMIZE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Attributable profile",
            evidence_id="evidence_03",
        )
        d_rec = ResourceTreatmentDecision(
            resource_id="search_052",
            system_id="search_service",
            data_category="SEARCH_INDEX_ENTRY",
            rule_id="rule_03",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Search index present",
            evidence_id="evidence_03",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_ord",
            user_id="usr_ord",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_pii_1, d_pii_2, d_rec],
            decisions_by_resource={d.resource_id: d for d in [d_pii_1, d_pii_2, d_rec]},
        )
        res = self.assessor.assess_remaining_data(pol_res)

        self.assertEqual(res.total_residual_findings, 3)
        # Expected order:
        # 1. REPORT_REMAINING_RECORD (search_service, search_052)
        # 2. REPORT_EXPOSED_PII (analytics_platform, analytics_2034)
        # 3. REPORT_EXPOSED_PII (support_platform, support_864)
        ops = [f.finding_type for f in res.findings]
        rids = [f.resource_id for f in res.findings]
        self.assertEqual(ops, ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_EXPOSED_PII"])
        self.assertEqual(rids, ["search_052", "analytics_2034", "support_864"])

    # 9. Participant-Visible evidence_id preservation
    def test_09_evidence_id_preservation(self):
        d_viol = ResourceTreatmentDecision(
            resource_id="export_001",
            system_id="export_service",
            data_category="USER_EXPORT",
            rule_id="rule_09",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Export zip archive remains on disk",
            evidence_id="evidence_59",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_08",
            user_id="usr_08",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_viol],
            decisions_by_resource={"export_001": d_viol},
        )
        res = self.assessor.assess_remaining_data(pol_res)
        self.assertEqual(res.findings[0].evidence_id, "evidence_59")

    # 10. Repeat-Run Determinism across 50 iterations
    def test_10_repeat_run_determinism(self):
        d_viol = ResourceTreatmentDecision(
            resource_id="account_005",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="User profile remains present",
            evidence_id="evidence_54",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_det",
            user_id="usr_det",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_viol],
            decisions_by_resource={"account_005": d_viol},
        )
        first = self.assessor.assess_remaining_data(pol_res)
        for _ in range(50):
            subsequent = self.assessor.assess_remaining_data(pol_res)
            self.assertEqual(first.has_remaining_data, subsequent.has_remaining_data)
            self.assertEqual(first.total_residual_findings, subsequent.total_residual_findings)
            self.assertEqual([f.resource_id for f in first.findings], [f.resource_id for f in subsequent.findings])
            self.assertEqual([f.finding_type for f in first.findings], [f.finding_type for f in subsequent.findings])


if __name__ == "__main__":
    unittest.main()

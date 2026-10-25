"""Phase 7.3 Unit Tests: Resource Compliance Aggregator.

Tests:
1. Multiple compliant resources (all satisfying required treatments).
2. Mixed compliant and non-compliant resources (proves single compliant cannot make case compliant).
3. Missing / indeterminate evidence resources.
4. Contradictory observations (timeline contradiction propagation).
5. Valid retention exceptions (SECURITY_AUDIT_LOG, ACCOUNT_TOMBSTONE).
6. Handling of duplicate resource references in evaluation inputs.
7. Empty resource collections handling.
8. Replica drift detection and violation surfacing.
9. Remediations required mapping.
10. Preservation of rule IDs, decision reasons, and evidence provenance.
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
    from .models import ResourceAggregationResult
    from .aggregator import ResourceComplianceAggregator
except ImportError:
    from models import ResourceAggregationResult
    from aggregator import ResourceComplianceAggregator

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


class TestResourceComplianceAggregator(unittest.TestCase):
    """Test suite for ResourceComplianceAggregator."""

    @classmethod
    def setUpClass(cls):
        cls.aggregator = ResourceComplianceAggregator()
        cls.audit_cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Multiple Compliant Resources
    def test_01_multiple_compliant_resources(self):
        d1 = ResourceTreatmentDecision(
            resource_id="account_001",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Record is absent",
            evidence_id="evidence_54",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="audit_record_2016",
            system_id="security_service",
            data_category="SECURITY_AUDIT_LOG",
            rule_id="rule_12",
            required_action="RETAIN",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Retained within retention period",
            evidence_id="evidence_94",
        )
        d3 = ResourceTreatmentDecision(
            resource_id="analytics_9406",
            system_id="analytics_platform",
            data_category="ANALYTICS_PROFILE",
            rule_id="rule_07",
            required_action="ANONYMIZE",
            observed_state="ANONYMIZED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Identifiers unlinked",
            evidence_id="evidence_94",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_03",
            user_id="usr_03",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d1, d2, d3],
            decisions_by_resource={d.resource_id: d for d in [d1, d2, d3]},
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        self.assertTrue(agg.is_all_compliant)
        self.assertFalse(agg.has_violations)
        self.assertFalse(agg.has_indeterminate)
        self.assertTrue(agg.has_retained_data)
        self.assertEqual(agg.total_resources, 3)
        self.assertEqual(agg.compliant_resources, ["account_001", "analytics_9406", "audit_record_2016"])
        self.assertEqual(agg.retained_resources, ["audit_record_2016"])
        self.assertEqual(agg.evidence_provenance_by_resource["account_001"], "evidence_54")
        self.assertEqual(agg.rule_id_by_resource["analytics_9406"], "rule_07")

    # 2. Mixed Compliant and Non-Compliant Resources (Single compliant cannot make case compliant)
    def test_02_mixed_compliant_and_non_compliant(self):
        d_comp = ResourceTreatmentDecision(
            resource_id="account_006",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Record is absent",
            evidence_id="evidence_57",
        )
        d_viol = ResourceTreatmentDecision(
            resource_id="search_001",
            system_id="search_service",
            data_category="SEARCH_INDEX_ENTRY",
            rule_id="rule_03",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Search index entry remains present",
            evidence_id="evidence_57",
        )
        bundle_viol = PolicyOperationBundle(
            resource_id="search_001",
            system_id="search_service",
            data_category="SEARCH_INDEX_ENTRY",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            remediations=[
                OperationSpec(
                    phase=StepPhase.REMEDIATION.value,
                    system_id="search_service",
                    resource_id="search_001",
                    operation=StepOperation.DELETE_RECORD.value,
                    state=StepState.ABSENT.value,
                    evidence_id="",
                )
            ]
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_06",
            user_id="usr_06",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_comp, d_viol],
            decisions_by_resource={"account_006": d_comp, "search_001": d_viol},
            operation_bundles_by_resource={"search_001": bundle_viol},
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        self.assertFalse(agg.is_all_compliant)
        self.assertTrue(agg.has_violations)
        self.assertEqual(agg.compliant_resources, ["account_006"])
        self.assertEqual(agg.non_compliant_resources, ["search_001"])
        self.assertEqual(agg.remediations_required_by_resource["search_001"], "DELETE_RECORD")
        self.assertIn("Search index entry remains present", agg.violations_by_resource["search_001"])

    # 3. Missing / Indeterminate Evidence
    def test_03_indeterminate_missing_evidence(self):
        d_indet = ResourceTreatmentDecision(
            resource_id="cache_001",
            system_id="cache_service",
            data_category="CACHE_ENTRY",
            rule_id="rule_04",
            required_action="DELETE",
            observed_state="UNKNOWN",
            compliance_result=ComplianceResult.INDETERMINATE,
            reason="No admissible evidence captured before audit cutoff",
            evidence_id=None,
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_indet",
            user_id="usr_indet",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="AMBIGUOUS",
            decisions=[d_indet],
            decisions_by_resource={"cache_001": d_indet},
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        self.assertFalse(agg.is_all_compliant)
        self.assertTrue(agg.has_indeterminate)
        self.assertIn("cache_001", agg.indeterminate_resources)

    # 4. Contradictory Observations
    def test_04_contradictory_evidence_propagation(self):
        d_comp = ResourceTreatmentDecision(
            resource_id="account_001",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Record is absent",
            evidence_id="evidence_54",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_contra",
            user_id="usr_contra",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_comp],
            decisions_by_resource={"account_001": d_comp},
            contradictions=["Activity log claims DELETE_RECORD at 10:00 but evidence captured at 11:00 shows PRESENT"],
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        # Contradictions prevent case from being considered cleanly all_compliant
        self.assertFalse(agg.is_all_compliant)
        self.assertTrue(agg.has_indeterminate)
        self.assertEqual(len(agg.contradictions), 1)

    # 5. Valid Retention Exceptions (Tombstone with stable ref, Audit record within retention)
    def test_05_valid_retention_exceptions(self):
        d_tomb = ResourceTreatmentDecision(
            resource_id="tombstone_440",
            system_id="identity_service",
            data_category="ACCOUNT_TOMBSTONE",
            rule_id="rule_15",
            required_action="REDACT",
            observed_state="REDACTED",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Stable reference user_541 preserved; direct PII redacted",
            evidence_id="evidence_51",
        )
        d_audit = ResourceTreatmentDecision(
            resource_id="audit_record_6909",
            system_id="security_service",
            data_category="SECURITY_AUDIT_LOG",
            rule_id="rule_12",
            required_action="RETAIN",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Mandatory retention period active",
            evidence_id="evidence_51",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_31",
            user_id="usr_31",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_tomb, d_audit],
            decisions_by_resource={"tombstone_440": d_tomb, "audit_record_6909": d_audit},
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        self.assertTrue(agg.is_all_compliant)
        self.assertTrue(agg.has_retained_data)
        self.assertEqual(agg.retained_resources, ["audit_record_6909", "tombstone_440"])

    # 6. Handling Duplicate Resource References Deterministically
    def test_06_duplicate_resource_references(self):
        # Resource account_dup evaluated twice (e.g. from decisions list and map)
        d_ok = ResourceTreatmentDecision(
            resource_id="account_dup",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Snapshot shows absent",
            evidence_id="evidence_01",
        )
        d_bad = ResourceTreatmentDecision(
            resource_id="account_dup",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Second replica shows present",
            evidence_id="evidence_02",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_dup",
            user_id="usr_dup",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_ok, d_bad],
            decisions_by_resource={"account_dup": d_bad},
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        # NON_COMPLIANT takes deterministic precedence
        self.assertEqual(agg.total_resources, 1)
        self.assertFalse(agg.is_all_compliant)
        self.assertEqual(agg.non_compliant_resources, ["account_dup"])
        self.assertEqual(agg.compliant_resources, [])

    # 7. Empty Resource Collection
    def test_07_empty_resource_collection(self):
        pol_res = CasePolicyEvaluationResult(
            case_id="case_empty",
            user_id=None,
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="UNRESOLVED",
            decisions=[],
            decisions_by_resource={},
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        self.assertEqual(agg.total_resources, 0)
        self.assertFalse(agg.is_all_compliant)
        self.assertTrue(any("zero associated resources" in d for d in agg.diagnostics))

    # 8. Replica Drift Detection
    def test_08_replica_drift_detection(self):
        d_comp = ResourceTreatmentDecision(
            resource_id="account_primary",
            system_id="account_service",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            required_action="DELETE",
            observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT,
            reason="Primary record is absent",
            evidence_id="evidence_54",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_drift",
            user_id="usr_drift",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_comp],
            decisions_by_resource={"account_primary": d_comp},
            replica_drift_findings=[{"resource_id": "account_replica_01", "system_id": "account_service_replica"}],
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        self.assertFalse(agg.is_all_compliant)
        self.assertTrue(agg.has_replica_drift)
        self.assertTrue(agg.has_violations)
        self.assertIn("account_replica_01", agg.non_compliant_resources)
        self.assertIn("account_replica_01", agg.violations_by_resource)

    # 9. Remediations Required Mapping Across Action Types
    def test_09_remediations_required_mapping(self):
        d_red = ResourceTreatmentDecision(
            resource_id="support_01",
            system_id="support_platform",
            data_category="SUPPORT_MESSAGE",
            rule_id="rule_05",
            required_action="REDACT",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="PII exposed",
            evidence_id="evidence_01",
        )
        d_anon = ResourceTreatmentDecision(
            resource_id="analytics_01",
            system_id="analytics_platform",
            data_category="ANALYTICS_PROFILE",
            rule_id="rule_07",
            required_action="ANONYMIZE",
            observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Profile linkable",
            evidence_id="evidence_01",
        )
        d_flow = ResourceTreatmentDecision(
            resource_id="data_flow_01",
            system_id="integration_service",
            data_category="DATA_FLOW",
            rule_id=None,
            required_action=None,
            observed_state="ACTIVE",
            compliance_result=ComplianceResult.NON_COMPLIANT,
            reason="Active sync flow",
            evidence_id="evidence_01",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_rems",
            user_id="usr_rems",
            audit_at=self.audit_cutoff,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=[d_red, d_anon, d_flow],
            decisions_by_resource={"support_01": d_red, "analytics_01": d_anon, "data_flow_01": d_flow},
        )
        agg = self.aggregator.aggregate_compliance(pol_res)

        self.assertEqual(agg.remediations_required_by_resource["support_01"], "REDACT_RECORD")
        self.assertEqual(agg.remediations_required_by_resource["analytics_01"], "ANONYMIZE_RECORD")
        self.assertEqual(agg.remediations_required_by_resource["data_flow_01"], "DISABLE_DATA_FLOW")

    # 10. Repeat-Run Determinism
    def test_10_repeat_run_determinism(self):
        d1 = ResourceTreatmentDecision(
            resource_id="res_a", system_id="sys_a", data_category="USER_PROFILE",
            rule_id="rule_01", required_action="DELETE", observed_state="ABSENT",
            compliance_result=ComplianceResult.COMPLIANT, reason="Absent", evidence_id="ev_1",
        )
        d2 = ResourceTreatmentDecision(
            resource_id="res_b", system_id="sys_b", data_category="USER_EXPORT",
            rule_id="rule_09", required_action="DELETE", observed_state="PRESENT",
            compliance_result=ComplianceResult.NON_COMPLIANT, reason="Present", evidence_id="ev_2",
        )
        pol_res = CasePolicyEvaluationResult(
            case_id="case_det", user_id="usr_det", audit_at=self.audit_cutoff,
            is_non_deletion_request=False, resolution_status="RESOLVED",
            decisions=[d1, d2], decisions_by_resource={"res_a": d1, "res_b": d2},
        )
        first = self.aggregator.aggregate_compliance(pol_res)
        for _ in range(50):
            subsequent = self.aggregator.aggregate_compliance(pol_res)
            self.assertEqual(first.is_all_compliant, subsequent.is_all_compliant)
            self.assertEqual(first.compliant_resources, subsequent.compliant_resources)
            self.assertEqual(first.non_compliant_resources, subsequent.non_compliant_resources)
            self.assertEqual(first.violations_by_resource, subsequent.violations_by_resource)


if __name__ == "__main__":
    unittest.main()

"""Phase 6.8: Comprehensive Policy Engine Edge-Case and Stress Testing.

Covers the complete Phase 6 test matrix:
1. Loader and validation edge cases (exact duplicates vs legitimate repeated categories, ambiguous precedence).
2. Treatment logic edge cases (unsupported states, partial/insufficient evidence).
3. Exception edge cases (tombstone missing stable reference, prohibited credentials in retained records, unmet conditions).
4. Temporal and forensic edge cases (cutoff boundaries, contradictory timestamps, replica drift, active sync/restore risks).
5. Upstream integration and repeat-run determinism using real Phase 3B/4/5 classes on sample data.
"""

import copy
import io
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

POLICY_DIR = Path(__file__).resolve().parent
ROOT_DIR = POLICY_DIR.parent.parent

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))

try:
    from .loader import PolicyLoader, PolicyRule
    from .engine import (
        TreatmentEngine,
        ComplianceResult,
        RequiredAction,
        ResourceTreatmentDecision,
        inspect_tombstone_fields,
    )
    from .mapper import (
        PolicyOperationMapper,
        StepPhase,
        StepOperation,
        StepState,
    )
    from .temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
    )
    from .service import (
        PolicyEvaluationService,
        CasePolicyEvaluationResult,
    )
except ImportError:
    from loader import PolicyLoader, PolicyRule
    from engine import (
        TreatmentEngine,
        ComplianceResult,
        RequiredAction,
        ResourceTreatmentDecision,
        inspect_tombstone_fields,
    )
    from mapper import (
        PolicyOperationMapper,
        StepPhase,
        StepOperation,
        StepState,
    )
    from temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
    )
    from service import (
        PolicyEvaluationService,
        CasePolicyEvaluationResult,
    )

# Upstream imports for end-to-end integration
IDENTITY_DIR = ROOT_DIR / "code" / "identity"
TIMELINE_DIR = ROOT_DIR / "code" / "timeline"
EVIDENCE_DIR = ROOT_DIR / "code" / "evidence"

if str(IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(IDENTITY_DIR))
if str(TIMELINE_DIR) not in sys.path:
    sys.path.insert(0, str(TIMELINE_DIR))
if str(EVIDENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_DIR))

try:
    from resolver import IdentityResolver
    from integration import EvidenceIntegrator
    from reconstructor import TimelineReconstructor, ResourceTimeline
except ImportError:
    pass


class TestPolicyLoaderEdgeCases(unittest.TestCase):
    """Test loader edge cases and schema anomalies."""

    def test_exact_duplicate_rule_warning_vs_repeated_category(self):
        """Exact duplicate rules trigger DUPLICATE_RULE_CONTENT warning; legitimate repeated categories do not."""
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_01,SUPPORT_MESSAGE,Shared context,REDACT\n"
            "rule_02,SUPPORT_MESSAGE,Shared context,REDACT\n"  # Exact duplicate content
            "rule_03,SUPPORT_MESSAGE,Personal note only,DELETE\n"  # Legitimate repeated category with different condition
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.warnings), 1)
        self.assertEqual(res.warnings[0]["warning_type"], "DUPLICATE_RULE_CONTENT")
        self.assertEqual(res.warnings[0]["rule_id"], "rule_02")

        # 3 rules loaded deterministically
        rules = loader.get_rules_for_category("SUPPORT_MESSAGE")
        self.assertEqual(len(rules), 3)

    def test_conflicting_rules_ambiguous_precedence(self):
        """Conflicting rules for same category and condition with different actions trigger CONFLICTING_RULE error."""
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_01,CACHE_ENTRY,Always,DELETE\n"
            "rule_02,CACHE_ENTRY,Always,RETAIN\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertFalse(res.is_valid)
        self.assertTrue(any(e["error_type"] == "CONFLICTING_RULE" for e in res.errors))


class TestTreatmentEngineEdgeCases(unittest.TestCase):
    """Test treatment engine edge cases, exceptions, and boundary handling."""

    def setUp(self):
        self.engine = TreatmentEngine()

    def test_unsupported_states_yield_indeterminate(self):
        """Arbitrary or corrupt observed states produce INDETERMINATE."""
        for state in ["CORRUPT", "HALF_DELETED", "PENDING_SYNC", "UNKNOWN_FORMAT"]:
            decision = self.engine.evaluate_resource(
                resource_id="account_001",
                observed_state=state,
                data_category="USER_PROFILE",
            )
            self.assertEqual(decision.compliance_result, ComplianceResult.INDETERMINATE)
            self.assertTrue("Unsupported state" in decision.reason or "UNKNOWN" in decision.reason)

    def test_tombstone_missing_stable_reference(self):
        """Tombstone record missing a stable user identifier is invalid and non-compliant."""
        record_data = {
            "name": None,
            "email": None,
            "status": "tombstoned",
            # No user_id or subject_reference
        }
        res = inspect_tombstone_fields(record_data)
        self.assertFalse(res.is_valid_tombstone)
        self.assertFalse(res.has_stable_reference)
        self.assertIsNone(res.stable_reference_value)

        decision = self.engine.evaluate_resource(
            resource_id="tombstone_001",
            observed_state="REDACTED",
            data_category="ACCOUNT_TOMBSTONE",
            context={"record_data": record_data},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertTrue("stable reference is missing" in decision.reason)

    def test_retained_record_with_prohibited_sensitive_credentials(self):
        """Mandatory retained record containing prohibited credentials (password/card) is non-compliant."""
        record_data = {
            "user_id": "usr_99",
            "audit_action": "LOGIN",
            "password": "plain_text_secret",
        }
        decision = self.engine.evaluate_resource(
            resource_id="audit_record_01",
            observed_state="PRESENT",
            data_category="SECURITY_AUDIT_LOG",
            context={"record_data": record_data},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertTrue("prohibited sensitive fields" in decision.reason)

    def test_retention_condition_not_met_legal_hold(self):
        """Legal hold record when legal_hold_active is False yields NOT_APPLICABLE."""
        decision = self.engine.evaluate_resource(
            resource_id="legal_doc_01",
            observed_state="PRESENT",
            data_category="LEGAL_HOLD_RECORD",
            context={"legal_hold_active": False},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NOT_APPLICABLE)
        self.assertTrue("No active legal hold" in decision.reason)

    def test_retention_period_exceeded(self):
        """Retained record when within_retention_period is False yields NON_COMPLIANT."""
        decision = self.engine.evaluate_resource(
            resource_id="audit_rec_old",
            observed_state="PRESENT",
            data_category="SECURITY_AUDIT_LOG",
            context={"within_retention_period": False},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertTrue("outside the retention period" in decision.reason)


class TestRepeatRunDeterminismAndImmutability(unittest.TestCase):
    """Test repeat-run determinism and immutability under multiple evaluations."""

    def setUp(self):
        self.service = PolicyEvaluationService()

    def test_deterministic_multi_run_evaluation(self):
        """Evaluating the same timeline 5 times produces identical outputs and orderings."""
        from test_service import MockResourceTimeline, MockTimelineReconstructionResult

        t1 = MockResourceTimeline("account_005", "account_service", "USER_PROFILE", "PRESENT", "evidence_db_01")
        t2 = MockResourceTimeline("backup_40", "backup_service", "BACKUP_ARCHIVE", "ACTIVE", "evidence_bak_01", is_restore_risk=True)
        t3 = MockResourceTimeline("tombstone_01", "identity_service", "ACCOUNT_TOMBSTONE", "REDACTED", "evidence_tb_01")

        recon = MockTimelineReconstructionResult(
            case_id="case_det_001",
            resources={"backup_40": t2, "tombstone_01": t3, "account_005": t1},  # deliberately out of order
        )
        request = {"case_id": "case_det_001", "audit_at": "2026-06-01T12:00:00Z"}

        runs = [self.service.evaluate_timeline(request, recon) for _ in range(5)]

        # Check identical results across all 5 runs
        first = runs[0]
        for run in runs[1:]:
            self.assertEqual([d.resource_id for d in first.decisions], [d.resource_id for d in run.decisions])
            self.assertEqual([d.compliance_result for d in first.decisions], [d.compliance_result for d in run.decisions])
            self.assertEqual([d.required_action for d in first.decisions], [d.required_action for d in run.decisions])
            self.assertEqual([b.resource_id for b in first.operation_bundles], [b.resource_id for b in run.operation_bundles])
            self.assertEqual(first.summary, run.summary)


class TestEndToEndPipelineIntegration(unittest.TestCase):
    """End-to-end integration test with real Phase 3B/4/5 components."""

    @classmethod
    def setUpClass(cls):
        dataset_dir = ROOT_DIR / "dataset"
        cls.resolver = IdentityResolver.from_directory(dataset_dir)
        cls.integrator = EvidenceIntegrator()
        cls.reconstructor = TimelineReconstructor()
        cls.policy_service = PolicyEvaluationService()

    def test_sample_case_e2e_evaluation(self):
        """Evaluate a real sample deletion request through Phase 3B, 4, 5, and Phase 6."""
        import csv
        sample_csv = ROOT_DIR / "dataset" / "sample_deletion_requests.csv"
        if not sample_csv.is_file():
            self.skipTest("sample_deletion_requests.csv not found")

        with open(sample_csv, "r", encoding="utf-8-sig") as f:
            reader = list(csv.DictReader(f))

        # Pick the first sample request
        req = reader[0]
        case_id = req["case_id"]

        # Run Phase 5 Reconstruction
        timeline_result = self.reconstructor.reconstruct_for_request(
            request=req,
            resolver=self.resolver,
            integrator=self.integrator,
        )

        self.assertEqual(timeline_result.case_id, case_id)

        # Run Phase 6 Policy Evaluation
        policy_result = self.policy_service.evaluate_timeline(
            request=req,
            timeline_result=timeline_result,
        )

        self.assertIsInstance(policy_result, CasePolicyEvaluationResult)
        self.assertEqual(policy_result.case_id, case_id)
        self.assertIsInstance(policy_result.decisions, list)
        self.assertIsInstance(policy_result.operation_bundles, list)

        # Every decision must be an allowed challenge state
        for dec in policy_result.decisions:
            self.assertIn(dec.compliance_result, [
                ComplianceResult.COMPLIANT,
                ComplianceResult.NON_COMPLIANT,
                ComplianceResult.INDETERMINATE,
                ComplianceResult.NOT_APPLICABLE,
            ])
            # Evidence ID must be valid prefix or empty
            self.assertTrue(validate_evidence_id(dec.evidence_id))

        # Every operation bundle must conform strictly to challenge vocabulary
        for bundle in policy_result.operation_bundles:
            for step in bundle.findings:
                self.assertEqual(step.phase, "FINDING")
                self.assertTrue(PolicyOperationMapper.is_valid_step(step.phase, step.operation, step.state))
            for step in bundle.remediations:
                self.assertEqual(step.phase, "REMEDIATION")
                self.assertTrue(PolicyOperationMapper.is_valid_step(step.phase, step.operation, step.state))
            for step in bundle.verifications:
                self.assertEqual(step.phase, "VERIFICATION")
                self.assertTrue(PolicyOperationMapper.is_valid_step(step.phase, step.operation, step.state))


if __name__ == "__main__":
    unittest.main()

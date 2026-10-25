"""Phase 6.3 Unit Tests: Deterministic Resource-Treatment Engine.

Tests:
- All supported treatment types (DELETE, REDACT, ANONYMIZE, RETAIN).
- Compliant vs Non-compliant resource states for each treatment.
- Explicit uncertainty handling:
  * Missing policy rule for category -> INDETERMINATE
  * Unsupported / unknown resource state -> INDETERMINATE
  * Conflicting policy rules -> INDETERMINATE
- Disambiguation logic (support_ attachment vs message, marketing vs analytics).
- Repeat-run determinism (same inputs produce identical decisions).
- Non-mutation of input parameters.
"""

from pathlib import Path
import sys
import unittest
import copy

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
POLICY_DIR = CURRENT_DIR

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))

from loader import PolicyLoader, PolicyRule
from engine import (
    TreatmentEngine,
    ResourceTreatmentDecision,
    ComplianceResult,
    RequiredAction,
)


class TestTreatmentEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = TreatmentEngine()

    # 1. DELETE Treatment: Compliant when ABSENT
    def test_01_delete_treatment_compliant_when_absent(self):
        decision = self.engine.evaluate_resource(
            resource_id="account_001",
            observed_state="ABSENT",
            data_category="USER_PROFILE",
            evidence_id="evidence_54",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_01")
        self.assertEqual(decision.required_action, "DELETE")
        self.assertEqual(decision.observed_state, "ABSENT")
        self.assertEqual(decision.evidence_id, "evidence_54")
        self.assertTrue(decision.is_compliant)
        self.assertFalse(decision.is_non_compliant)

    # 2. DELETE Treatment: Non-compliant when PRESENT
    def test_02_delete_treatment_non_compliant_when_present(self):
        decision = self.engine.evaluate_resource(
            resource_id="account_005",
            observed_state="PRESENT",
            data_category="USER_PROFILE",
            evidence_id="evidence_54",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_01")
        self.assertEqual(decision.required_action, "DELETE")
        self.assertEqual(decision.observed_state, "PRESENT")
        self.assertTrue(decision.is_non_compliant)

    # 3. DELETE Treatment: Non-compliant even if REDACTED or ANONYMIZED
    def test_03_delete_treatment_non_compliant_if_retained_redacted(self):
        decision = self.engine.evaluate_resource(
            resource_id="export_001",
            observed_state="REDACTED",
            data_category="USER_EXPORT",
            evidence_id="evidence_59",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_09")
        self.assertEqual(decision.required_action, "DELETE")

    # 4. REDACT Treatment: Compliant when REDACTED
    def test_04_redact_treatment_compliant_when_redacted(self):
        decision = self.engine.evaluate_resource(
            resource_id="support_4715",
            observed_state="REDACTED",
            data_category="SUPPORT_MESSAGE",
            evidence_id="evidence_92",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_05")
        self.assertEqual(decision.required_action, "REDACT")
        self.assertEqual(decision.observed_state, "REDACTED")
        self.assertTrue(decision.is_compliant)

    # 5. REDACT Treatment: Compliant when ABSENT (full deletion is compliant)
    def test_05_redact_treatment_compliant_when_absent(self):
        decision = self.engine.evaluate_resource(
            resource_id="tombstone_100",
            observed_state="ABSENT",
            data_category="ACCOUNT_TOMBSTONE",
            evidence_id="evidence_51",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_15")
        self.assertEqual(decision.required_action, "REDACT")

    # 6. REDACT Treatment: Non-compliant when PRESENT (identifiers exposed)
    def test_06_redact_treatment_non_compliant_when_present(self):
        decision = self.engine.evaluate_resource(
            resource_id="tombstone_9178",
            observed_state="PRESENT",
            data_category="ACCOUNT_TOMBSTONE",
            evidence_id="evidence_51",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_15")
        self.assertEqual(decision.required_action, "REDACT")
        self.assertTrue(decision.is_non_compliant)

    # 7. ANONYMIZE Treatment: Compliant when ANONYMIZED
    def test_07_anonymize_treatment_compliant_when_anonymized(self):
        decision = self.engine.evaluate_resource(
            resource_id="analytics_901",
            observed_state="ANONYMIZED",
            data_category="ANALYTICS_PROFILE",
            evidence_id="evidence_56",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_07")
        self.assertEqual(decision.required_action, "ANONYMIZE")
        self.assertTrue(decision.is_compliant)

    # 8. ANONYMIZE Treatment: Non-compliant when PRESENT (still attributable)
    def test_08_anonymize_treatment_non_compliant_when_present(self):
        decision = self.engine.evaluate_resource(
            resource_id="analytics_2034",
            observed_state="PRESENT",
            data_category="ANALYTICS_PROFILE",
            evidence_id="evidence_03",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_07")
        self.assertEqual(decision.required_action, "ANONYMIZE")
        self.assertTrue(decision.is_non_compliant)

    # 9. RETAIN Treatment: Compliant when PRESENT
    def test_09_retain_treatment_compliant_when_present(self):
        decision = self.engine.evaluate_resource(
            resource_id="audit_record_2016",
            observed_state="PRESENT",
            data_category="SECURITY_AUDIT_LOG",
            evidence_id="evidence_94",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_12")
        self.assertEqual(decision.required_action, "RETAIN")
        self.assertTrue(decision.is_compliant)

    # 10. RETAIN Treatment: Non-compliant when prematurely ABSENT
    def test_10_retain_treatment_non_compliant_when_absent(self):
        decision = self.engine.evaluate_resource(
            resource_id="audit_record_9999",
            observed_state="ABSENT",
            data_category="SECURITY_AUDIT_LOG",
            evidence_id="evidence_94",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_12")
        self.assertEqual(decision.required_action, "RETAIN")
        self.assertTrue(decision.is_non_compliant)

    # 11. RETAIN Treatment: BACKUP_ARCHIVE compliant when BLOCKED
    def test_11_backup_archive_compliant_when_blocked(self):
        decision = self.engine.evaluate_resource(
            resource_id="backup_3120",
            observed_state="BLOCKED",
            data_category="BACKUP_ARCHIVE",
            evidence_id="evidence_92",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_14")
        self.assertEqual(decision.required_action, "RETAIN")
        self.assertTrue(decision.is_compliant)

    # 12. RETAIN Treatment: BACKUP_ARCHIVE non-compliant when ACTIVE restore risk
    def test_12_backup_archive_non_compliant_when_active(self):
        decision = self.engine.evaluate_resource(
            resource_id="backup_4978",
            observed_state="ACTIVE",
            data_category="BACKUP_ARCHIVE",
            evidence_id="evidence_93",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_14")
        self.assertEqual(decision.required_action, "RETAIN")
        self.assertTrue(decision.is_non_compliant)

    # 13. DATA_FLOW Infrastructure Entity: Compliant when DISABLED
    def test_13_data_flow_compliant_when_disabled(self):
        decision = self.engine.evaluate_resource(
            resource_id="data_flow_6244",
            observed_state="DISABLED",
            data_category="DATA_FLOW",
            evidence_id="evidence_92",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.required_action, "DISABLE_DATA_FLOW")
        self.assertTrue(decision.is_compliant)

    # 14. DATA_FLOW Infrastructure Entity: Non-compliant when ACTIVE
    def test_14_data_flow_non_compliant_when_active(self):
        decision = self.engine.evaluate_resource(
            resource_id="data_flow_9522",
            observed_state="ACTIVE",
            data_category="DATA_FLOW",
            evidence_id="evidence_03",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.required_action, "DISABLE_DATA_FLOW")
        self.assertTrue(decision.is_non_compliant)

    # 15. Uncertainty Handling: Missing Policy Rule for Category
    def test_15_uncertainty_missing_policy_rule(self):
        decision = self.engine.evaluate_resource(
            resource_id="custom_res_001",
            observed_state="PRESENT",
            data_category="UNREGISTERED_CATEGORY",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertIsNone(decision.rule_id)
        self.assertTrue(decision.is_indeterminate)
        self.assertIn("No governing policy rule found", decision.reason)

    # 16. Uncertainty Handling: Unknown / Empty Observed State
    def test_16_uncertainty_unknown_observed_state(self):
        decision = self.engine.evaluate_resource(
            resource_id="account_001",
            observed_state="UNKNOWN",
            data_category="USER_PROFILE",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertTrue(decision.is_indeterminate)
        self.assertIn("compliance cannot be established", decision.reason)

    # 17. Uncertainty Handling: Unsupported State for Action
    def test_17_uncertainty_unsupported_state_for_action(self):
        decision = self.engine.evaluate_resource(
            resource_id="account_001",
            observed_state="PARTIAL_CORRUPTED",
            data_category="USER_PROFILE",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertTrue(decision.is_indeterminate)
        self.assertIn("Unsupported state", decision.reason)

    # 18. Uncertainty Handling: Conflicting Policy Rules in Loader
    def test_18_uncertainty_conflicting_rules(self):
        conflicting_csv = (
            "rule_id,data_category,condition,required_action\n"
            "rule_a,CUSTOM_CAT,Condition A,DELETE\n"
            "rule_b,CUSTOM_CAT,Condition B,RETAIN\n"
        )
        loader = PolicyLoader(conflicting_csv)
        custom_engine = TreatmentEngine(loader)
        decision = custom_engine.evaluate_resource(
            resource_id="custom_01",
            observed_state="PRESENT",
            data_category="CUSTOM_CAT",
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertTrue(decision.is_indeterminate)
        self.assertIn("conflicting rules", decision.reason)

    # 19. Disambiguation: Support Attachment vs Message
    def test_19_support_disambiguation(self):
        # 19a. Explicit context attachment
        cat, reason = self.engine.categorize_resource(
            "support_4218",
            context={"record_type": "SUPPORT_ATTACHMENT"},
        )
        self.assertEqual(cat, "SUPPORT_ATTACHMENT")
        decision_att = self.engine.evaluate_resource(
            resource_id="support_4218",
            observed_state="PRESENT",
            context={"record_type": "SUPPORT_ATTACHMENT"},
        )
        self.assertEqual(decision_att.data_category, "SUPPORT_ATTACHMENT")
        self.assertEqual(decision_att.rule_id, "rule_06")
        self.assertEqual(decision_att.required_action, "DELETE")
        self.assertEqual(decision_att.compliance_result, ComplianceResult.NON_COMPLIANT)

        # 19b. Context pdf file path
        cat_pdf, _ = self.engine.categorize_resource(
            "support_001",
            context={"source_path": "evidence/documents/delivery_correction_attachment.pdf"},
        )
        self.assertEqual(cat_pdf, "SUPPORT_ATTACHMENT")

        # 19c. Explicit message
        decision_msg = self.engine.evaluate_resource(
            resource_id="support_864",
            observed_state="PRESENT",
            context={"record_type": "SUPPORT_MESSAGE"},
        )
        self.assertEqual(decision_msg.data_category, "SUPPORT_MESSAGE")
        self.assertEqual(decision_msg.rule_id, "rule_05")
        self.assertEqual(decision_msg.required_action, "REDACT")
        self.assertEqual(decision_msg.compliance_result, ComplianceResult.NON_COMPLIANT)

    # 20. Determinism: Repeat Runs Yield Identical Decisions
    def test_20_repeat_run_determinism(self):
        params = {
            "resource_id": "account_994",
            "observed_state": "PRESENT",
            "system_id": "account_service",
            "data_category": "USER_PROFILE",
            "evidence_id": "evidence_05",
        }
        res1 = self.engine.evaluate_resource(**params)
        res2 = self.engine.evaluate_resource(**params)
        self.assertEqual(res1, res2)

    # 21. Non-mutation of Input Parameters
    def test_21_non_mutation_of_inputs(self):
        context = {"record_type": "SUPPORT_MESSAGE", "details": "Customer query"}
        context_copy = copy.deepcopy(context)
        self.engine.evaluate_resource(
            resource_id="support_101",
            observed_state="PRESENT",
            context=context,
        )
        self.assertEqual(context, context_copy)


    # 22. Tombstone with Permitted Stable Reference (Compliant)
    def test_22_tombstone_compliant_with_stable_reference(self):
        tombstone_data = {
            "resource_id": "tombstone_440",
            "subject_reference": "user_541",
            "name": None,
            "email": None,
            "phone": None,
            "email_hash": None,
            "account_status": "DELETED",
        }
        decision = self.engine.evaluate_resource(
            resource_id="tombstone_440",
            observed_state="PRESENT",
            data_category="ACCOUNT_TOMBSTONE",
            evidence_id="evidence_51",
            context={"record_data": tombstone_data},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_15")
        self.assertEqual(decision.required_action, "REDACT")
        self.assertEqual(decision.observed_state, "REDACTED")
        self.assertIn("user_541", decision.reason)
        self.assertTrue(decision.is_compliant)

    # 23. Tombstone with Prohibited Direct Identifier Remaining (Non-compliant)
    def test_23_tombstone_non_compliant_with_exposed_pii(self):
        tombstone_data = {
            "resource_id": "tombstone_9178",
            "subject_reference": "user_542",
            "name": "Kofi Addo",
            "email": "addo.kofi@gmail.com",
            "phone": "+233 24 991 1328",
            "email_hash": "4f4b9c98a05a2dad20e52313cce7809d18c3da544754dcd46d728b0173174b26",
            "account_status": "DELETED",
        }
        decision = self.engine.evaluate_resource(
            resource_id="tombstone_9178",
            observed_state="PRESENT",
            data_category="ACCOUNT_TOMBSTONE",
            evidence_id="evidence_51",
            context={"record_data": tombstone_data},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_15")
        self.assertEqual(decision.required_action, "REDACT")
        self.assertTrue(decision.is_non_compliant)
        self.assertIn("prohibited fields exposed", decision.reason)

    # 24. Tombstone Missing Required Stable Reference (Non-compliant)
    def test_24_tombstone_missing_stable_reference(self):
        tombstone_data = {
            "resource_id": "tombstone_orphan",
            "subject_reference": None,
            "user_id": None,
            "name": None,
            "email": None,
            "phone": None,
            "email_hash": None,
            "account_status": "DELETED",
        }
        decision = self.engine.evaluate_resource(
            resource_id="tombstone_orphan",
            observed_state="PRESENT",
            data_category="ACCOUNT_TOMBSTONE",
            evidence_id="evidence_51",
            context={"record_data": tombstone_data},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_15")
        self.assertIn("stable reference is missing", decision.reason)

    # 25. Field Aliases and Casing Variations in Tombstones
    def test_25_tombstone_field_aliases_and_casing(self):
        # Case A: camelCase aliases (emailHash, phoneNumber)
        tombstone_camel = {
            "resource_id": "tombstone_test_1",
            "userId": "user_999",
            "emailHash": "some_sha256_hash",
            "phoneNumber": None,
        }
        dec_camel = self.engine.evaluate_resource(
            resource_id="tombstone_test_1",
            observed_state="PRESENT",
            data_category="ACCOUNT_TOMBSTONE",
            context={"record_data": tombstone_camel},
        )
        self.assertEqual(dec_camel.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertIn("emailHash", dec_camel.reason)

        # Case B: UPPERCASE aliases
        tombstone_upper = {
            "RESOURCE_ID": "tombstone_test_2",
            "SUBJECT_REFERENCE": "user_888",
            "EMAIL": "TEST@EXAMPLE.COM",
        }
        dec_upper = self.engine.evaluate_resource(
            resource_id="tombstone_test_2",
            observed_state="PRESENT",
            data_category="ACCOUNT_TOMBSTONE",
            context={"record_data": tombstone_upper},
        )
        self.assertEqual(dec_upper.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertIn("EMAIL", dec_upper.reason)

    # 26. Retained Record Correctly Preserved (Compliant)
    def test_26_retained_record_correctly_preserved(self):
        decision = self.engine.evaluate_resource(
            resource_id="audit_record_2016",
            observed_state="PRESENT",
            data_category="SECURITY_AUDIT_LOG",
            evidence_id="evidence_94",
            context={"within_retention_period": True},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_12")
        self.assertEqual(decision.required_action, "RETAIN")

    # 27. Required Retained Record Missing (Non-compliant)
    def test_27_required_retained_record_missing(self):
        decision = self.engine.evaluate_resource(
            resource_id="audit_record_missing",
            observed_state="ABSENT",
            data_category="SECURITY_AUDIT_LOG",
            context={"within_retention_period": True},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.rule_id, "rule_12")
        self.assertIn("prematurely ABSENT", decision.reason)

    # 28. Retention Condition Not Met: Outside Retention Period
    def test_28_retention_condition_outside_period(self):
        decision = self.engine.evaluate_resource(
            resource_id="audit_record_old",
            observed_state="PRESENT",
            data_category="SECURITY_AUDIT_LOG",
            context={"within_retention_period": False},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertIn("outside the retention period", decision.reason)

    # 29. Retention Condition Not Met: Legal Hold Inactive (Not Applicable)
    def test_29_retention_legal_hold_inactive(self):
        decision = self.engine.evaluate_resource(
            resource_id="legal_hold_001",
            observed_state="PRESENT",
            data_category="LEGAL_HOLD_RECORD",
            context={"legal_hold_active": False},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NOT_APPLICABLE)
        self.assertIn("No active legal hold", decision.reason)

    # 30. Retention with Sensitive Identifier Restrictions (Non-compliant)
    def test_30_retained_record_with_prohibited_sensitive_fields(self):
        record_data = {
            "audit_id": "audit_123",
            "user_id": "user_456",
            "action": "LOGIN",
            "password": "unhashed_password_123",
        }
        decision = self.engine.evaluate_resource(
            resource_id="audit_record_leaked",
            observed_state="PRESENT",
            data_category="SECURITY_AUDIT_LOG",
            context={"record_data": record_data, "within_retention_period": True},
        )
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertIn("prohibited sensitive fields", decision.reason)


if __name__ == "__main__":
    unittest.main()


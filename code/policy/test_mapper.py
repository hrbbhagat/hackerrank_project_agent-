"""Phase 6.5 Unit Tests: Policy-to-Challenge-Operation Mapping.

Tests:
- All 15 official challenge operations across FINDING, REMEDIATION, VERIFICATION.
- Exact permitted (phase, operation, state) combinations.
- Rejection of invalid / unapproved operations, states, or phase pairings.
- Mapping of DELETE violations (REPORT_REMAINING_RECORD, DELETE_RECORD, VERIFY_RECORD_ABSENT).
- Mapping of REDACT violations (REPORT_EXPOSED_PII, REDACT_RECORD, VERIFY_RECORD_REDACTED).
- Mapping of ANONYMIZE violations (REPORT_EXPOSED_PII, ANONYMIZE_RECORD, VERIFY_RECORD_ANONYMIZED).
- Mapping of RETAIN obligations (VERIFY_RECORD_PRESENT).
- Non-fabrication of RESTORE_RECORD for missing retained records.
- Mapping of active data flows (REPORT_ACTIVE_DATA_FLOW, DISABLE_DATA_FLOW, VERIFY_DATA_FLOW_DISABLED).
- Mapping of restore risks (REPORT_RESTORE_RISK, BLOCK_RESTORE, VERIFY_RESTORE_BLOCKED).
- Tombstone compliance and non-compliance mappings.
"""

from pathlib import Path
import sys
import unittest

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
POLICY_DIR = CURRENT_DIR

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))

from loader import PolicyLoader
from engine import (
    TreatmentEngine,
    ResourceTreatmentDecision,
    ComplianceResult,
    RequiredAction,
)
from mapper import (
    StepPhase,
    StepOperation,
    StepState,
    PERMITTED_COMBINATIONS,
    OperationSpec,
    PolicyOperationBundle,
    PolicyOperationMapper,
)


class TestPolicyOperationMapper(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = TreatmentEngine()
        cls.mapper = PolicyOperationMapper()

    # 1. Authoritative Vocabulary: Exactly 15 Permitted Combinations
    def test_01_authoritative_permitted_combinations_count(self):
        # 4 findings + 5 remediations + 6 verifications = 15 total
        self.assertEqual(len(PERMITTED_COMBINATIONS), 15)

    # 2. Strict Validation: Rejection of Invalid Combinations
    def test_02_rejection_of_invalid_combinations(self):
        # Case A: Invalid operation name
        with self.assertRaises(ValueError):
            OperationSpec(
                phase="REMEDIATION",
                system_id="account_service",
                resource_id="account_001",
                operation="PURGE_RECORD",  # Unapproved operation
                state="ABSENT",
            )

        # Case B: Invalid state for operation
        with self.assertRaises(ValueError):
            OperationSpec(
                phase="FINDING",
                system_id="account_service",
                resource_id="account_001",
                operation="REPORT_REMAINING_RECORD",
                state="ABSENT",  # Invalid state: must be PRESENT
            )

        # Case C: Invalid phase for operation
        with self.assertRaises(ValueError):
            OperationSpec(
                phase="VERIFICATION",
                system_id="account_service",
                resource_id="account_001",
                operation="REPORT_REMAINING_RECORD",  # Finding operation in verification phase
                state="PRESENT",
            )

    # 3. DELETE Violation Mapping
    def test_03_delete_violation_mapping(self):
        dec = self.engine.evaluate_resource(
            resource_id="account_005",
            observed_state="PRESENT",
            data_category="USER_PROFILE",
            evidence_id="evidence_54",
        )
        bundle = self.mapper.map_decision(dec)

        # Finding: REPORT_REMAINING_RECORD -> PRESENT (evidence_54)
        self.assertEqual(len(bundle.findings), 1)
        finding = bundle.findings[0]
        self.assertEqual(finding.phase, "FINDING")
        self.assertEqual(finding.operation, "REPORT_REMAINING_RECORD")
        self.assertEqual(finding.state, "PRESENT")
        self.assertEqual(finding.evidence_id, "evidence_54")

        # Remediation: DELETE_RECORD -> ABSENT (empty evidence_id)
        self.assertEqual(len(bundle.remediations), 1)
        remediation = bundle.remediations[0]
        self.assertEqual(remediation.phase, "REMEDIATION")
        self.assertEqual(remediation.operation, "DELETE_RECORD")
        self.assertEqual(remediation.state, "ABSENT")
        self.assertEqual(remediation.evidence_id, "")

        # Verification: VERIFY_RECORD_ABSENT -> ABSENT (empty evidence_id for future check)
        self.assertEqual(len(bundle.verifications), 1)
        verification = bundle.verifications[0]
        self.assertEqual(verification.phase, "VERIFICATION")
        self.assertEqual(verification.operation, "VERIFY_RECORD_ABSENT")
        self.assertEqual(verification.state, "ABSENT")
        self.assertEqual(verification.evidence_id, "")

    # 4. DELETE Compliant Mapping (Verification Only)
    def test_04_delete_compliant_mapping(self):
        dec = self.engine.evaluate_resource(
            resource_id="account_001",
            observed_state="ABSENT",
            data_category="USER_PROFILE",
            evidence_id="evidence_54",
        )
        bundle = self.mapper.map_decision(dec)

        # Compliant: 0 findings, 0 remediations, 1 verification citing evidence
        self.assertEqual(len(bundle.findings), 0)
        self.assertEqual(len(bundle.remediations), 0)
        self.assertEqual(len(bundle.verifications), 1)

        verification = bundle.verifications[0]
        self.assertEqual(verification.phase, "VERIFICATION")
        self.assertEqual(verification.operation, "VERIFY_RECORD_ABSENT")
        self.assertEqual(verification.state, "ABSENT")
        self.assertEqual(verification.evidence_id, "evidence_54")

    # 5. REDACT Violation Mapping (Exposed PII)
    def test_05_redact_violation_mapping(self):
        dec = self.engine.evaluate_resource(
            resource_id="support_864",
            observed_state="PRESENT",
            data_category="SUPPORT_MESSAGE",
            evidence_id="evidence_03",
        )
        bundle = self.mapper.map_decision(dec)

        # Finding: REPORT_EXPOSED_PII -> PRESENT
        self.assertEqual(len(bundle.findings), 1)
        self.assertEqual(bundle.findings[0].operation, "REPORT_EXPOSED_PII")
        self.assertEqual(bundle.findings[0].state, "PRESENT")

        # Remediation: REDACT_RECORD -> REDACTED
        self.assertEqual(len(bundle.remediations), 1)
        self.assertEqual(bundle.remediations[0].operation, "REDACT_RECORD")
        self.assertEqual(bundle.remediations[0].state, "REDACTED")

        # Verification: VERIFY_RECORD_REDACTED -> REDACTED
        self.assertEqual(len(bundle.verifications), 1)
        self.assertEqual(bundle.verifications[0].operation, "VERIFY_RECORD_REDACTED")
        self.assertEqual(bundle.verifications[0].state, "REDACTED")

    # 6. ANONYMIZE Violation Mapping
    def test_06_anonymize_violation_mapping(self):
        dec = self.engine.evaluate_resource(
            resource_id="analytics_2034",
            observed_state="PRESENT",
            data_category="ANALYTICS_PROFILE",
            evidence_id="evidence_03",
        )
        bundle = self.mapper.map_decision(dec)

        # Finding: REPORT_EXPOSED_PII -> PRESENT
        self.assertEqual(len(bundle.findings), 1)
        self.assertEqual(bundle.findings[0].operation, "REPORT_EXPOSED_PII")
        self.assertEqual(bundle.findings[0].state, "PRESENT")

        # Remediation: ANONYMIZE_RECORD -> ANONYMIZED
        self.assertEqual(len(bundle.remediations), 1)
        self.assertEqual(bundle.remediations[0].operation, "ANONYMIZE_RECORD")
        self.assertEqual(bundle.remediations[0].state, "ANONYMIZED")

        # Verification: VERIFY_RECORD_ANONYMIZED -> ANONYMIZED
        self.assertEqual(len(bundle.verifications), 1)
        self.assertEqual(bundle.verifications[0].operation, "VERIFY_RECORD_ANONYMIZED")
        self.assertEqual(bundle.verifications[0].state, "ANONYMIZED")

    # 7. RETAIN Compliant Mapping
    def test_07_retain_compliant_mapping(self):
        dec = self.engine.evaluate_resource(
            resource_id="audit_record_2016",
            observed_state="PRESENT",
            data_category="SECURITY_AUDIT_LOG",
            evidence_id="evidence_94",
        )
        bundle = self.mapper.map_decision(dec)

        # Compliant: 0 findings, 0 remediations, 1 verification (VERIFY_RECORD_PRESENT)
        self.assertEqual(len(bundle.findings), 0)
        self.assertEqual(len(bundle.remediations), 0)
        self.assertEqual(len(bundle.verifications), 1)

        ver = bundle.verifications[0]
        self.assertEqual(ver.phase, "VERIFICATION")
        self.assertEqual(ver.operation, "VERIFY_RECORD_PRESENT")
        self.assertEqual(ver.state, "PRESENT")
        self.assertEqual(ver.evidence_id, "evidence_94")

    # 8. RETAIN Violation: Missing Retained Record (No RESTORE_RECORD invention)
    def test_08_retain_missing_record_no_invented_restore(self):
        dec = self.engine.evaluate_resource(
            resource_id="audit_record_9999",
            observed_state="ABSENT",
            data_category="SECURITY_AUDIT_LOG",
        )
        bundle = self.mapper.map_decision(dec)

        # Must NOT invent RESTORE_RECORD remediation
        self.assertEqual(len(bundle.remediations), 0)
        self.assertTrue(any("Retention violation" in d for d in bundle.diagnostics))

    # 9. Active DATA_FLOW Mapping
    def test_09_active_data_flow_mapping(self):
        dec = self.engine.evaluate_resource(
            resource_id="data_flow_9522",
            observed_state="ACTIVE",
            data_category="DATA_FLOW",
            evidence_id="evidence_03",
        )
        bundle = self.mapper.map_decision(dec)

        # Finding: REPORT_ACTIVE_DATA_FLOW -> ACTIVE
        self.assertEqual(len(bundle.findings), 1)
        self.assertEqual(bundle.findings[0].operation, "REPORT_ACTIVE_DATA_FLOW")
        self.assertEqual(bundle.findings[0].state, "ACTIVE")

        # Remediation: DISABLE_DATA_FLOW -> DISABLED
        self.assertEqual(len(bundle.remediations), 1)
        self.assertEqual(bundle.remediations[0].operation, "DISABLE_DATA_FLOW")
        self.assertEqual(bundle.remediations[0].state, "DISABLED")

        # Verification: VERIFY_DATA_FLOW_DISABLED -> DISABLED
        self.assertEqual(len(bundle.verifications), 1)
        self.assertEqual(bundle.verifications[0].operation, "VERIFY_DATA_FLOW_DISABLED")
        self.assertEqual(bundle.verifications[0].state, "DISABLED")

    # 10. Restore Risk Mapping (BACKUP_ARCHIVE Active)
    def test_10_restore_risk_mapping(self):
        dec = self.engine.evaluate_resource(
            resource_id="backup_4978",
            observed_state="ACTIVE",
            data_category="BACKUP_ARCHIVE",
            evidence_id="evidence_93",
        )
        bundle = self.mapper.map_decision(dec)

        # Finding: REPORT_RESTORE_RISK -> ACTIVE
        self.assertEqual(len(bundle.findings), 1)
        self.assertEqual(bundle.findings[0].operation, "REPORT_RESTORE_RISK")
        self.assertEqual(bundle.findings[0].state, "ACTIVE")

        # Remediation: BLOCK_RESTORE -> BLOCKED
        self.assertEqual(len(bundle.remediations), 1)
        self.assertEqual(bundle.remediations[0].operation, "BLOCK_RESTORE")
        self.assertEqual(bundle.remediations[0].state, "BLOCKED")

        # Verification: VERIFY_RESTORE_BLOCKED -> BLOCKED
        self.assertEqual(len(bundle.verifications), 1)
        self.assertEqual(bundle.verifications[0].operation, "VERIFY_RESTORE_BLOCKED")
        self.assertEqual(bundle.verifications[0].state, "BLOCKED")

    # 11. Account Tombstone Compliant Mapping
    def test_11_tombstone_compliant_mapping(self):
        tombstone_data = {
            "resource_id": "tombstone_440",
            "subject_reference": "user_541",
            "name": None,
            "email": None,
        }
        dec = self.engine.evaluate_resource(
            resource_id="tombstone_440",
            observed_state="PRESENT",
            data_category="ACCOUNT_TOMBSTONE",
            evidence_id="evidence_51",
            context={"record_data": tombstone_data},
        )
        bundle = self.mapper.map_decision(dec)

        # Compliant tombstone: VERIFY_RECORD_REDACTED -> REDACTED citing evidence_51
        self.assertEqual(len(bundle.findings), 0)
        self.assertEqual(len(bundle.remediations), 0)
        self.assertEqual(len(bundle.verifications), 1)
        ver = bundle.verifications[0]
        self.assertEqual(ver.operation, "VERIFY_RECORD_REDACTED")
        self.assertEqual(ver.state, "REDACTED")
        self.assertEqual(ver.evidence_id, "evidence_51")


if __name__ == "__main__":
    unittest.main()

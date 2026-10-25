"""Tests for Phase 8 Chunk 8.5: Verification Planning.

Validates:
1. All 6 permitted challenge verification operations:
   - VERIFY_RECORD_ABSENT (ABSENT)
   - VERIFY_RECORD_PRESENT (PRESENT)
   - VERIFY_RECORD_REDACTED (REDACTED)
   - VERIFY_RECORD_ANONYMIZED (ANONYMIZED)
   - VERIFY_DATA_FLOW_DISABLED (DISABLED)
   - VERIFY_RESTORE_BLOCKED (BLOCKED)
2. COMPLETE cases: All steps are VERIFICATION and cite non-empty admissible evidence.
3. INCOMPLETE cases: Verification steps represent future checks and strictly cite evidence_id="".
4. NOT_APPLICABLE cases: Zero verification steps emitted (verifications=[]).
5. Policy-mandated retention (VERIFY_RECORD_PRESENT) and tombstone (VERIFY_RECORD_REDACTED).
6. Redaction vs Anonymization mapping.
7. Data flow stoppage (VERIFY_DATA_FLOW_DISABLED) and restore control (VERIFY_RESTORE_BLOCKED).
8. Missing evidence handling in COMPLETE cases.
9. Deterministic sorting hierarchy.
"""

from pathlib import Path
import sys
import pytest

CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from planner.models import (
    Step,
    StepPhase,
    StepOperation,
    StepState,
)
from planner.remediation import (
    RemediationCandidate,
    RemediationPlan,
)
from planner.verification import (
    VerificationCandidate,
    VerificationPlan,
    VerificationStepGenerator,
)

# Upstream Phase 7 and Phase 6 models
from status.models import (
    CaseStatusResult,
    DeletionStatus,
    RequestApplicabilityResult,
    RequestIntentCategory,
    ResourceAggregationResult,
    RemainingDataAssessmentResult,
    RecreationRiskAssessmentResult,
    ResidualFinding,
    RecreationRiskFinding,
    DecisionExplanation,
    EvidenceTrace,
)
from policy.engine import (
    ResourceTreatmentDecision,
    ComplianceResult,
    RequiredAction,
)
from policy.service import CasePolicyEvaluationResult


def _make_dummy_status_result(
    case_id: str = "case_01",
    status: DeletionStatus = DeletionStatus.COMPLETE,
    observations: list[EvidenceTrace] = None,
    residual_findings: list[ResidualFinding] = None,
    risk_findings: list[RecreationRiskFinding] = None,
) -> CaseStatusResult:
    """Helper fixture creating a realistic CaseStatusResult."""
    obs = observations or []
    rf_list = residual_findings or []
    rk_list = risk_findings or []

    remaining_res = RemainingDataAssessmentResult(
        case_id=case_id,
        has_remaining_data=bool(rf_list),
        total_residual_findings=len(rf_list),
        findings=rf_list,
    )

    risk_res = RecreationRiskAssessmentResult(
        case_id=case_id,
        has_active_risks=bool(rk_list),
        total_risk_findings=len(rk_list),
        findings=rk_list,
    )

    agg_res = ResourceAggregationResult(
        case_id=case_id,
        total_resources=len(obs) + len(rf_list) + len(rk_list),
        is_all_compliant=(status == DeletionStatus.COMPLETE),
        has_violations=(status == DeletionStatus.INCOMPLETE),
        has_indeterminate=False,
        has_retained_data=False,
        has_replica_drift=False,
    )

    app_res = RequestApplicabilityResult(
        case_id=case_id,
        is_applicable=(status != DeletionStatus.NOT_APPLICABLE),
        deletion_status="NOT_APPLICABLE" if status == DeletionStatus.NOT_APPLICABLE else None,
        intent_category=RequestIntentCategory.DELETION_AUTHORIZED if status != DeletionStatus.NOT_APPLICABLE else RequestIntentCategory.NON_DELETION_ACCESS_REQUEST,
        reason="Test applicability",
    )

    explanation = DecisionExplanation(
        case_id=case_id,
        deletion_status=status,
        status_value=status.value,
        summary_reason="Test explanation",
        primary_deciding_factor="TEST_FACTOR",
        direct_observations=obs,
        evidence_citations=[o.evidence_id for o in obs if o.evidence_id],
    )

    return CaseStatusResult(
        case_id=case_id,
        deletion_status=status,
        reason="Test case resolution",
        is_non_deletion_request=(status == DeletionStatus.NOT_APPLICABLE),
        resolution_status=status.value,
        applicability=app_res,
        resource_aggregation=agg_res,
        remaining_data=remaining_res,
        risk_assessment=risk_res,
        explanation=explanation,
    )


class TestCompleteCaseVerification:
    """Tests verifying COMPLETE cases produce evidence-backed verification steps."""

    def test_complete_case_single_record_absent(self):
        obs = [
            EvidenceTrace(
                evidence_id="evidence_54",
                resource_id="account_001",
                system_id="account_service",
                data_category="USER_PROFILE",
                observed_state="ABSENT",
                evidence_role="VERIFICATION_PROOF",
            )
        ]
        status_res = _make_dummy_status_result(status=DeletionStatus.COMPLETE, observations=obs)
        generator = VerificationStepGenerator()
        plan = generator.generate_verification(case_status_result=status_res)

        assert plan.case_status == "COMPLETE"
        assert plan.total_verifications == 1
        v = plan.verifications[0]
        assert v.step.operation == "VERIFY_RECORD_ABSENT"
        assert v.step.state == "ABSENT"
        assert v.step.evidence_id == "evidence_54"
        assert v.step.phase == "VERIFICATION"

    def test_complete_case_all_6_operations(self):
        """Verify each of the 6 allowed verification operations in a COMPLETE case."""
        decisions = [
            ResourceTreatmentDecision(resource_id="acc_01", system_id="account_service", data_category="USER_PROFILE", rule_id="rule_01", required_action="DELETE", observed_state="ABSENT", compliance_result=ComplianceResult.COMPLIANT, reason="Deleted", evidence_id="evidence_92"),
            ResourceTreatmentDecision(resource_id="log_01", system_id="security_service", data_category="SECURITY_AUDIT_LOG", rule_id="rule_09", required_action="RETAIN", observed_state="PRESENT", compliance_result=ComplianceResult.COMPLIANT, reason="Retained", evidence_id="evidence_92"),
            ResourceTreatmentDecision(resource_id="tomb_01", system_id="account_service", data_category="ACCOUNT_TOMBSTONE", rule_id="rule_04", required_action="REDACT", observed_state="REDACTED", compliance_result=ComplianceResult.COMPLIANT, reason="Redacted", evidence_id="evidence_92"),
            ResourceTreatmentDecision(resource_id="anon_01", system_id="analytics_platform", data_category="ANALYTICS_PROFILE", rule_id="rule_06", required_action="ANONYMIZE", observed_state="ANONYMIZED", compliance_result=ComplianceResult.COMPLIANT, reason="Anonymized", evidence_id="evidence_92"),
            ResourceTreatmentDecision(resource_id="flow_01", system_id="integration_service", data_category="DATA_FLOW", rule_id="rule_13", required_action="DELETE", observed_state="DISABLED", compliance_result=ComplianceResult.COMPLIANT, reason="Disabled", evidence_id="evidence_92"),
            ResourceTreatmentDecision(resource_id="bk_01", system_id="backup_service", data_category="BACKUP_ARCHIVE", rule_id="rule_14", required_action="DELETE", observed_state="BLOCKED", compliance_result=ComplianceResult.COMPLIANT, reason="Blocked", evidence_id="evidence_92"),
        ]
        policy_res = CasePolicyEvaluationResult(
            case_id="case_26",
            user_id="user_26",
            audit_at=None,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=decisions,
        )
        status_res = _make_dummy_status_result(case_id="case_26", status=DeletionStatus.COMPLETE)

        generator = VerificationStepGenerator()
        plan = generator.generate_verification(case_status_result=status_res, policy_result=policy_res)

        assert plan.total_verifications == 6
        ops = [v.step.operation for v in plan.verifications]
        assert ops == [
            "VERIFY_RECORD_ABSENT",
            "VERIFY_RECORD_PRESENT",
            "VERIFY_RECORD_REDACTED",
            "VERIFY_RECORD_ANONYMIZED",
            "VERIFY_DATA_FLOW_DISABLED",
            "VERIFY_RESTORE_BLOCKED",
        ]
        # In a COMPLETE case, all evidence_ids must be non-empty
        for v in plan.verifications:
            assert v.step.evidence_id == "evidence_92"


class TestIncompleteCaseFutureVerification:
    """Tests verifying INCOMPLETE cases produce future verification checks with evidence_id=""."""

    def test_incomplete_case_remediation_correspondence(self):
        """Proposed remediations must map to future verification checks with empty evidence_id."""
        remediations = [
            RemediationCandidate(
                step=Step(1, "REMEDIATION", "integration_service", "flow_9522", "DISABLE_DATA_FLOW", "DISABLED", ""),
                remediation_type="DISABLE_DATA_FLOW",
                system_id="integration_service",
                resource_id="flow_9522",
                target_state="DISABLED",
                data_category="DATA_FLOW",
            ),
            RemediationCandidate(
                step=Step(2, "REMEDIATION", "backup_service", "bk_001", "BLOCK_RESTORE", "BLOCKED", ""),
                remediation_type="BLOCK_RESTORE",
                system_id="backup_service",
                resource_id="bk_001",
                target_state="BLOCKED",
                data_category="BACKUP_ARCHIVE",
            ),
            RemediationCandidate(
                step=Step(3, "REMEDIATION", "account_service", "acc_005", "DELETE_RECORD", "ABSENT", ""),
                remediation_type="DELETE_RECORD",
                system_id="account_service",
                resource_id="acc_005",
                target_state="ABSENT",
                data_category="USER_PROFILE",
            ),
            RemediationCandidate(
                step=Step(4, "REMEDIATION", "account_service", "tomb_005", "REDACT_RECORD", "REDACTED", ""),
                remediation_type="REDACT_RECORD",
                system_id="account_service",
                resource_id="tomb_005",
                target_state="REDACTED",
                data_category="ACCOUNT_TOMBSTONE",
            ),
            RemediationCandidate(
                step=Step(5, "REMEDIATION", "analytics_platform", "prof_101", "ANONYMIZE_RECORD", "ANONYMIZED", ""),
                remediation_type="ANONYMIZE_RECORD",
                system_id="analytics_platform",
                resource_id="prof_101",
                target_state="ANONYMIZED",
                data_category="ANALYTICS_PROFILE",
            ),
        ]
        remed_plan = RemediationPlan(case_id="case_11", case_status="INCOMPLETE", remediations=remediations)

        # Policy decisions with a retained record
        decisions = [
            ResourceTreatmentDecision(
                resource_id="sec_01",
                system_id="security_service",
                data_category="SECURITY_AUDIT_LOG",
                rule_id="rule_09",
                required_action="RETAIN",
                observed_state="PRESENT",
                compliance_result=ComplianceResult.COMPLIANT,
                reason="Retained",
                evidence_id="evidence_sec",
            ),
        ]
        policy_res = CasePolicyEvaluationResult(
            case_id="case_11",
            user_id="user_11",
            audit_at=None,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=decisions,
        )
        status_res = _make_dummy_status_result(case_id="case_11", status=DeletionStatus.INCOMPLETE)

        generator = VerificationStepGenerator()
        plan = generator.generate_verification(
            case_status_result=status_res,
            policy_result=policy_res,
            remediation_plan=remed_plan,
        )

        assert plan.case_status == "INCOMPLETE"
        assert plan.total_verifications == 6

        # In an INCOMPLETE case, ALL verification steps must have empty string evidence_id
        for v in plan.verifications:
            assert v.step.evidence_id == ""
            assert v.is_future_check is True

        ops = [v.step.operation for v in plan.verifications]
        assert ops == [
            "VERIFY_RECORD_ABSENT",
            "VERIFY_RECORD_PRESENT",
            "VERIFY_RECORD_REDACTED",
            "VERIFY_RECORD_ANONYMIZED",
            "VERIFY_DATA_FLOW_DISABLED",
            "VERIFY_RESTORE_BLOCKED",
        ]


class TestNotApplicableAndBoundaries:
    """Tests verifying NOT_APPLICABLE and edge boundaries."""

    def test_not_applicable_produces_no_verifications(self):
        status_res = _make_dummy_status_result(status=DeletionStatus.NOT_APPLICABLE)
        generator = VerificationStepGenerator()
        plan = generator.generate_verification(case_status_result=status_res)

        assert plan.case_status == "NOT_APPLICABLE"
        assert plan.total_verifications == 0
        assert plan.steps == []

    def test_missing_evidence_in_complete_case_omitted(self):
        """In a COMPLETE case, a resource without admissible evidence is omitted from verification."""
        decisions = [
            ResourceTreatmentDecision(
                resource_id="acc_01",
                system_id="account_service",
                data_category="USER_PROFILE",
                rule_id="rule_01",
                required_action="DELETE",
                observed_state="ABSENT",
                compliance_result=ComplianceResult.COMPLIANT,
                reason="Deleted",
                evidence_id="",
            ),
        ]
        policy_res = CasePolicyEvaluationResult(
            case_id="case_x",
            user_id="user_x",
            audit_at=None,
            is_non_deletion_request=False,
            resolution_status="RESOLVED",
            decisions=decisions,
        )
        status_res = _make_dummy_status_result(case_id="case_x", status=DeletionStatus.COMPLETE)

        generator = VerificationStepGenerator()
        plan = generator.generate_verification(case_status_result=status_res, policy_result=policy_res)

        assert plan.total_verifications == 0
        assert len(plan.omitted_unproven) == 1
        assert "lacks admissible evidence ID" in plan.omitted_unproven[0]

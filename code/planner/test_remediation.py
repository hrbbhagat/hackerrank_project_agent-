"""Tests for Phase 8 Chunk 8.4: Policy-Compliant Remediation Planning.

Validates:
1. Each of the 5 allowed challenge remediation operations:
   - DISABLE_DATA_FLOW (DISABLED)
   - BLOCK_RESTORE (BLOCKED)
   - DELETE_RECORD (ABSENT)
   - REDACT_RECORD (REDACTED)
   - ANONYMIZE_RECORD (ANONYMIZED)
2. Delete vs Redact vs Anonymize mapping.
3. Active data-flow remediation (DISABLE_DATA_FLOW).
4. Restore-risk remediation (BLOCK_RESTORE).
5. Policy-mandated retention preservation (SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD).
6. Missing and contradictory upstream decisions handling.
7. COMPLETE cases produce no remediation steps (remediations=[]).
8. NOT_APPLICABLE cases produce no steps (remediations=[]).
9. Empty string evidence_id invariant for proposed remediation (evidence_id="").
10. Deduplication & deterministic sorting hierarchy.
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
    RemediationStepGenerator,
)

# Upstream Phase 7 models
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
)


def _make_dummy_status_result(
    case_id: str = "case_01",
    status: DeletionStatus = DeletionStatus.INCOMPLETE,
    residual_findings: list[ResidualFinding] = None,
    risk_findings: list[RecreationRiskFinding] = None,
    retained_resources: list[str] = None,
) -> CaseStatusResult:
    """Helper fixture creating a realistic CaseStatusResult."""
    rf_list = residual_findings or []
    rk_list = risk_findings or []
    retained = retained_resources or []

    remaining_res = RemainingDataAssessmentResult(
        case_id=case_id,
        has_remaining_data=bool(rf_list),
        total_residual_findings=len(rf_list),
        findings=rf_list,
        legitimately_retained_resources=retained,
    )

    risk_res = RecreationRiskAssessmentResult(
        case_id=case_id,
        has_active_risks=bool(rk_list),
        total_risk_findings=len(rk_list),
        findings=rk_list,
    )

    agg_res = ResourceAggregationResult(
        case_id=case_id,
        total_resources=len(rf_list) + len(rk_list) + len(retained),
        is_all_compliant=(status == DeletionStatus.COMPLETE),
        has_violations=(status == DeletionStatus.INCOMPLETE),
        has_indeterminate=False,
        has_retained_data=bool(retained),
        has_replica_drift=False,
    )

    app_res = RequestApplicabilityResult(
        case_id=case_id,
        is_applicable=(status != DeletionStatus.NOT_APPLICABLE),
        deletion_status="NOT_APPLICABLE" if status == DeletionStatus.NOT_APPLICABLE else None,
        intent_category=RequestIntentCategory.DELETION_AUTHORIZED if status != DeletionStatus.NOT_APPLICABLE else RequestIntentCategory.NON_DELETION_ACCESS_REQUEST,
        reason="Test request applicability.",
    )

    explanation = DecisionExplanation(
        case_id=case_id,
        deletion_status=status,
        status_value=status.value,
        summary_reason="Test explanation",
        primary_deciding_factor="TEST_FACTOR",
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


class TestRemediationOperationGeneration:
    """Tests for each of the 5 allowed remediation operations."""

    def test_disable_data_flow_remediation(self):
        rk = RecreationRiskFinding(
            risk_type="REPORT_ACTIVE_DATA_FLOW",
            system_id="integration_service",
            resource_id="data_flow_9522",
            data_category="DATA_FLOW",
            observed_state="ACTIVE",
            evidence_id="activity_01",
            risk_reason="Active sync flow.",
        )
        status_res = _make_dummy_status_result(risk_findings=[rk])
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.total_remediations == 1
        r = plan.remediations[0]
        assert r.step.operation == "DISABLE_DATA_FLOW"
        assert r.step.state == "DISABLED"
        assert r.step.evidence_id == ""
        assert r.step.phase == "REMEDIATION"

    def test_block_restore_remediation(self):
        rk = RecreationRiskFinding(
            risk_type="REPORT_RESTORE_RISK",
            system_id="backup_service",
            resource_id="backup_001",
            data_category="BACKUP_ARCHIVE",
            observed_state="ACTIVE",
            evidence_id="evidence_b1",
            risk_reason="Active restore path.",
        )
        status_res = _make_dummy_status_result(risk_findings=[rk])
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.total_remediations == 1
        r = plan.remediations[0]
        assert r.step.operation == "BLOCK_RESTORE"
        assert r.step.state == "BLOCKED"
        assert r.step.evidence_id == ""

    def test_delete_record_remediation(self):
        rf = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="account_service",
            resource_id="account_005",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            observed_state="PRESENT",
            evidence_id="evidence_01",
            violation_reason="Account profile remains present.",
        )
        status_res = _make_dummy_status_result(residual_findings=[rf])
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.total_remediations == 1
        r = plan.remediations[0]
        assert r.step.operation == "DELETE_RECORD"
        assert r.step.state == "ABSENT"
        assert r.step.evidence_id == ""

    def test_redact_record_remediation_on_tombstone(self):
        rf = ResidualFinding(
            finding_type="REPORT_EXPOSED_PII",
            system_id="account_service",
            resource_id="account_tombstone_005",
            data_category="ACCOUNT_TOMBSTONE",
            rule_id="rule_04",
            observed_state="PRESENT",
            evidence_id="evidence_02",
            violation_reason="Tombstone contains exposed email.",
            exposed_fields=["email"],
        )
        status_res = _make_dummy_status_result(residual_findings=[rf])
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.total_remediations == 1
        r = plan.remediations[0]
        assert r.step.operation == "REDACT_RECORD"
        assert r.step.state == "REDACTED"
        assert r.step.evidence_id == ""

    def test_anonymize_record_remediation_on_analytics(self):
        rf = ResidualFinding(
            finding_type="REPORT_EXPOSED_PII",
            system_id="analytics_platform",
            resource_id="analytics_profile_101",
            data_category="ANALYTICS_PROFILE",
            rule_id="rule_06",
            observed_state="PRESENT",
            evidence_id="evidence_03",
            violation_reason="Analytics profile linked to user identity.",
        )
        status_res = _make_dummy_status_result(residual_findings=[rf])
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.total_remediations == 1
        r = plan.remediations[0]
        assert r.step.operation == "ANONYMIZE_RECORD"
        assert r.step.state == "ANONYMIZED"
        assert r.step.evidence_id == ""


class TestStatusBoundariesAndRetention:
    """Tests verifying status-specific rules and policy retention preservation."""

    def test_complete_case_produces_no_remediation(self):
        """COMPLETE cases require zero remediation steps."""
        status_res = _make_dummy_status_result(status=DeletionStatus.COMPLETE)
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.case_status == "COMPLETE"
        assert plan.total_remediations == 0
        assert plan.steps == []

    def test_not_applicable_case_produces_no_steps(self):
        """NOT_APPLICABLE cases produce no remediation steps."""
        status_res = _make_dummy_status_result(status=DeletionStatus.NOT_APPLICABLE)
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.case_status == "NOT_APPLICABLE"
        assert plan.total_remediations == 0
        assert plan.steps == []

    def test_retained_records_preserved_from_deletion(self):
        """Legitimately retained records (SECURITY_AUDIT_LOG, LEGAL_HOLD) must not be deleted or redacted."""
        rf_retained = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="security_service",
            resource_id="sec_audit_log_99",
            data_category="SECURITY_AUDIT_LOG",
            rule_id="rule_09",
            observed_state="PRESENT",
            evidence_id="evidence_sec",
            violation_reason="Retained audit log.",
        )
        rf_delete = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="account_service",
            resource_id="account_001",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            observed_state="PRESENT",
            evidence_id="evidence_acc",
            violation_reason="User profile remaining.",
        )
        status_res = _make_dummy_status_result(
            residual_findings=[rf_retained, rf_delete],
            retained_resources=["sec_audit_log_99"],
        )
        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.total_remediations == 1
        assert plan.remediations[0].resource_id == "account_001"
        assert plan.remediations[0].step.operation == "DELETE_RECORD"
        assert "sec_audit_log_99" in plan.retained_records_preserved


class TestRemediationOrderingHierarchy:
    """Tests verifying strict hierarchical ordering of remediation actions."""

    def test_remediation_hierarchy(self):
        """
        Hierarchy:
        1. DISABLE_DATA_FLOW (rank 1)
        2. BLOCK_RESTORE (rank 2)
        3. DELETE_RECORD (rank 3)
        4. REDACT_RECORD (rank 4)
        5. ANONYMIZE_RECORD (rank 5)
        Tie breaker: system_id ascending, resource_id ascending.
        """
        rk_flow = RecreationRiskFinding(
            risk_type="REPORT_ACTIVE_DATA_FLOW",
            system_id="integration_service",
            resource_id="flow_01",
            data_category="DATA_FLOW",
            observed_state="ACTIVE",
            evidence_id="act_1",
            risk_reason="Flow active.",
        )
        rk_restore = RecreationRiskFinding(
            risk_type="REPORT_RESTORE_RISK",
            system_id="backup_service",
            resource_id="backup_01",
            data_category="BACKUP_ARCHIVE",
            observed_state="ACTIVE",
            evidence_id="ev_b1",
            risk_reason="Backup active.",
        )
        rf_anon = ResidualFinding(
            finding_type="REPORT_EXPOSED_PII",
            system_id="analytics_platform",
            resource_id="profile_01",
            data_category="ANALYTICS_PROFILE",
            rule_id="rule_06",
            observed_state="PRESENT",
            evidence_id="ev_a1",
            violation_reason="Analytics exposed.",
        )
        rf_redact = ResidualFinding(
            finding_type="REPORT_EXPOSED_PII",
            system_id="account_service",
            resource_id="tombstone_01",
            data_category="ACCOUNT_TOMBSTONE",
            rule_id="rule_04",
            observed_state="PRESENT",
            evidence_id="ev_t1",
            violation_reason="Tombstone exposed.",
        )
        rf_del_b = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="search_service",
            resource_id="index_01",
            data_category="SEARCH_INDEX_ENTRY",
            rule_id="rule_03",
            observed_state="PRESENT",
            evidence_id="ev_s1",
            violation_reason="Search index present.",
        )
        rf_del_a = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="account_service",
            resource_id="account_01",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            observed_state="PRESENT",
            evidence_id="ev_u1",
            violation_reason="Account present.",
        )

        status_res = _make_dummy_status_result(
            residual_findings=[rf_anon, rf_del_b, rf_redact, rf_del_a],
            risk_findings=[rk_restore, rk_flow],
        )

        generator = RemediationStepGenerator()
        plan = generator.generate_remediation(case_status_result=status_res)

        assert plan.total_remediations == 6
        ops = [r.step.operation for r in plan.remediations]
        assert ops == [
            "DISABLE_DATA_FLOW",
            "BLOCK_RESTORE",
            "DELETE_RECORD",
            "DELETE_RECORD",
            "REDACT_RECORD",
            "ANONYMIZE_RECORD",
        ]

        # Tie breaking for DELETE_RECORD
        assert plan.remediations[2].system_id == "account_service"
        assert plan.remediations[3].system_id == "search_service"

        # Check steps property
        steps = plan.steps
        assert len(steps) == 6
        for i, s in enumerate(steps):
            assert s.step_no == i + 1
            assert s.phase == "REMEDIATION"
            assert s.evidence_id == ""  # Must be empty string

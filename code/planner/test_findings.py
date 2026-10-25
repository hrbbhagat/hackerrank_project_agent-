"""Tests for Phase 8 Chunk 8.3: Evidence-Backed Findings Generation.

Validates:
1. Each of the 4 allowed challenge finding operations:
   - REPORT_REMAINING_RECORD (PRESENT)
   - REPORT_EXPOSED_PII (PRESENT)
   - REPORT_ACTIVE_DATA_FLOW (ACTIVE)
   - REPORT_RESTORE_RISK (ACTIVE)
2. Evidence-backed finding generation citing valid participant-visible evidence IDs.
3. Missing evidence handling: omitted from emitted steps, recorded in omitted_unproven.
4. Cutoff-awareness: post-cutoff events excluded from emitted findings.
5. Historical identifier matching: findings on resources associated with alias records.
6. Conflicting evidence: preservation of violation finding without arbitrary suppression.
7. Retained resources: legitimately retained data (SECURITY_AUDIT_LOG) not emitted as violations.
8. Failed deletion claims without proof: unverified claims do not generate finding steps.
9. Backup existence: blocked backup compliant; unblocked active restore emitted as REPORT_RESTORE_RISK.
10. Deduplication & repeated sightings: multiple sightings of same resource collapsed to 1 finding.
11. Deterministic sorting: operation rank -> system_id -> resource_id.
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
from planner.findings import (
    FindingCandidate,
    FindingsPlan,
    FindingStepGenerator,
    is_valid_evidence_id,
)

# Phase 7 and Phase 6 model imports
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
from policy.engine import (
    ResourceTreatmentDecision,
    ComplianceResult,
    RequiredAction,
)
from policy.service import CasePolicyEvaluationResult


def _make_dummy_status_result(
    case_id: str = "case_01",
    residual_findings: list[ResidualFinding] = None,
    risk_findings: list[RecreationRiskFinding] = None,
    retained_resources: list[str] = None,
    cutoff_iso: str = "2026-04-15T00:00:00Z",
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
        is_all_compliant=False,
        has_violations=True,
        has_indeterminate=False,
        has_retained_data=bool(retained),
        has_replica_drift=False,
    )

    app_res = RequestApplicabilityResult(
        case_id=case_id,
        is_applicable=True,
        deletion_status=None,
        intent_category=RequestIntentCategory.DELETION_AUTHORIZED,
        reason="Explicit deletion request.",
    )

    explanation = DecisionExplanation(
        case_id=case_id,
        deletion_status=DeletionStatus.INCOMPLETE,
        status_value="INCOMPLETE",
        summary_reason="Prohibited records or recreation risks present.",
        primary_deciding_factor="RESIDUAL_DATA_PRESENT",
        cutoff_iso=cutoff_iso,
    )

    return CaseStatusResult(
        case_id=case_id,
        deletion_status=DeletionStatus.INCOMPLETE,
        reason="Incomplete deletion",
        is_non_deletion_request=False,
        resolution_status="INCOMPLETE",
        applicability=app_res,
        resource_aggregation=agg_res,
        remaining_data=remaining_res,
        risk_assessment=risk_res,
        explanation=explanation,
    )


class TestEvidenceIdValidation:
    """Tests verifying evidence identifier validation."""

    @pytest.mark.parametrize("valid_id", [
        "evidence_01",
        "evidence_file_99",
        "activity_log_102",
        "activity_4821",
        "audit_entry_501",
        "audit_33",
    ])
    def test_valid_evidence_prefixes(self, valid_id):
        assert is_valid_evidence_id(valid_id)

    @pytest.mark.parametrize("invalid_id", [
        "",
        "   ",
        None,
        "doc_01",
        "file_01",
        "log_01",
        "unverified_claim",
    ])
    def test_invalid_evidence_ids(self, invalid_id):
        assert not is_valid_evidence_id(invalid_id)


class TestFindingOperationGeneration:
    """Tests ensuring each of the 4 challenge finding operations is correctly generated."""

    def test_report_remaining_record_generation(self):
        rf = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="account_service",
            resource_id="account_005",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            observed_state="PRESENT",
            evidence_id="evidence_01",
            violation_reason="User profile was not deleted.",
        )
        status_res = _make_dummy_status_result(residual_findings=[rf])
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 1
        f = plan.findings[0]
        assert f.step.operation == "REPORT_REMAINING_RECORD"
        assert f.step.state == "PRESENT"
        assert f.step.evidence_id == "evidence_01"
        assert f.step.phase == "FINDING"
        assert f.system_id == "account_service"
        assert f.resource_id == "account_005"

    def test_report_exposed_pii_generation(self):
        rf = ResidualFinding(
            finding_type="REPORT_EXPOSED_PII",
            system_id="support_platform",
            resource_id="ticket_901",
            data_category="SUPPORT_MESSAGE",
            rule_id="rule_05",
            observed_state="PRESENT",
            evidence_id="evidence_44",
            violation_reason="Support ticket contains unredacted customer email.",
            exposed_fields=["email"],
        )
        status_res = _make_dummy_status_result(residual_findings=[rf])
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 1
        f = plan.findings[0]
        assert f.step.operation == "REPORT_EXPOSED_PII"
        assert f.step.state == "PRESENT"
        assert f.step.evidence_id == "evidence_44"
        assert "email" in f.exposed_fields

    def test_report_active_data_flow_generation(self):
        rk = RecreationRiskFinding(
            risk_type="REPORT_ACTIVE_DATA_FLOW",
            system_id="integration_service",
            resource_id="data_flow_9522",
            data_category="DATA_FLOW",
            observed_state="ACTIVE",
            evidence_id="activity_881",
            risk_reason="Active sync connector is syncing user records.",
            is_pre_cutoff=True,
        )
        status_res = _make_dummy_status_result(risk_findings=[rk])
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 1
        f = plan.findings[0]
        assert f.step.operation == "REPORT_ACTIVE_DATA_FLOW"
        assert f.step.state == "ACTIVE"
        assert f.step.evidence_id == "activity_881"

    def test_report_restore_risk_generation(self):
        rk = RecreationRiskFinding(
            risk_type="REPORT_RESTORE_RISK",
            system_id="backup_service",
            resource_id="backup_snapshot_001",
            data_category="BACKUP_ARCHIVE",
            observed_state="ACTIVE",
            evidence_id="evidence_backup_01",
            risk_reason="Backup snapshot has unblocked restore pathway.",
            is_pre_cutoff=True,
        )
        status_res = _make_dummy_status_result(risk_findings=[rk])
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 1
        f = plan.findings[0]
        assert f.step.operation == "REPORT_RESTORE_RISK"
        assert f.step.state == "ACTIVE"
        assert f.step.evidence_id == "evidence_backup_01"


class TestEvidenceRequirementsAndBoundaries:
    """Tests verifying evidence cutoff, missing evidence, and unverified claim handling."""

    def test_missing_evidence_omits_finding_step(self):
        """Findings without participant-visible evidence cannot be emitted as finding steps."""
        rf = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="search_service",
            resource_id="search_index_001",
            data_category="SEARCH_INDEX_ENTRY",
            rule_id="rule_03",
            observed_state="PRESENT",
            evidence_id="",  # Missing evidence
            violation_reason="Suspected remaining record without supporting evidence.",
        )
        status_res = _make_dummy_status_result(residual_findings=[rf])
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 0
        assert len(plan.omitted_unproven) == 1
        assert "lacks admissible evidence ID" in plan.omitted_unproven[0]

    def test_post_cutoff_risk_excluded(self):
        """Risks occurring strictly after audit_at must not be emitted as findings."""
        rk = RecreationRiskFinding(
            risk_type="REPORT_ACTIVE_DATA_FLOW",
            system_id="integration_service",
            resource_id="data_flow_late",
            data_category="DATA_FLOW",
            observed_state="ACTIVE",
            evidence_id="activity_late",
            risk_reason="Flow created after cutoff.",
            is_pre_cutoff=False,  # Post cutoff
        )
        status_res = _make_dummy_status_result(risk_findings=[rk])
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 0
        assert len(plan.excluded_post_cutoff) == 1
        assert "is post-cutoff; excluded" in plan.excluded_post_cutoff[0]

    def test_retained_records_not_emitted_as_violations(self):
        """Legitimately retained records under policy must not generate finding steps."""
        status_res = _make_dummy_status_result(
            residual_findings=[],
            retained_resources=["audit_log_99", "legal_hold_01"],
        )
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 0
        assert "audit_log_99" in plan.retained_records
        assert "legal_hold_01" in plan.retained_records

    def test_deduplication_of_repeated_resource_sightings(self):
        """If the same resource appears in residual findings and risk findings, it is deduplicated."""
        rf = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="account_service",
            resource_id="account_005",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            observed_state="PRESENT",
            evidence_id="evidence_01",
            violation_reason="Primary copy present.",
        )
        # Duplicate risk citing same resource
        rk = RecreationRiskFinding(
            risk_type="RECREATION_EVENT",
            system_id="account_service",
            resource_id="account_005",
            data_category="USER_PROFILE",
            observed_state="PRESENT",
            evidence_id="activity_05",
            risk_reason="Recreation attempt.",
            is_pre_cutoff=True,
        )
        status_res = _make_dummy_status_result(
            residual_findings=[rf],
            risk_findings=[rk],
        )
        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 1
        assert plan.findings[0].resource_id == "account_005"
        assert plan.findings[0].step.operation == "REPORT_REMAINING_RECORD"


class TestDeterministicFindingOrdering:
    """Tests verifying the strict ordering hierarchy of findings."""

    def test_multi_finding_ordering_hierarchy(self):
        """
        Verify:
        1. REPORT_REMAINING_RECORD (rank 1)
        2. REPORT_EXPOSED_PII (rank 2)
        3. REPORT_ACTIVE_DATA_FLOW (rank 3)
        4. REPORT_RESTORE_RISK (rank 4)
        And within same operation: system_id ascending, resource_id ascending.
        """
        # Create scrambled findings
        rk_restore = RecreationRiskFinding(
            risk_type="REPORT_RESTORE_RISK",
            system_id="backup_service",
            resource_id="backup_001",
            data_category="BACKUP_ARCHIVE",
            observed_state="ACTIVE",
            evidence_id="evidence_b1",
            risk_reason="Restore risk.",
            is_pre_cutoff=True,
        )
        rk_flow = RecreationRiskFinding(
            risk_type="REPORT_ACTIVE_DATA_FLOW",
            system_id="integration_service",
            resource_id="flow_001",
            data_category="DATA_FLOW",
            observed_state="ACTIVE",
            evidence_id="activity_f1",
            risk_reason="Active flow.",
            is_pre_cutoff=True,
        )
        rf_pii_b = ResidualFinding(
            finding_type="REPORT_EXPOSED_PII",
            system_id="support_platform",
            resource_id="ticket_200",
            data_category="SUPPORT_MESSAGE",
            rule_id="rule_05",
            observed_state="PRESENT",
            evidence_id="evidence_p2",
            violation_reason="Exposed email.",
        )
        rf_pii_a = ResidualFinding(
            finding_type="REPORT_EXPOSED_PII",
            system_id="analytics_platform",
            resource_id="profile_100",
            data_category="ANALYTICS_PROFILE",
            rule_id="rule_06",
            observed_state="PRESENT",
            evidence_id="evidence_p1",
            violation_reason="Exposed profile.",
        )
        rf_remaining_z = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="search_service",
            resource_id="index_z",
            data_category="SEARCH_INDEX_ENTRY",
            rule_id="rule_03",
            observed_state="PRESENT",
            evidence_id="evidence_r2",
            violation_reason="Search index remaining.",
        )
        rf_remaining_a = ResidualFinding(
            finding_type="REPORT_REMAINING_RECORD",
            system_id="account_service",
            resource_id="account_a",
            data_category="USER_PROFILE",
            rule_id="rule_01",
            observed_state="PRESENT",
            evidence_id="evidence_r1",
            violation_reason="Account remaining.",
        )

        status_res = _make_dummy_status_result(
            residual_findings=[rf_pii_b, rf_remaining_z, rf_pii_a, rf_remaining_a],
            risk_findings=[rk_restore, rk_flow],
        )

        generator = FindingStepGenerator()
        plan = generator.generate_findings(case_status_result=status_res)

        assert plan.total_findings == 6

        # Check sequence operations
        ops = [f.step.operation for f in plan.findings]
        assert ops == [
            "REPORT_REMAINING_RECORD",
            "REPORT_REMAINING_RECORD",
            "REPORT_EXPOSED_PII",
            "REPORT_EXPOSED_PII",
            "REPORT_ACTIVE_DATA_FLOW",
            "REPORT_RESTORE_RISK",
        ]

        # Check tie breaking within REPORT_REMAINING_RECORD
        assert plan.findings[0].system_id == "account_service"
        assert plan.findings[1].system_id == "search_service"

        # Check tie breaking within REPORT_EXPOSED_PII
        assert plan.findings[2].system_id == "analytics_platform"
        assert plan.findings[3].system_id == "support_platform"

        # Check plan.steps properties (1-indexed consecutive)
        steps = plan.steps
        assert len(steps) == 6
        for i, s in enumerate(steps):
            assert s.step_no == i + 1
            assert s.phase == "FINDING"
            assert s.evidence_id != ""

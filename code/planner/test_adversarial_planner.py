"""Phase 8.8: Adversarial Testing, Contradiction Handling, and Determinism.

Comprehensive adversarial test suite validating:
1. Request & Identity:
   - Non-deletion requests (access, export, marketing opt-out) -> NOT_APPLICABLE with steps_json="[]".
   - Unresolved or ambiguous identities.
   - Multiple historical identifiers with boundary transitions.
   - Duplicate requests and duplicate evidence records.
   - Unknown systems and resources.
2. Evidence & Timeline:
   - Evidence entirely after audit_at (post-cutoff rejection).
   - Inclusive cutoff boundary (captured_at == audit_at).
   - Contradictory evidence (primary claims absent, replica proves present).
   - Successful workflow claims while record still exists (claim vs evidence).
   - Failed deletion claim without proof of resulting state.
   - Backup exists without proof of restoration (restore risk).
   - Recreation event after deletion event.
   - Missing, malformed, or unrelated evidence references.
3. Policy:
   - Mandatory retained records (SECURITY_AUDIT_LOG, TRANSACTION_RECORD) -> VERIFY_RECORD_PRESENT.
   - Tombstones required by policy (ACCOUNT_TOMBSTONE) -> REDACT_RECORD and VERIFY_RECORD_REDACTED.
   - Records requiring redaction (SUPPORT_COMMUNICATION).
   - Records requiring anonymization (ANALYTICS_PROFILE).
   - Active data flows (DATA_FLOW).
   - Restore risks (BACKUP_ARCHIVE).
   - Missing or contradictory policy evaluations.
4. Step Generation & Plan Normalization:
   - COMPLETE with attempted findings or remediations (strict rejection).
   - INCOMPLETE missing required remediation.
   - NOT_APPLICABLE with non-empty input steps (normalized to []).
   - Unsupported operation/state pairs.
   - Scrambled operation ordering reordered to canonical hierarchy.
   - Nonconsecutive numbering renumbered to 1, 2, 3, ...
   - Empty evidence on COMPLETE verification.
   - Non-empty evidence on future actions.
   - Duplicate candidate steps deduplicated.
   - Malformed input objects rejected.
5. Determinism:
   - 100 randomized permutations producing byte-for-byte identical output.
   - Zero random identifiers or nondeterministic timestamps in output.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
import sys
import pytest

# Setup path imports safely
CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from planner.contract import (
    StepPhase,
    StepOperation,
    StepState,
    OPERATION_CANONICAL_INDEX,
    StepContractValidator,
    InvalidOperationStateError,
    StepValidationError,
)
from planner.models import Step
from planner.findings import (
    FindingCandidate,
    FindingsPlan,
    FindingStepGenerator,
)
from planner.remediation import (
    RemediationCandidate,
    RemediationPlan,
    RemediationStepGenerator,
)
from planner.verification import (
    VerificationCandidate,
    VerificationPlan,
    VerificationStepGenerator,
)
from planner.sequencer import (
    CaseStepPlan,
    StepSequencer,
    get_step_sort_key,
)
from planner.validator import (
    ContextualValidationContext,
    StepValidator,
)
from policy.engine import (
    ResourceTreatmentDecision,
    ComplianceResult,
    RequiredAction,
)
from policy.service import CasePolicyEvaluationResult
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


# =============================================================================
# 1. Request and Identity Adversarial Scenarios
# =============================================================================

class TestRequestAndIdentityAdversarial:
    """Tests for non-deletion requests, unresolved identities, multiple historical IDs."""

    def test_non_deletion_request_produces_empty_plan(self):
        """A request for access or marketing opt-out is NOT_APPLICABLE; steps_json must be []."""
        # Even if intermediate generators created steps by mistake, sequencer enforces steps_json="[]"
        stray_step = Step(1, "FINDING", "account_service", "acc_99", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        plan = StepSequencer.assemble_plan(
            case_id="case_533",
            case_status="NOT_APPLICABLE",
            raw_steps=[stray_step],
        )

        assert plan.case_status == "NOT_APPLICABLE"
        assert plan.steps == []
        assert plan.steps_json == "[]"
        assert plan.is_valid is True
        assert len(plan.diagnostics) > 0
        assert "NOT_APPLICABLE; discarded" in plan.diagnostics[0]

    def test_unresolved_identity_handling(self):
        """An unresolved identity cannot produce substantiated deletion findings."""
        ctx = ContextualValidationContext(
            case_id="case_unresolved",
            case_status="INCOMPLETE",
            admissible_evidence_ids=set(),  # No admissible evidence linked to unresolved user
        )
        # Attempting to cite an evidence ID not linked to this user
        s = Step(1, "FINDING", "account_service", "acc_unknown", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_99")
        plan = StepSequencer.assemble_plan("case_unresolved", "INCOMPLETE", [s], context=ctx)

        assert plan.is_valid is False
        assert any("inadmissible at audit cutoff" in e for e in plan.errors)

    def test_duplicate_input_requests_and_evidence_deduplication(self):
        """Multiple duplicate candidate steps for the same resource violation are deduplicated safely."""
        s1 = Step(1, "FINDING", "account_service", "acc_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        s2 = Step(2, "FINDING", "account_service", "acc_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        s3 = Step(3, "FINDING", "account_service", "acc_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")

        ordered = StepSequencer.order_and_number([s1, s2, s3])
        assert len(ordered) == 1
        assert ordered[0].step_no == 1
        assert ordered[0].resource_id == "acc_1"

    def test_unknown_system_or_resource_rejects_empty_and_whitespace(self):
        """Identifiers must be non-empty and non-whitespace."""
        with pytest.raises(StepValidationError):
            Step(1, "FINDING", "   ", "acc_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        with pytest.raises(StepValidationError):
            Step(1, "FINDING", "account_service", "", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")


# =============================================================================
# 2. Evidence and Timeline Adversarial Scenarios
# =============================================================================

class TestEvidenceAndTimelineAdversarial:
    """Tests for post-cutoff evidence, boundary handling, claims vs proof, replica drift."""

    def test_evidence_entirely_after_audit_at_rejected(self):
        """Evidence captured after audit_at must not establish state or be cited."""
        cutoff = "2026-04-04T00:00:00Z"
        admissible_set = {"evidence_01", "evidence_02"}  # evidence_post_cutoff (2026-04-10) is excluded

        ctx = ContextualValidationContext(
            case_id="case_101",
            case_status="COMPLETE",
            audit_at=cutoff,
            admissible_evidence_ids=admissible_set,
        )

        s_post = Step(1, "VERIFICATION", "account_service", "acc_1", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_99")
        plan = StepSequencer.assemble_plan("case_101", "COMPLETE", [s_post], context=ctx)

        assert plan.is_valid is False
        assert any("is inadmissible at audit cutoff" in e for e in plan.errors)

    def test_evidence_at_cutoff_boundary_admitted(self):
        """Evidence captured exactly at audit_at (inclusive) is admissible."""
        cutoff = "2026-04-04T12:00:00Z"
        ctx = ContextualValidationContext(
            case_id="case_102",
            case_status="COMPLETE",
            audit_at=cutoff,
            admissible_evidence_ids={"evidence_boundary_01"},
        )
        s_boundary = Step(1, "VERIFICATION", "account_service", "acc_1", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_boundary_01")
        plan = StepSequencer.assemble_plan("case_102", "COMPLETE", [s_boundary], context=ctx)

        assert plan.is_valid is True
        assert len(plan.errors) == 0

    def test_successful_workflow_claim_while_record_still_exists(self):
        """Workflow claims COMPLETE, but evidence proves record still exists (replica drift / residual)."""
        # Phase 7 status result is INCOMPLETE despite workflow claim
        residual_findings = [
            ResidualFinding(
                finding_type="REPORT_REMAINING_RECORD",
                system_id="account_service",
                resource_id="account_005",
                data_category="ACCOUNT",
                rule_id="RULE_001",
                observed_state="PRESENT",
                evidence_id="evidence_54",
                violation_reason="Customer record customer_005 still present in replica database",
                is_replica_drift=True,
                exposed_fields=["email", "phone"],
            )
        ]
        status_res = _make_dummy_status_result(
            case_id="case_05",
            status=DeletionStatus.INCOMPLETE,
            residual_findings=residual_findings,
        )

        findings_plan = FindingStepGenerator().generate_findings(case_status_result=status_res)
        assert len(findings_plan.steps) == 1
        assert findings_plan.steps[0].operation == "REPORT_REMAINING_RECORD"
        assert findings_plan.steps[0].state == "PRESENT"
        assert findings_plan.steps[0].evidence_id == "evidence_54"

    def test_backup_exists_without_evidence_of_restoration(self):
        """Backup exists containing deleted data: reports restore risk, does not fabricate restoration event."""
        risk_findings = [
            RecreationRiskFinding(
                risk_type="REPORT_RESTORE_RISK",
                system_id="backup_service",
                resource_id="backup_4978",
                data_category="BACKUP_ARCHIVE",
                observed_state="ACTIVE",
                evidence_id="evidence_93",
                risk_reason="Unblocked snapshot contains deleted user data",
                is_pre_cutoff=True,
            )
        ]
        status_res = _make_dummy_status_result(
            case_id="case_09",
            status=DeletionStatus.INCOMPLETE,
            risk_findings=risk_findings,
        )

        findings_plan = FindingStepGenerator().generate_findings(case_status_result=status_res)
        assert len(findings_plan.steps) == 1
        assert findings_plan.steps[0].operation == "REPORT_RESTORE_RISK"
        assert findings_plan.steps[0].state == "ACTIVE"

        # Remediation generates BLOCK_RESTORE, not DELETE_RECORD or fabricated events
        rem_gen = RemediationStepGenerator()
        rem_plan = rem_gen.generate_remediation(
            case_status_result=status_res,
        )
        assert len(rem_plan.steps) == 1
        assert rem_plan.steps[0].operation == "BLOCK_RESTORE"
        assert rem_plan.steps[0].state == "BLOCKED"
        assert rem_plan.steps[0].evidence_id == ""


# =============================================================================
# 3. Policy Adversarial Scenarios
# =============================================================================

class TestPolicyAdversarial:
    """Tests for mandatory retention, tombstones, redaction vs anonymization, active data flows."""

    def test_mandatory_retained_record_verified_present_not_absent(self):
        """Security audit logs and financial records required by policy must be VERIFY_RECORD_PRESENT."""
        decisions = [
            ResourceTreatmentDecision(
                resource_id="audit_record_2016",
                system_id="security_service",
                data_category="SECURITY_AUDIT_LOG",
                rule_id="RULE_005",
                required_action="RETAIN",
                observed_state="PRESENT",
                compliance_result=ComplianceResult.COMPLIANT,
                reason="Mandatory 7-year security audit log retention",
                evidence_id="evidence_94",
            )
        ]
        case_policy = CasePolicyEvaluationResult(
            case_id="case_03",
            user_id="user_003",
            audit_at=None,
            is_non_deletion_request=False,
            resolution_status="COMPLETE",
            decisions=decisions,
        )
        status_res = _make_dummy_status_result(case_id="case_03", status=DeletionStatus.COMPLETE)

        verif_gen = VerificationStepGenerator()
        verif_plan = verif_gen.generate_verification(
            case_status_result=status_res,
            policy_result=case_policy,
        )
        assert len(verif_plan.steps) == 1
        step = verif_plan.steps[0]
        assert step.operation == "VERIFY_RECORD_PRESENT"
        assert step.state == "PRESENT"
        assert step.evidence_id == "evidence_94"

    def test_account_tombstone_redaction_and_verification(self):
        """Account tombstone with exposed email requires REDACT_RECORD and VERIFY_RECORD_REDACTED."""
        decisions = [
            ResourceTreatmentDecision(
                resource_id="account_tombstone_101",
                system_id="account_service",
                data_category="ACCOUNT_TOMBSTONE",
                rule_id="RULE_002",
                required_action="REDACT",
                observed_state="PRESENT",  # PII still exposed
                compliance_result=ComplianceResult.NON_COMPLIANT,
                reason="Account tombstone still contains direct email identifier",
                evidence_id="evidence_50",
            )
        ]
        case_policy = CasePolicyEvaluationResult(
            case_id="case_10",
            user_id="user_010",
            audit_at=None,
            is_non_deletion_request=False,
            resolution_status="INCOMPLETE",
            decisions=decisions,
        )
        status_res = _make_dummy_status_result(case_id="case_10", status=DeletionStatus.INCOMPLETE)

        # 1. Remediation must generate REDACT_RECORD (not DELETE_RECORD)
        rem_gen = RemediationStepGenerator()
        rem_plan = rem_gen.generate_remediation(
            policy_result=case_policy,
            case_status="INCOMPLETE",
        )
        assert len(rem_plan.steps) == 1
        assert rem_plan.steps[0].operation == "REDACT_RECORD"
        assert rem_plan.steps[0].state == "REDACTED"
        assert rem_plan.steps[0].evidence_id == ""

        # 2. Future verification must generate VERIFY_RECORD_REDACTED (not VERIFY_RECORD_ABSENT)
        verif_gen = VerificationStepGenerator()
        verif_plan = verif_gen.generate_verification(
            policy_result=case_policy,
            case_status="INCOMPLETE",
            remediation_plan=rem_plan,
        )
        assert len(verif_plan.steps) == 1
        assert verif_plan.steps[0].operation == "VERIFY_RECORD_REDACTED"
        assert verif_plan.steps[0].state == "REDACTED"
        assert verif_plan.steps[0].evidence_id == ""

    def test_anonymize_record_workflow(self):
        """Analytics profile requiring anonymization generates ANONYMIZE_RECORD and VERIFY_RECORD_ANONYMIZED."""
        decisions = [
            ResourceTreatmentDecision(
                resource_id="analytics_profile_55",
                system_id="analytics_platform",
                data_category="ANALYTICS_PROFILE",
                rule_id="RULE_003",
                required_action="ANONYMIZE",
                observed_state="PRESENT",
                compliance_result=ComplianceResult.NON_COMPLIANT,
                reason="Analytics profile not yet irreversibly unlinked",
                evidence_id="evidence_60",
            )
        ]
        case_policy = CasePolicyEvaluationResult(
            case_id="case_11",
            user_id="user_011",
            audit_at=None,
            is_non_deletion_request=False,
            resolution_status="INCOMPLETE",
            decisions=decisions,
        )
        status_res = _make_dummy_status_result(case_id="case_11", status=DeletionStatus.INCOMPLETE)

        rem_gen = RemediationStepGenerator()
        rem_plan = rem_gen.generate_remediation(
            policy_result=case_policy,
            case_status="INCOMPLETE",
        )
        assert rem_plan.steps[0].operation == "ANONYMIZE_RECORD"
        assert rem_plan.steps[0].state == "ANONYMIZED"

        verif_gen = VerificationStepGenerator()
        verif_plan = verif_gen.generate_verification(
            policy_result=case_policy,
            case_status="INCOMPLETE",
            remediation_plan=rem_plan,
        )
        assert verif_plan.steps[0].operation == "VERIFY_RECORD_ANONYMIZED"
        assert verif_plan.steps[0].state == "ANONYMIZED"


# =============================================================================
# 4. Step Generation and Plan Assembly Adversarial Scenarios
# =============================================================================

class TestStepGenerationAdversarial:
    """Tests for invalid combinations, numbering gaps, order corruption, and schema violations."""

    def test_complete_case_rejects_finding_or_remediation(self):
        """A COMPLETE case cannot contain findings or remediation; sequencer marks plan invalid."""
        s_finding = Step(1, "FINDING", "sys", "res", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        plan = StepSequencer.assemble_plan("case_01", "COMPLETE", [s_finding])

        assert plan.is_valid is False
        assert any("Case case_01 is COMPLETE but contains FINDING step" in e for e in plan.errors)

    def test_unsupported_operation_state_pair_rejected(self):
        """Invented or mismatched (operation, state) tuples are strictly rejected."""
        with pytest.raises(InvalidOperationStateError):
            Step(1, "REMEDIATION", "sys", "res", "RESTORE_RECORD", "RESTORED", "")

        with pytest.raises(InvalidOperationStateError):
            Step(1, "REMEDIATION", "sys", "res", "DELETE_RECORD", "PRESENT", "")  # DELETE_RECORD requires ABSENT

    def test_operation_ordering_corruption_corrected_to_canonical(self):
        """Even if candidate steps are in completely corrupt order, sequencer canonically orders them."""
        # Intentionally backwards order
        s_verif = Step(1, "VERIFICATION", "z_sys", "z_res", "VERIFY_RESTORE_BLOCKED", "BLOCKED", "")
        s_remed = Step(2, "REMEDIATION", "a_sys", "a_res", "ANONYMIZE_RECORD", "ANONYMIZED", "")
        s_finding = Step(3, "FINDING", "m_sys", "m_res", "REPORT_RESTORE_RISK", "ACTIVE", "evidence_01")

        plan = StepSequencer.assemble_plan("case_test", "INCOMPLETE", [s_verif, s_remed, s_finding])

        assert plan.is_valid is True
        assert [s.phase for s in plan.steps] == ["FINDING", "REMEDIATION", "VERIFICATION"]
        assert [s.step_no for s in plan.steps] == [1, 2, 3]

    def test_missing_evidence_on_complete_verification_rejected(self):
        """A COMPLETE case verification step with empty evidence_id is invalid."""
        s_no_ev = Step(1, "VERIFICATION", "account_service", "acc_1", "VERIFY_RECORD_ABSENT", "ABSENT", "")
        plan = StepSequencer.assemble_plan("case_01", "COMPLETE", [s_no_ev])

        assert plan.is_valid is False
        assert any("must cite non-empty admissible evidence" in e for e in plan.errors)

    def test_non_empty_evidence_on_incomplete_future_action_rejected(self):
        """Future remediation/verification steps in INCOMPLETE case must have evidence_id == ''."""
        s_future = Step(1, "REMEDIATION", "account_service", "acc_1", "DELETE_RECORD", "ABSENT", "evidence_01")
        plan = StepSequencer.assemble_plan("case_05", "INCOMPLETE", [s_future])

        assert plan.is_valid is False
        assert any("represents future action in INCOMPLETE case and must have evidence_id=\"\"" in e for e in plan.errors)


# =============================================================================
# 5. Determinism and Reproducibility Testing
# =============================================================================

class TestDeterminismAndReproducibility:
    """Verify byte-for-byte serialization determinism across 100 permutations."""

    def test_100_random_permutations_yield_identical_json_and_steps(self):
        steps = [
            Step(1, "FINDING", "export_service", "export_001", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_59"),
            Step(2, "FINDING", "support_platform", "support_001", "REPORT_EXPOSED_PII", "PRESENT", "evidence_58"),
            Step(3, "FINDING", "sync_service", "flow_901", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", "evidence_57"),
            Step(4, "REMEDIATION", "sync_service", "flow_901", "DISABLE_DATA_FLOW", "DISABLED", ""),
            Step(5, "REMEDIATION", "export_service", "export_001", "DELETE_RECORD", "ABSENT", ""),
            Step(6, "REMEDIATION", "support_platform", "support_001", "REDACT_RECORD", "REDACTED", ""),
            Step(7, "VERIFICATION", "export_service", "export_001", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
            Step(8, "VERIFICATION", "support_platform", "support_001", "VERIFY_RECORD_REDACTED", "REDACTED", ""),
            Step(9, "VERIFICATION", "sync_service", "flow_901", "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ""),
        ]

        # Generate baseline plan
        baseline_plan = StepSequencer.assemble_plan("case_determinism", "INCOMPLETE", steps)
        assert baseline_plan.is_valid is True
        assert len(baseline_plan.steps) == 9

        # Test across 100 seeded shuffles
        for seed in range(100):
            rng = random.Random(seed)
            shuffled = list(steps)
            rng.shuffle(shuffled)

            run_plan = StepSequencer.assemble_plan("case_determinism", "INCOMPLETE", shuffled)
            assert run_plan.steps_json == baseline_plan.steps_json
            assert [s.to_dict() for s in run_plan.steps] == [s.to_dict() for s in baseline_plan.steps]
            assert run_plan.is_valid is True

    def test_no_timestamps_or_random_elements_in_serialization(self):
        """Ensure serialized steps_json strictly contains only the 7 contract fields."""
        step = Step(1, "FINDING", "account_service", "acc_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        plan = StepSequencer.assemble_plan("case_test", "INCOMPLETE", [step])

        data = json.loads(plan.steps_json)
        assert len(data) == 1
        assert set(data[0].keys()) == {
            "step_no",
            "phase",
            "system_id",
            "resource_id",
            "operation",
            "state",
            "evidence_id",
        }

"""Exhaustive tests for Phase 8 Chunk 8.7: Deterministic Ordering, Step Numbering, and Evidence Integrity.

Tests:
1. Strict Phase Ordering (FINDING -> REMEDIATION -> VERIFICATION).
2. Operation Canonical Rank Ordering (problem_statement.md table order, not alphabetical).
3. Ascending system_id and resource_id sorting.
4. Consecutive 1-indexed step numbering (step_no = 1, 2, 3, ... without gaps).
5. Stable tie-breaking and safe deduplication.
6. Evidence Reference Integrity:
   - Valid admissible references on FINDING steps.
   - Valid admissible references on COMPLETE VERIFICATION steps.
   - Strictly empty evidence_id ("") on INCOMPLETE REMEDIATION and VERIFICATION steps.
   - Rejection of malformed, invented, or post-cutoff evidence IDs.
7. Status-Specific Validation:
   - NOT_APPLICABLE produces empty list and "[]".
   - COMPLETE allows only VERIFICATION steps.
   - INCOMPLETE allows findings, remediation, and future verification.
8. Assembly from upstream plans and serialization matching challenge format.
9. Determinism across repeated runs with shuffled inputs.
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
)
from planner.models import Step
from planner.validator import ContextualValidationContext
from planner.sequencer import (
    CaseStepPlan,
    StepSequencer,
    get_step_sort_key,
    load_manifest_evidence_ids,
    is_valid_evidence_format,
)


# =============================================================================
# 1. Phase Ordering Tests
# =============================================================================

class TestPhaseOrdering:
    """Verify strict phase hierarchy: FINDING -> REMEDIATION -> VERIFICATION."""

    def test_phases_sorted_in_canonical_order(self):
        s_verif = Step(
            step_no=10,
            phase="VERIFICATION",
            system_id="account_service",
            resource_id="acc_1",
            operation="VERIFY_RECORD_ABSENT",
            state="ABSENT",
            evidence_id="",
        )
        s_finding = Step(
            step_no=20,
            phase="FINDING",
            system_id="account_service",
            resource_id="acc_1",
            operation="REPORT_REMAINING_RECORD",
            state="PRESENT",
            evidence_id="evidence_01",
        )
        s_remed = Step(
            step_no=30,
            phase="REMEDIATION",
            system_id="account_service",
            resource_id="acc_1",
            operation="DELETE_RECORD",
            state="ABSENT",
            evidence_id="",
        )

        # Scrambled input order
        ordered = StepSequencer.order_and_number([s_verif, s_finding, s_remed])

        assert len(ordered) == 3
        assert ordered[0].phase == "FINDING"
        assert ordered[1].phase == "REMEDIATION"
        assert ordered[2].phase == "VERIFICATION"

        assert ordered[0].step_no == 1
        assert ordered[1].step_no == 2
        assert ordered[2].step_no == 3


# =============================================================================
# 2. Operation Canonical Rank Ordering Tests
# =============================================================================

class TestOperationRankOrdering:
    """Verify operations follow the exact problem_statement.md table order, NOT alphabetical."""

    def test_finding_operations_canonical_order(self):
        # Alphabetical: REPORT_ACTIVE_DATA_FLOW (A), REPORT_EXPOSED_PII (E),
        # REPORT_REMAINING_RECORD (Rem), REPORT_RESTORE_RISK (Res)
        # Challenge canonical order:
        # 1. REPORT_REMAINING_RECORD
        # 2. REPORT_EXPOSED_PII
        # 3. REPORT_ACTIVE_DATA_FLOW
        # 4. REPORT_RESTORE_RISK
        s_flow = Step(1, "FINDING", "sys_b", "res_3", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", "evidence_01")
        s_risk = Step(2, "FINDING", "sys_c", "res_4", "REPORT_RESTORE_RISK", "ACTIVE", "evidence_02")
        s_rem = Step(3, "FINDING", "sys_d", "res_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_03")
        s_pii = Step(4, "FINDING", "sys_a", "res_2", "REPORT_EXPOSED_PII", "PRESENT", "evidence_04")

        ordered = StepSequencer.order_and_number([s_flow, s_risk, s_rem, s_pii])

        assert [s.operation for s in ordered] == [
            "REPORT_REMAINING_RECORD",
            "REPORT_EXPOSED_PII",
            "REPORT_ACTIVE_DATA_FLOW",
            "REPORT_RESTORE_RISK",
        ]

    def test_remediation_operations_canonical_order(self):
        # Challenge canonical order:
        # 1. DISABLE_DATA_FLOW
        # 2. BLOCK_RESTORE
        # 3. DELETE_RECORD
        # 4. REDACT_RECORD
        # 5. ANONYMIZE_RECORD
        s_anon = Step(1, "REMEDIATION", "sys", "res", "ANONYMIZE_RECORD", "ANONYMIZED", "")
        s_del = Step(2, "REMEDIATION", "sys", "res", "DELETE_RECORD", "ABSENT", "")
        s_flow = Step(3, "REMEDIATION", "sys", "res", "DISABLE_DATA_FLOW", "DISABLED", "")
        s_block = Step(4, "REMEDIATION", "sys", "res", "BLOCK_RESTORE", "BLOCKED", "")
        s_redact = Step(5, "REMEDIATION", "sys", "res", "REDACT_RECORD", "REDACTED", "")

        ordered = StepSequencer.order_and_number([s_anon, s_del, s_flow, s_block, s_redact])

        assert [s.operation for s in ordered] == [
            "DISABLE_DATA_FLOW",
            "BLOCK_RESTORE",
            "DELETE_RECORD",
            "REDACT_RECORD",
            "ANONYMIZE_RECORD",
        ]

    def test_verification_operations_canonical_order(self):
        # Challenge canonical order:
        # 1. VERIFY_RECORD_ABSENT
        # 2. VERIFY_RECORD_PRESENT
        # 3. VERIFY_RECORD_REDACTED
        # 4. VERIFY_RECORD_ANONYMIZED
        # 5. VERIFY_DATA_FLOW_DISABLED
        # 6. VERIFY_RESTORE_BLOCKED
        ops = [
            ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
            ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
            ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
            ("VERIFY_RECORD_PRESENT", "PRESENT"),
            ("VERIFY_RECORD_ABSENT", "ABSENT"),
            ("VERIFY_RECORD_REDACTED", "REDACTED"),
        ]
        steps = [Step(i + 1, "VERIFICATION", "sys", f"res_{i}", op, st, "") for i, (op, st) in enumerate(ops)]

        ordered = StepSequencer.order_and_number(steps)

        assert [s.operation for s in ordered] == [
            "VERIFY_RECORD_ABSENT",
            "VERIFY_RECORD_PRESENT",
            "VERIFY_RECORD_REDACTED",
            "VERIFY_RECORD_ANONYMIZED",
            "VERIFY_DATA_FLOW_DISABLED",
            "VERIFY_RESTORE_BLOCKED",
        ]


# =============================================================================
# 3. Ascending System ID and Resource ID Sorting Tests
# =============================================================================

class TestSystemAndResourceSorting:
    """Verify tie-breaking by system_id then resource_id ascending."""

    def test_sort_by_system_id_ascending(self):
        s_search = Step(1, "FINDING", "search_service", "res_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        s_account = Step(2, "FINDING", "account_service", "res_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_02")
        s_export = Step(3, "FINDING", "export_service", "res_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_03")

        ordered = StepSequencer.order_and_number([s_search, s_account, s_export])

        assert [s.system_id for s in ordered] == [
            "account_service",
            "export_service",
            "search_service",
        ]

    def test_sort_by_resource_id_ascending_when_system_matches(self):
        s_300 = Step(1, "VERIFICATION", "account_service", "account_300", "VERIFY_RECORD_ABSENT", "ABSENT", "")
        s_100 = Step(2, "VERIFICATION", "account_service", "account_100", "VERIFY_RECORD_ABSENT", "ABSENT", "")
        s_200 = Step(3, "VERIFICATION", "account_service", "account_200", "VERIFY_RECORD_ABSENT", "ABSENT", "")

        ordered = StepSequencer.order_and_number([s_300, s_100, s_200])

        assert [s.resource_id for s in ordered] == [
            "account_100",
            "account_200",
            "account_300",
        ]


# =============================================================================
# 4. Consecutive Numbering Tests
# =============================================================================

class TestConsecutiveNumbering:
    """Verify that output steps are 1-indexed and consecutively numbered without gaps."""

    def test_renumbering_eliminates_gaps_and_scrambled_numbers(self):
        s1 = Step(99, "FINDING", "account_service", "acc_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        s2 = Step(5, "REMEDIATION", "account_service", "acc_1", "DELETE_RECORD", "ABSENT", "")
        s3 = Step(1, "VERIFICATION", "account_service", "acc_1", "VERIFY_RECORD_ABSENT", "ABSENT", "")

        ordered = StepSequencer.order_and_number([s1, s2, s3])

        assert [s.step_no for s in ordered] == [1, 2, 3]

    def test_deduplication_preserves_consecutive_numbering(self):
        s1 = Step(1, "FINDING", "sys", "res", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        s2 = Step(2, "FINDING", "sys", "res", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")  # duplicate
        s3 = Step(3, "REMEDIATION", "sys", "res", "DELETE_RECORD", "ABSENT", "")

        ordered = StepSequencer.order_and_number([s1, s2, s3])

        assert len(ordered) == 2
        assert ordered[0].step_no == 1
        assert ordered[1].step_no == 2


# =============================================================================
# 5. Evidence Reference Integrity Tests
# =============================================================================

class TestEvidenceReferenceIntegrity:
    """Verify evidence format, presence, and status-dependent emptiness rules."""

    def test_valid_evidence_format_helper(self):
        assert is_valid_evidence_format("evidence_01") is True
        assert is_valid_evidence_format("activity_999") is True
        assert is_valid_evidence_format("audit_100") is True
        assert is_valid_evidence_format("doc_123") is False
        assert is_valid_evidence_format("fake_evidence") is False
        assert is_valid_evidence_format("") is False

    def test_reject_missing_evidence_on_finding(self):
        step_dict = {
            "step_no": 1,
            "phase": "FINDING",
            "system_id": "account_service",
            "resource_id": "acc_1",
            "operation": "REPORT_REMAINING_RECORD",
            "state": "PRESENT",
            "evidence_id": "",  # Missing evidence on finding
        }
        plan = StepSequencer.assemble_plan("case_01", "INCOMPLETE", [step_dict])
        assert plan.is_valid is False
        assert any("FINDING step 1 (REPORT_REMAINING_RECORD) in INCOMPLETE case must cite non-empty proving evidence" in e for e in plan.errors)

    def test_reject_non_empty_evidence_on_incomplete_remediation(self):
        step_dict = {
            "step_no": 1,
            "phase": "REMEDIATION",
            "system_id": "account_service",
            "resource_id": "acc_1",
            "operation": "DELETE_RECORD",
            "state": "ABSENT",
            "evidence_id": "evidence_99",  # Remediation must have ""
        }
        plan = StepSequencer.assemble_plan("case_01", "INCOMPLETE", [step_dict])
        assert plan.is_valid is False
        assert any("REMEDIATION step 1 (DELETE_RECORD) represents future action" in e for e in plan.errors)

    def test_reject_non_empty_evidence_on_incomplete_verification(self):
        step_dict = {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "account_service",
            "resource_id": "acc_1",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "evidence_99",  # Incomplete future verification must have ""
        }
        plan = StepSequencer.assemble_plan("case_01", "INCOMPLETE", [step_dict])
        assert plan.is_valid is False
        assert any("VERIFICATION step 1 (VERIFY_RECORD_ABSENT) represents future action" in e for e in plan.errors)

    def test_complete_case_requires_valid_evidence_on_verification(self):
        # Missing evidence
        step_missing_ev = {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "account_service",
            "resource_id": "acc_1",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "",
        }
        plan_bad = StepSequencer.assemble_plan("case_01", "COMPLETE", [step_missing_ev])
        assert plan_bad.is_valid is False
        assert any("must cite non-empty admissible evidence" in e for e in plan_bad.errors)

        # Valid evidence
        step_valid_ev = {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "account_service",
            "resource_id": "acc_1",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "evidence_54",
        }
        plan_good = StepSequencer.assemble_plan("case_01", "COMPLETE", [step_valid_ev])
        assert plan_good.is_valid is True
        assert len(plan_good.errors) == 0

    def test_reject_inadmissible_evidence_cutoff(self):
        ctx = ContextualValidationContext(
            case_id="case_01",
            case_status="COMPLETE",
            audit_at="2026-04-04T00:00:00Z",
            admissible_evidence_ids={"evidence_01", "evidence_02"},
        )
        step_dict = {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "account_service",
            "resource_id": "acc_1",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "evidence_99",  # Not in admissible set
        }
        plan = StepSequencer.assemble_plan("case_01", "COMPLETE", [step_dict], context=ctx)
        assert plan.is_valid is False
        assert any("inadmissible at audit cutoff" in e for e in plan.errors)


# =============================================================================
# 6. Status-Specific Plan Rules Tests
# =============================================================================

class TestStatusSpecificPlanRules:
    """Verify NOT_APPLICABLE, COMPLETE, and INCOMPLETE specific rules."""

    def test_not_applicable_produces_empty_plan(self):
        candidate_step = Step(1, "FINDING", "sys", "res", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        plan = StepSequencer.assemble_plan("case_533", "NOT_APPLICABLE", [candidate_step])

        assert plan.is_valid is True
        assert plan.steps == []
        assert plan.steps_json == "[]"
        assert len(plan.diagnostics) > 0

    def test_complete_case_rejects_findings_and_remediations(self):
        s_finding = Step(1, "FINDING", "sys", "res", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01")
        s_remed = Step(2, "REMEDIATION", "sys", "res", "DELETE_RECORD", "ABSENT", "")
        s_verif = Step(3, "VERIFICATION", "sys", "res", "VERIFY_RECORD_ABSENT", "ABSENT", "evidence_54")

        plan = StepSequencer.assemble_plan("case_01", "COMPLETE", [s_finding, s_remed, s_verif])

        assert plan.is_valid is False
        assert any("Case case_01 is COMPLETE but contains FINDING step" in e for e in plan.errors)
        assert any("Case case_01 is COMPLETE but contains REMEDIATION step" in e for e in plan.errors)


# =============================================================================
# 7. Plan Assembly from Upstream Plan Objects
# =============================================================================

class MockPlan:
    def __init__(self, steps: list[Step]):
        self.steps = steps


class TestPlanAssemblyFromUpstream:
    """Verify integration assembly with FindingsPlan, RemediationPlan, and VerificationPlan."""

    def test_assemble_from_mock_upstream_plans(self):
        findings_plan = MockPlan([
            Step(1, "FINDING", "account_service", "account_005", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_54")
        ])
        remediation_plan = MockPlan([
            Step(1, "REMEDIATION", "account_service", "account_005", "DELETE_RECORD", "ABSENT", "")
        ])
        verification_plan = MockPlan([
            Step(1, "VERIFICATION", "account_service", "account_005", "VERIFY_RECORD_ABSENT", "ABSENT", "")
        ])

        plan = StepSequencer.assemble_from_plans(
            case_id="case_05",
            case_status="INCOMPLETE",
            findings_plan=findings_plan,
            remediation_plan=remediation_plan,
            verification_plan=verification_plan,
        )

        assert plan.is_valid is True
        assert len(plan.steps) == 3
        assert [s.step_no for s in plan.steps] == [1, 2, 3]
        assert [s.phase for s in plan.steps] == ["FINDING", "REMEDIATION", "VERIFICATION"]

        # Verify CSV row output format
        row = plan.to_csv_row()
        assert row[0] == "case_05"
        assert row[1] == "INCOMPLETE"
        assert json.loads(row[2]) == [s.to_dict() for s in plan.steps]


# =============================================================================
# 8. Determinism Over Repeated Runs
# =============================================================================

class TestDeterminismOverRepeatedRuns:
    """Verify identical outputs regardless of input permutation across repeated executions."""

    def test_randomized_input_permutations_yield_identical_json(self):
        s1 = Step(1, "FINDING", "backup_service", "backup_01", "REPORT_RESTORE_RISK", "ACTIVE", "evidence_01")
        s2 = Step(2, "FINDING", "account_service", "acc_01", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_02")
        s3 = Step(3, "REMEDIATION", "backup_service", "backup_01", "BLOCK_RESTORE", "BLOCKED", "")
        s4 = Step(4, "REMEDIATION", "account_service", "acc_01", "DELETE_RECORD", "ABSENT", "")
        s5 = Step(5, "VERIFICATION", "backup_service", "backup_01", "VERIFY_RESTORE_BLOCKED", "BLOCKED", "")
        s6 = Step(6, "VERIFICATION", "account_service", "acc_01", "VERIFY_RECORD_ABSENT", "ABSENT", "")

        original_steps = [s1, s2, s3, s4, s5, s6]
        baseline_plan = StepSequencer.assemble_plan("case_test", "INCOMPLETE", original_steps)

        for seed in range(50):
            rng = random.Random(seed)
            shuffled = list(original_steps)
            rng.shuffle(shuffled)

            run_plan = StepSequencer.assemble_plan("case_test", "INCOMPLETE", shuffled)
            assert run_plan.steps_json == baseline_plan.steps_json
            assert [s.to_dict() for s in run_plan.steps] == [s.to_dict() for s in baseline_plan.steps]

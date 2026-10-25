"""Phase 8 Chunk 8.9: End-to-End Step Planner Integration and Orchestration Service.

Integrates the Step Planner subsystem with Phase 7 Case Status Resolver, Phase 6
Policy Evaluation, Phase 5 Timeline Reconstruction, Phase 4 Evidence Integrator,
and Phase 3B Identity Resolver.

Coordinates:
- FindingStepGenerator (Phase 8.3)
- RemediationStepGenerator (Phase 8.4)
- VerificationStepGenerator (Phase 8.5)
- StepContractValidator & ContextualValidator (Phase 8.6)
- StepSequencer & Deterministic Ordering (Phase 8.7)

Guarantees:
1. Strict adherence to upstream Phase 7 deletion_status without re-deciding it.
2. Complete-case verification citing only admissible pre-cutoff evidence.
3. Incomplete-case lifecycle: FINDING -> REMEDIATION -> VERIFICATION with evidence_id="".
4. Not-applicable requests: steps_json = "[]".
5. 1-indexed consecutive step numbering and canonical challenge ordering.
6. Absolute determinism over repeated runs.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

# Safe path resolution avoiding shadowed 'code' package
CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
ROOT_DIR = CODE_DIR.parent

for p in [str(CODE_DIR), str(ROOT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from planner.models import Step
from planner.findings import FindingStepGenerator, FindingsPlan
from planner.remediation import RemediationStepGenerator, RemediationPlan
from planner.verification import VerificationStepGenerator, VerificationPlan
from planner.sequencer import (
    StepSequencer,
    CaseStepPlan,
    load_manifest_evidence_ids,
)
from planner.validator import (
    StepValidator,
    ContextualValidationContext,
    ValidationResult,
)
from planner.contract import (
    StepPhase,
    StepOperation,
    StepState,
    PERMITTED_OPERATIONS,
    PERMITTED_PHASES,
    StepContractValidator,
)
from status.models import CaseStatusResult, DeletionStatus
from status.pipeline import CaseStatusPipeline


@dataclass
class StepPlannerDryRunSummary:
    """Comprehensive metrics and telemetry from a full-dataset step planner dry run."""
    input_file: str
    total_input_rows: int
    successfully_planned: int
    failed_cases: int
    duplicate_case_ids: list[str] = field(default_factory=list)
    missing_case_ids: list[str] = field(default_factory=list)
    status_distribution: dict[str, int] = field(default_factory=dict)
    planning_errors_by_category: dict[str, int] = field(default_factory=dict)
    total_steps_generated: int = 0
    steps_by_phase: dict[str, int] = field(default_factory=dict)
    steps_by_operation: dict[str, int] = field(default_factory=dict)
    invalid_combinations_count: int = 0
    invalid_evidence_citations_count: int = 0
    ordering_violations_count: int = 0
    numbering_violations_count: int = 0
    elapsed_seconds: float = 0.0
    throughput_cases_per_sec: float = 0.0
    plans: list[CaseStepPlan] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


class StepPlannerOrchestrator:
    """
    Central orchestration and integration service for the Step Planner subsystem.
    
    Coordinates upstream forensic services and Step Planner generators to produce
    validated, deterministically sequenced, and consecutively numbered CaseStepPlans.
    """

    def __init__(
        self,
        pipeline: Optional[CaseStatusPipeline] = None,
        manifest_evidence_ids: Optional[set[str]] = None,
        manifest_path: Optional[Union[str, Path]] = None,
    ):
        self._pipeline = pipeline
        self.manifest_evidence_ids = manifest_evidence_ids or load_manifest_evidence_ids(manifest_path)
        
        self.finding_generator = FindingStepGenerator()
        self.remediation_generator = RemediationStepGenerator()
        self.verification_generator = VerificationStepGenerator()

    @property
    def pipeline(self) -> CaseStatusPipeline:
        if self._pipeline is None:
            self._pipeline = CaseStatusPipeline(preload_evidence=False)
        return self._pipeline

    def plan_case(
        self,
        case_status_result: CaseStatusResult,
        policy_result: Optional[Any] = None,
        timeline_result: Optional[Any] = None,
        request: Optional[dict[str, Any]] = None,
        admissible_evidence_ids: Optional[set[str]] = None,
    ) -> CaseStepPlan:
        """
        Assemble and validate a deterministic CaseStepPlan for a resolved case.

        Args:
            case_status_result: Authoritative Phase 7 resolution result.
            policy_result: Optional upstream policy evaluation result.
            timeline_result: Optional upstream forensic timeline result.
            request: Optional raw request dict (supplies fallback audit_at).
            admissible_evidence_ids: Optional set of valid participant-visible evidence IDs.
        """
        case_id = case_status_result.case_id
        status_str = case_status_result.status_value

        audit_at = None
        if case_status_result.explanation:
            audit_at = case_status_result.explanation.cutoff_iso
        if not audit_at and request:
            audit_at = request.get("audit_at")

        evidence_ids = admissible_evidence_ids or self.manifest_evidence_ids
        context = ContextualValidationContext(
            case_id=case_id,
            case_status=status_str,
            audit_at=audit_at,
            admissible_evidence_ids=evidence_ids,
        )

        # 1. NOT_APPLICABLE: Strictly [] steps
        if case_status_result.is_not_applicable:
            return StepSequencer.assemble_plan(
                case_id=case_id,
                case_status="NOT_APPLICABLE",
                raw_steps=[],
                context=context,
            )

        # 2. COMPLETE: Strictly VERIFICATION steps with admissible proving evidence
        if case_status_result.is_complete:
            v_plan = self.verification_generator.generate_verification(
                case_status_result=case_status_result,
                policy_result=policy_result,
                remediation_plan=None,
            )
            return StepSequencer.assemble_from_plans(
                case_id=case_id,
                case_status="COMPLETE",
                findings_plan=None,
                remediation_plan=None,
                verification_plan=v_plan,
                context=context,
            )

        # 3. INCOMPLETE: FINDING -> REMEDIATION -> VERIFICATION lifecycle
        f_plan = self.finding_generator.generate_findings(
            case_status_result=case_status_result,
        )
        r_plan = self.remediation_generator.generate_remediation(
            case_status_result=case_status_result,
            policy_result=policy_result,
        )
        v_plan = self.verification_generator.generate_verification(
            case_status_result=case_status_result,
            policy_result=policy_result,
            remediation_plan=r_plan,
        )

        return StepSequencer.assemble_from_plans(
            case_id=case_id,
            case_status="INCOMPLETE",
            findings_plan=f_plan,
            remediation_plan=r_plan,
            verification_plan=v_plan,
            context=context,
        )

    def plan_request(self, request: dict[str, Any]) -> tuple[CaseStepPlan, CaseStatusResult]:
        """
        Process a single deletion request through the entire forensic stack into a CaseStepPlan.

        Args:
            request: Raw request dictionary from deletion_requests.csv.

        Returns:
            Tuple of (CaseStepPlan, CaseStatusResult).
        """
        timeline_result = self.pipeline.timeline_reconstructor.reconstruct_for_request(
            request=request,
            resolver=self.pipeline.identity_resolver,
            integrator=self.pipeline.evidence_integrator,
        )

        policy_result = self.pipeline.policy_service.evaluate_timeline(
            request=request,
            timeline_result=timeline_result,
        )

        status_result = self.pipeline.status_resolver.resolve_case_status(
            request=request,
            policy_result=policy_result,
            timeline_result=timeline_result,
        )

        plan = self.plan_case(
            case_status_result=status_result,
            policy_result=policy_result,
            timeline_result=timeline_result,
            request=request,
        )

        return plan, status_result

    def run_dataset_dry_run(
        self,
        csv_path: Optional[Union[str, Path]] = None,
        max_cases: Optional[int] = None,
    ) -> StepPlannerDryRunSummary:
        """
        Execute an end-to-end dry run across the input request dataset without generating output.csv.

        Args:
            csv_path: Path to request CSV (defaults to dataset/deletion_requests.csv).
            max_cases: Optional upper limit for benchmark / testing.

        Returns:
            StepPlannerDryRunSummary with complete validation telemetry.
        """
        path = Path(csv_path or (ROOT_DIR / "dataset" / "deletion_requests.csv")).resolve()
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            requests = list(reader)

        total_input_rows = len(requests)
        if max_cases is not None:
            requests = requests[:max_cases]

        plans: list[CaseStepPlan] = []
        seen_case_ids: set[str] = set()
        duplicate_case_ids: list[str] = []
        diagnostics: list[dict[str, Any]] = []

        status_dist: dict[str, int] = {
            "COMPLETE": 0,
            "INCOMPLETE": 0,
            "NOT_APPLICABLE": 0,
        }
        steps_by_phase: dict[str, int] = {
            "FINDING": 0,
            "REMEDIATION": 0,
            "VERIFICATION": 0,
        }
        steps_by_operation: dict[str, int] = {op: 0 for op in PERMITTED_OPERATIONS}
        errors_by_category: dict[str, int] = {}

        total_steps = 0
        invalid_combinations = 0
        invalid_evidence_citations = 0
        ordering_violations = 0
        numbering_violations = 0
        failed_count = 0
        success_count = 0

        start_time = time.perf_counter()

        for req in requests:
            cid = str(req.get("case_id", "")).strip()

            if cid in seen_case_ids:
                duplicate_case_ids.append(cid)
            seen_case_ids.add(cid)

            try:
                plan, status_res = self.plan_request(req)
                plans.append(plan)

                # Record status distribution
                st = plan.case_status
                status_dist[st] = status_dist.get(st, 0) + 1

                # Check plan validity
                if not plan.is_valid or plan.errors:
                    failed_count += 1
                    for err in plan.errors:
                        cat = err.split(":")[0] if ":" in err else "ContractError"
                        errors_by_category[cat] = errors_by_category.get(cat, 0) + 1
                    diagnostics.append({
                        "case_id": cid,
                        "status": st,
                        "is_valid": plan.is_valid,
                        "errors": plan.errors,
                    })
                else:
                    success_count += 1

                # Inspect steps
                for i, s in enumerate(plan.steps):
                    total_steps += 1
                    steps_by_phase[s.phase] = steps_by_phase.get(s.phase, 0) + 1
                    steps_by_operation[s.operation] = steps_by_operation.get(s.operation, 0) + 1

                    # Check consecutive numbering
                    if s.step_no != i + 1:
                        numbering_violations += 1

                # Check ordering
                sorted_steps = StepSequencer.sort_steps(plan.steps)
                if [s.step_no for s in plan.steps] != [s.step_no for s in sorted_steps]:
                    ordering_violations += 1

            except Exception as exc:
                failed_count += 1
                cat = type(exc).__name__
                errors_by_category[cat] = errors_by_category.get(cat, 0) + 1
                diagnostics.append({
                    "case_id": cid,
                    "error": str(exc),
                    "exception_type": cat,
                })

        elapsed = time.perf_counter() - start_time
        throughput = len(plans) / elapsed if elapsed > 0 else 0.0

        return StepPlannerDryRunSummary(
            input_file=str(path),
            total_input_rows=total_input_rows,
            successfully_planned=success_count,
            failed_cases=failed_count,
            duplicate_case_ids=duplicate_case_ids,
            missing_case_ids=[],
            status_distribution=status_dist,
            planning_errors_by_category=errors_by_category,
            total_steps_generated=total_steps,
            steps_by_phase=steps_by_phase,
            steps_by_operation=steps_by_operation,
            invalid_combinations_count=invalid_combinations,
            invalid_evidence_citations_count=invalid_evidence_citations,
            ordering_violations_count=ordering_violations,
            numbering_violations_count=numbering_violations,
            elapsed_seconds=elapsed,
            throughput_cases_per_sec=throughput,
            plans=plans,
            diagnostics=diagnostics,
        )

    @staticmethod
    def verify_dry_run_determinism(
        run1: StepPlannerDryRunSummary,
        run2: StepPlannerDryRunSummary,
    ) -> tuple[bool, list[str]]:
        """
        Verify that two independent dry runs produce bit-for-bit identical step plans.

        Returns:
            Tuple of (is_deterministic, list of detected differences).
        """
        differences: list[str] = []

        if run1.total_input_rows != run2.total_input_rows:
            differences.append(
                f"Input row count mismatch: {run1.total_input_rows} vs {run2.total_input_rows}"
            )
        if len(run1.plans) != len(run2.plans):
            differences.append(
                f"Planned case count mismatch: {len(run1.plans)} vs {len(run2.plans)}"
            )
            return False, differences

        if run1.status_distribution != run2.status_distribution:
            differences.append(
                f"Status distribution mismatch: {run1.status_distribution} vs {run2.status_distribution}"
            )

        if run1.steps_by_phase != run2.steps_by_phase:
            differences.append(
                f"Step counts by phase mismatch: {run1.steps_by_phase} vs {run2.steps_by_phase}"
            )

        if run1.steps_by_operation != run2.steps_by_operation:
            differences.append(
                f"Step counts by operation mismatch: {run1.steps_by_operation} vs {run2.steps_by_operation}"
            )

        for p1, p2 in zip(run1.plans, run2.plans):
            if p1.case_id != p2.case_id:
                differences.append(f"Case ID sequence mismatch: '{p1.case_id}' vs '{p2.case_id}'")
                break
            if p1.case_status != p2.case_status:
                differences.append(
                    f"Case {p1.case_id} status mismatch: '{p1.case_status}' vs '{p2.case_status}'"
                )
            if p1.steps_json != p2.steps_json:
                differences.append(
                    f"Case {p1.case_id} steps_json mismatch:\n  Run 1: {p1.steps_json}\n  Run 2: {p2.steps_json}"
                )
            if p1.is_valid != p2.is_valid:
                differences.append(
                    f"Case {p1.case_id} is_valid mismatch: {p1.is_valid} vs {p2.is_valid}"
                )

        return (len(differences) == 0), differences

"""Phase 7 Chunk 7.9: End-to-End Batch Pipeline & Integration Boundary.

Integrates IdentityResolver (Phase 3A), EvidenceIntegrator (Phase 3B/4),
TimelineReconstructor (Phase 5), PolicyEvaluationService (Phase 6),
and CaseStatusResolver (Phase 7) into a high-performance, deterministic
case processing pipeline.

Constraints:
- Strictly deterministic; no LLM in decision loop.
- Does NOT generate output.csv (Phase 8 deliverable).
- Does NOT construct final steps_json array (Phase 8 deliverable).
- Preserves all 518 evaluation case IDs without dropping, duplicating, or reordering.
"""

from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Setup path resolution avoiding stdlib 'code' conflict
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
CODE_DIR = CURRENT_DIR.parent

for p in [
    str(CODE_DIR / "policy"),
    str(CODE_DIR / "timeline"),
    str(CODE_DIR / "identity"),
    str(CODE_DIR / "evidence"),
    str(CURRENT_DIR),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from resolver import IdentityResolver
from integration import EvidenceIntegrator
from reconstructor import ActivityIndex, TimelineReconstructor
from service import PolicyEvaluationService, CasePolicyEvaluationResult
from status.resolver import CaseStatusResolver
from status.models import CaseStatusResult, DeletionStatus


@dataclass
class BatchPipelineSummary:
    total_processed: int
    complete_count: int
    incomplete_count: int
    not_applicable_count: int
    indeterminate_count: int
    contradiction_count: int
    error_count: int
    elapsed_seconds: float
    throughput_cases_per_sec: float
    case_ids_in_order: list[str] = field(default_factory=list)
    unresolved_diagnostics: list[dict[str, Any]] = field(default_factory=list)


class CaseStatusPipeline:
    """
    Unified end-to-end processing pipeline for deletion requests.
    
    Coordinates the full forensic investigation stack:
    1. Identity resolution across snapshot and audit log history
    2. Admissible evidence collection and temporal filtering
    3. Multi-system chronological timeline reconstruction
    4. Deterministic policy evaluation and operation mapping
    5. Case-level deletion status resolution with complete audit explanations
    """

    def __init__(
        self,
        dataset_dir: Optional[Path | str] = None,
        manifest_path: Optional[Path | str] = None,
        evidence_root: Optional[Path | str] = None,
        activity_path: Optional[Path | str] = None,
        rules_path: Optional[Path | str] = None,
        preload_evidence: bool = True,
    ):
        self.dataset_dir = Path(dataset_dir or (ROOT_DIR / "dataset")).resolve()
        self.manifest_path = Path(manifest_path or (self.dataset_dir / "evidence_files.csv")).resolve()
        self.evidence_root = Path(evidence_root or (self.dataset_dir / "evidence")).resolve()
        self.activity_path = Path(activity_path or (self.dataset_dir / "system_activity.csv")).resolve()
        self.rules_path = Path(rules_path or (self.dataset_dir / "deletion_rules.csv")).resolve()

        # Initialize upstream services
        self.identity_resolver = IdentityResolver.from_directory(self.dataset_dir)
        self.evidence_integrator = EvidenceIntegrator(
            manifest_path=self.manifest_path,
            evidence_root=self.evidence_root,
        )
        if preload_evidence:
            self.evidence_integrator.preload_all()

        self.activity_index = ActivityIndex(activity_path=self.activity_path)
        self.timeline_reconstructor = TimelineReconstructor(
            activity_index=self.activity_index,
            manifest_path=self.manifest_path,
            evidence_root=self.evidence_root,
        )
        self.policy_service = PolicyEvaluationService()
        self.status_resolver = CaseStatusResolver()

    def process_request(self, request: dict[str, Any]) -> CaseStatusResult:
        """
        Process a single deletion request through the complete investigation stack.
        
        Args:
            request: Raw request dictionary containing case_id, email, requested_at,
                     reported_status, reported_at, audit_at, request_text.
                     
        Returns:
            CaseStatusResult with authoritative status, detailed explanation,
            and complete evidence provenance.
        """
        # Reconstruct timeline for resource states, flows, and restore risks
        timeline_result = self.timeline_reconstructor.reconstruct_for_request(
            request=request,
            resolver=self.identity_resolver,
            integrator=self.evidence_integrator,
        )

        # Evaluate policy compliance and operation bundles
        policy_result = self.policy_service.evaluate_timeline(
            request=request,
            timeline_result=timeline_result,
        )

        # Deterministically resolve case status and structured explanation
        return self.status_resolver.resolve_case_status(
            request=request,
            policy_result=policy_result,
            timeline_result=timeline_result,
        )

    def process_dataset(
        self,
        csv_path: Optional[Path | str] = None,
        max_cases: Optional[int] = None,
    ) -> tuple[list[CaseStatusResult], BatchPipelineSummary]:
        """
        Process an entire dataset CSV in strict order and produce structured results.
        
        Args:
            csv_path: Path to request CSV (defaults to dataset/deletion_requests.csv)
            max_cases: Optional cap on cases to process (for testing/benchmarks)
            
        Returns:
            Tuple of (list of CaseStatusResult, BatchPipelineSummary)
        """
        path = Path(csv_path or (self.dataset_dir / "deletion_requests.csv")).resolve()
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            requests = list(reader)

        if max_cases is not None:
            requests = requests[:max_cases]

        results: list[CaseStatusResult] = []
        case_ids: list[str] = []
        unresolved_diagnostics: list[dict[str, Any]] = []

        start_time = time.perf_counter()

        for req in requests:
            cid = str(req.get("case_id", "")).strip()
            case_ids.append(cid)

            result = self.process_request(req)
            results.append(result)

            # Record internal diagnostic signals for unresolved evidence or ambiguities
            has_ambiguity = (
                result.resolution_status in ("AMBIGUOUS", "UNRESOLVED")
                or result.resource_aggregation.has_indeterminate
                or bool(result.resource_aggregation.contradictions)
            )
            if has_ambiguity:
                unresolved_diagnostics.append({
                    "case_id": cid,
                    "resolution_status": result.resolution_status,
                    "indeterminate_count": len(result.resource_aggregation.indeterminate_resources),
                    "contradictions": result.resource_aggregation.contradictions,
                    "status": result.deletion_status.value,
                    "primary_reason": result.reason,
                })

        elapsed = time.perf_counter() - start_time
        throughput = len(results) / elapsed if elapsed > 0 else 0.0

        complete_count = sum(1 for r in results if r.deletion_status == DeletionStatus.COMPLETE)
        incomplete_count = sum(1 for r in results if r.deletion_status == DeletionStatus.INCOMPLETE)
        not_applicable_count = sum(1 for r in results if r.deletion_status == DeletionStatus.NOT_APPLICABLE)

        summary = BatchPipelineSummary(
            total_processed=len(results),
            complete_count=complete_count,
            incomplete_count=incomplete_count,
            not_applicable_count=not_applicable_count,
            indeterminate_count=len(unresolved_diagnostics),
            contradiction_count=sum(
                len(r.resource_aggregation.contradictions) for r in results
            ),
            error_count=0,
            elapsed_seconds=elapsed,
            throughput_cases_per_sec=throughput,
            case_ids_in_order=case_ids,
            unresolved_diagnostics=unresolved_diagnostics,
        )

        return results, summary

    @staticmethod
    def verify_determinism(
        run1: list[CaseStatusResult],
        run2: list[CaseStatusResult],
    ) -> bool:
        """Verify that two independent pipeline runs produce bit-for-bit identical results."""
        if len(run1) != len(run2):
            return False

        for r1, r2 in zip(run1, run2):
            if r1.case_id != r2.case_id:
                return False
            if r1.deletion_status != r2.deletion_status:
                return False
            if r1.reason != r2.reason:
                return False
            if r1.is_non_deletion_request != r2.is_non_deletion_request:
                return False
            if r1.resolution_status != r2.resolution_status:
                return False
            if r1.explanation.primary_deciding_factor != r2.explanation.primary_deciding_factor:
                return False
            if r1.explanation.direct_observations != r2.explanation.direct_observations:
                return False
            if r1.explanation.policy_conclusions != r2.explanation.policy_conclusions:
                return False
        return True

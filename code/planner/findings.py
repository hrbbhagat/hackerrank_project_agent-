"""Phase 8 Chunk 8.3: Evidence-Backed Findings Generation.

Generates strictly permitted, evidence-backed challenge finding steps from
upstream Phase 5 forensic timelines, Phase 4 evidence, Phase 3B identity
contexts, Phase 6 policy decisions, and Phase 7 case status results.

Permitted Finding Operations (problem_statement.md & AGENTS.md §6.4):
1. REPORT_REMAINING_RECORD (state: PRESENT) - Prohibited record still exists at cutoff.
2. REPORT_EXPOSED_PII (state: PRESENT) - Exposed PII in retained record/tombstone.
3. REPORT_ACTIVE_DATA_FLOW (state: ACTIVE) - Active process copying/recreating data.
4. REPORT_RESTORE_RISK (state: ACTIVE) - Unblocked backup/restore path can restore data.

Evidence Rules:
- Must cite a valid participant-visible file_id, activity_id, or audit_id.
- Inadmissible post-cutoff evidence is strictly excluded.
- Claims without evidence are omitted from emitted steps.
- Deduplicates repeated sightings per resource.
- Retained records under policy (SECURITY_AUDIT_LOG, compliant tombstones) are not violations.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

# Setup path imports safely without shadowed stdlib 'code' conflict
CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

try:
    from .models import (
        Step,
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
        StepValidationError,
    )
except ImportError:
    from planner.models import (
        Step,
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
        StepValidationError,
    )

from status.models import (
    CaseStatusResult,
    ResidualFinding,
    RecreationRiskFinding,
    RemainingDataAssessmentResult,
    RecreationRiskAssessmentResult,
)
from status.remaining_data import RemainingDataAssessor
from status.risk_assessment import RecreationRiskAssessor


VALID_EVIDENCE_PREFIXES: tuple[str, ...] = ("evidence_", "activity_", "audit_")

FINDING_OPERATION_ORDER: dict[str, int] = {
    StepOperation.REPORT_REMAINING_RECORD.value: 1,
    StepOperation.REPORT_EXPOSED_PII.value: 2,
    StepOperation.REPORT_ACTIVE_DATA_FLOW.value: 3,
    StepOperation.REPORT_RESTORE_RISK.value: 4,
}


def is_valid_evidence_id(evidence_id: Optional[str]) -> bool:
    """Verify that an evidence ID is non-empty and has a valid participant-visible prefix."""
    if not evidence_id or not isinstance(evidence_id, str):
        return False
    val = evidence_id.strip()
    return any(val.startswith(p) for p in VALID_EVIDENCE_PREFIXES)


@dataclass(frozen=True)
class FindingCandidate:
    """
    Internal finding representation binding a validated Step to rich forensic provenance.

    Maintains deep audit traceability without leaking extra fields into the serialized Step.
    """
    step: Step
    finding_type: str                   # REPORT_REMAINING_RECORD | REPORT_EXPOSED_PII | REPORT_ACTIVE_DATA_FLOW | REPORT_RESTORE_RISK
    system_id: str
    resource_id: str
    evidence_id: str
    observed_state: str                 # PRESENT or ACTIVE
    data_category: str
    rule_id: Optional[str] = None
    provenance_reason: str = ""
    is_replica_drift: bool = False
    exposed_fields: tuple[str, ...] = ()
    contradiction_notes: tuple[str, ...] = ()
    audit_at: Optional[str] = None

    def to_step(self, step_no: Optional[int] = None) -> Step:
        """Return the exact 7-field Step representation."""
        if step_no is not None:
            return Step(
                step_no=step_no,
                phase=self.step.phase,
                system_id=self.step.system_id,
                resource_id=self.step.resource_id,
                operation=self.step.operation,
                state=self.step.state,
                evidence_id=self.step.evidence_id,
            )
        return self.step


@dataclass(frozen=True)
class FindingsPlan:
    """
    Container for all evidence-backed findings generated for a single case.
    """
    case_id: str
    findings: list[FindingCandidate] = field(default_factory=list)
    omitted_unproven: list[str] = field(default_factory=list)
    excluded_post_cutoff: list[str] = field(default_factory=list)
    retained_records: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def steps(self) -> list[Step]:
        """Return strictly consecutive, 1-indexed Steps."""
        return [f.to_step(step_no=i + 1) for i, f in enumerate(self.findings)]

    @property
    def total_findings(self) -> int:
        return len(self.findings)


class FindingStepGenerator:
    """
    Forensic generator of evidence-backed challenge finding steps.

    Enforces:
    1. Only the 4 permitted finding operations are generated.
    2. Every finding cites admissible evidence (file_id, activity_id, or audit_id).
    3. Unproven claims and post-cutoff sightings are omitted.
    4. Deterministic sorting hierarchy:
       operation order -> system_id ascending -> resource_id ascending.
    """

    def generate_findings(
        self,
        case_status_result: Optional[CaseStatusResult] = None,
        policy_result: Optional[Any] = None,
        timeline_result: Optional[Any] = None,
        case_id: str = "",
        audit_at: Optional[str] = None,
    ) -> FindingsPlan:
        """
        Generate findings from either a pre-computed CaseStatusResult or raw policy/timeline results.
        """
        if case_status_result is not None:
            return self._generate_from_status_result(case_status_result)

        if policy_result is not None:
            return self._generate_from_policy_and_timeline(
                policy_result=policy_result,
                timeline_result=timeline_result,
                case_id=case_id or getattr(policy_result, "case_id", ""),
                audit_at=audit_at or getattr(policy_result, "audit_at", None),
            )

        raise ValueError("Either case_status_result or policy_result must be provided.")

    def _generate_from_status_result(self, res: CaseStatusResult) -> FindingsPlan:
        """Generate findings plan from an authoritative Phase 7 CaseStatusResult."""
        case_id = res.case_id
        audit_at = res.explanation.cutoff_iso if res.explanation else None

        candidates_map: dict[str, FindingCandidate] = {}
        omitted_unproven: list[str] = []
        excluded_post_cutoff: list[str] = list(res.risk_assessment.post_cutoff_events_excluded)
        retained_records: list[str] = list(res.remaining_data.legitimately_retained_resources)
        diagnostics: list[str] = list(res.diagnostics)

        # 1. Process Residual Findings (REPORT_REMAINING_RECORD, REPORT_EXPOSED_PII)
        for rf in res.remaining_data.findings:
            rid = rf.resource_id
            ev_id = rf.evidence_id.strip() if rf.evidence_id else ""

            # Check if evidence is missing or invalid
            if not is_valid_evidence_id(ev_id):
                omitted_unproven.append(
                    f"Residual violation on '{rid}' ({rf.finding_type}) lacks admissible evidence ID; omitted from findings."
                )
                continue

            op = rf.finding_type
            if op not in (
                StepOperation.REPORT_REMAINING_RECORD.value,
                StepOperation.REPORT_EXPOSED_PII.value,
            ):
                diagnostics.append(f"Unexpected residual finding type '{op}', defaulting to REPORT_REMAINING_RECORD.")
                op = StepOperation.REPORT_REMAINING_RECORD.value

            step = Step(
                step_no=1,  # Numbering assigned during sequencing
                phase=StepPhase.FINDING.value,
                system_id=rf.system_id,
                resource_id=rid,
                operation=op,
                state=StepState.PRESENT.value,
                evidence_id=ev_id,
            )

            candidate = FindingCandidate(
                step=step,
                finding_type=op,
                system_id=rf.system_id,
                resource_id=rid,
                evidence_id=ev_id,
                observed_state=StepState.PRESENT.value,
                data_category=rf.data_category,
                rule_id=rf.rule_id,
                provenance_reason=rf.violation_reason,
                is_replica_drift=rf.is_replica_drift,
                exposed_fields=tuple(rf.exposed_fields),
                contradiction_notes=(),
                audit_at=audit_at,
            )
            candidates_map[rid] = candidate

        # 2. Process Recreation and Restore Risks (REPORT_ACTIVE_DATA_FLOW, REPORT_RESTORE_RISK)
        for rk in res.risk_assessment.findings:
            rid = rk.resource_id
            ev_id = rk.evidence_id.strip() if rk.evidence_id else ""

            # Exclude post-cutoff events
            if not rk.is_pre_cutoff:
                excluded_post_cutoff.append(
                    f"Risk finding on '{rid}' ({rk.risk_type}) is post-cutoff; excluded."
                )
                continue

            # Verify evidence presence
            if not is_valid_evidence_id(ev_id):
                omitted_unproven.append(
                    f"Risk finding on '{rid}' ({rk.risk_type}) lacks admissible evidence ID; omitted from findings."
                )
                continue

            # Determine operation & state
            if rk.risk_type == StepOperation.REPORT_ACTIVE_DATA_FLOW.value:
                op = StepOperation.REPORT_ACTIVE_DATA_FLOW.value
                state = StepState.ACTIVE.value
            elif rk.risk_type == StepOperation.REPORT_RESTORE_RISK.value:
                op = StepOperation.REPORT_RESTORE_RISK.value
                state = StepState.ACTIVE.value
            elif rk.risk_type == "REPLICA_DRIFT":
                op = StepOperation.REPORT_REMAINING_RECORD.value
                state = StepState.PRESENT.value
            elif rk.risk_type == "RECREATION_EVENT":
                op = StepOperation.REPORT_REMAINING_RECORD.value
                state = StepState.PRESENT.value
            else:
                diagnostics.append(f"Unrecognized risk type '{rk.risk_type}'; skipped.")
                continue

            # Deduplicate if resource already present
            if rid in candidates_map:
                existing = candidates_map[rid]
                # If existing is already REPORT_REMAINING_RECORD, preserve it; otherwise merge
                diagnostics.append(f"Resource '{rid}' already has finding '{existing.finding_type}'; deduplicating.")
                continue

            step = Step(
                step_no=1,
                phase=StepPhase.FINDING.value,
                system_id=rk.system_id,
                resource_id=rid,
                operation=op,
                state=state,
                evidence_id=ev_id,
            )

            candidate = FindingCandidate(
                step=step,
                finding_type=op,
                system_id=rk.system_id,
                resource_id=rid,
                evidence_id=ev_id,
                observed_state=state,
                data_category=rk.data_category,
                rule_id=None,
                provenance_reason=rk.risk_reason,
                is_replica_drift=(rk.risk_type == "REPLICA_DRIFT"),
                exposed_fields=(),
                contradiction_notes=(),
                audit_at=audit_at,
            )
            candidates_map[rid] = candidate

        # 3. Deterministic Sorting Hierarchy
        # Priority: operation rank -> system_id ascending -> resource_id ascending
        sorted_candidates = sorted(
            candidates_map.values(),
            key=lambda c: (
                FINDING_OPERATION_ORDER.get(c.finding_type, 99),
                c.system_id,
                c.resource_id,
            ),
        )

        return FindingsPlan(
            case_id=case_id,
            findings=sorted_candidates,
            omitted_unproven=omitted_unproven,
            excluded_post_cutoff=excluded_post_cutoff,
            retained_records=retained_records,
            diagnostics=diagnostics,
        )

    def _generate_from_policy_and_timeline(
        self,
        policy_result: Any,
        timeline_result: Optional[Any],
        case_id: str,
        audit_at: Optional[str],
    ) -> FindingsPlan:
        """Assess policy and timeline directly using Phase 7 assessors if CaseStatusResult is absent."""
        remaining_assessor = RemainingDataAssessor()
        risk_assessor = RecreationRiskAssessor()

        remaining_res = remaining_assessor.assess_remaining_data(
            policy_result=policy_result,
            timeline_result=timeline_result,
        )
        risk_res = risk_assessor.assess_risks(
            policy_result=policy_result,
            timeline_result=timeline_result,
        )

        # Build mock CaseStatusResult shell for uniform generation
        class _StatusShim:
            def __init__(self):
                self.case_id = case_id
                self.remaining_data = remaining_res
                self.risk_assessment = risk_res
                self.diagnostics = list(policy_result.diagnostics)
                self.explanation = None

        return self._generate_from_status_result(_StatusShim())  # type: ignore

"""Phase 8 Chunk 8.5: Current-State and Future-State Verification Planning.

Generates strictly permitted verification steps according to the case status,
applicable policy outcomes, and evidence rules:

1. For COMPLETE cases:
   - Produces ONLY VERIFICATION steps (no finding, no remediation).
   - Each step cites admissible participant-visible evidence (file_id, activity_id, audit_id)
     proving the required state at audit_at.
   - Evidence ID must be non-empty and pre-cutoff.

2. For INCOMPLETE cases:
   - Generates future verification checks that must pass after proposed remediation.
   - Evidence ID is strictly empty string ("") as specified by challenge contract.
   - Covers all relevant required end-states (absent, present, redacted, anonymized,
     disabled flows, blocked restores).

3. For NOT_APPLICABLE cases:
   - Produces NO verification steps (verifications = []).

Permitted Verification Operations (problem_statement.md & AGENTS.md §6.4):
1. VERIFY_RECORD_ABSENT (state: ABSENT)
2. VERIFY_RECORD_PRESENT (state: PRESENT)
3. VERIFY_RECORD_REDACTED (state: REDACTED)
4. VERIFY_RECORD_ANONYMIZED (state: ANONYMIZED)
5. VERIFY_DATA_FLOW_DISABLED (state: DISABLED)
6. VERIFY_RESTORE_BLOCKED (state: BLOCKED)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

# Setup path imports safely
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
    from .findings import is_valid_evidence_id
    from .remediation import RemediationPlan
except ImportError:
    from planner.models import (
        Step,
        StepPhase,
        StepOperation,
        StepState,
        PERMITTED_COMBINATIONS,
        StepValidationError,
    )
    from planner.findings import is_valid_evidence_id
    from planner.remediation import RemediationPlan

from status.models import (
    CaseStatusResult,
    DeletionStatus,
)


VERIFICATION_OPERATION_ORDER: dict[str, int] = {
    StepOperation.VERIFY_RECORD_ABSENT.value: 1,
    StepOperation.VERIFY_RECORD_PRESENT.value: 2,
    StepOperation.VERIFY_RECORD_REDACTED.value: 3,
    StepOperation.VERIFY_RECORD_ANONYMIZED.value: 4,
    StepOperation.VERIFY_DATA_FLOW_DISABLED.value: 5,
    StepOperation.VERIFY_RESTORE_BLOCKED.value: 6,
}


@dataclass(frozen=True)
class VerificationCandidate:
    """
    Internal representation binding a verification Step to policy rationale and provenance.

    Maintains deep audit traceability without leaking extra fields into the serialized Step.
    """
    step: Step
    verification_type: str            # One of the 6 allowed verification operations
    system_id: str
    resource_id: str
    target_state: str                 # ABSENT | PRESENT | REDACTED | ANONYMIZED | DISABLED | BLOCKED
    data_category: str
    evidence_id: str                  # Non-empty for COMPLETE; strictly "" for INCOMPLETE
    rule_id: Optional[str] = None
    is_future_check: bool = False     # True for INCOMPLETE post-remediation checks
    rationale: str = ""

    def to_step(self, step_no: Optional[int] = None) -> Step:
        """Return the pure 7-field Step representation."""
        if step_no is not None:
            return Step(
                step_no=step_no,
                phase=self.step.phase,
                system_id=self.step.system_id,
                resource_id=self.step.resource_id,
                operation=self.step.operation,
                state=self.step.state,
                evidence_id=self.evidence_id,
            )
        return self.step


@dataclass(frozen=True)
class VerificationPlan:
    """
    Container for all verification steps for a single case.
    """
    case_id: str
    case_status: str                  # COMPLETE | INCOMPLETE | NOT_APPLICABLE
    verifications: list[VerificationCandidate] = field(default_factory=list)
    omitted_unproven: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def steps(self) -> list[Step]:
        """Return strictly consecutive, 1-indexed Steps."""
        return [v.to_step(step_no=i + 1) for i, v in enumerate(self.verifications)]

    @property
    def total_verifications(self) -> int:
        return len(self.verifications)


class VerificationStepGenerator:
    """
    Forensic planner generating current-state and future-state verification plans.

    Enforces:
    1. COMPLETE cases: All steps are VERIFICATION and must cite admissible evidence.
    2. INCOMPLETE cases: Verification steps describe future checks and must have evidence_id="".
    3. NOT_APPLICABLE cases: Zero verification steps are emitted.
    4. Deterministic sorting hierarchy:
       operation order -> system_id ascending -> resource_id ascending.
    """

    def generate_verification(
        self,
        case_status_result: Optional[CaseStatusResult] = None,
        policy_result: Optional[Any] = None,
        remediation_plan: Optional[RemediationPlan] = None,
        timeline_result: Optional[Any] = None,
        case_status: Optional[str] = None,
        case_id: str = "",
    ) -> VerificationPlan:
        """
        Generate verification plan according to case status and policy decisions.
        """
        if case_status_result is not None:
            return self._generate_from_status_result(
                case_status_result=case_status_result,
                policy_result=policy_result,
                remediation_plan=remediation_plan,
            )

        if policy_result is not None:
            status = case_status or "COMPLETE"
            return self._generate_from_policy_result(
                policy_result=policy_result,
                remediation_plan=remediation_plan,
                case_status=status,
                case_id=case_id or getattr(policy_result, "case_id", ""),
            )

        raise ValueError("Either case_status_result or policy_result must be provided.")

    def _generate_from_status_result(
        self,
        case_status_result: CaseStatusResult,
        policy_result: Optional[Any] = None,
        remediation_plan: Optional[RemediationPlan] = None,
    ) -> VerificationPlan:
        """Generate verification plan from CaseStatusResult."""
        case_id = case_status_result.case_id
        status = case_status_result.status_value

        # Status Boundary: NOT_APPLICABLE produces NO steps
        if case_status_result.is_not_applicable:
            return VerificationPlan(
                case_id=case_id,
                case_status=status,
                verifications=[],
                diagnostics=["Case is NOT_APPLICABLE; zero verification steps emitted."],
            )

        candidates_map: dict[str, VerificationCandidate] = {}
        omitted_unproven: list[str] = []
        diagnostics: list[str] = list(case_status_result.diagnostics)

        # -------------------------------------------------------------
        # Branch 1: COMPLETE Cases (Current-State Evidence-Backed Proof)
        # -------------------------------------------------------------
        if case_status_result.is_complete:
            # In a COMPLETE case, every resource decision is compliant and proven by evidence
            decisions = getattr(policy_result, "decisions", []) if policy_result else []
            
            # If policy_result is available, map each decision directly
            if decisions:
                for dec in decisions:
                    rid = dec.resource_id
                    cat = dec.data_category
                    action = dec.required_action
                    ev_id = (dec.evidence_id or "").strip()

                    # Fallback to direct evidence observations in explanation if blank
                    if not ev_id and case_status_result.explanation:
                        for obs in case_status_result.explanation.direct_observations:
                            if obs.resource_id == rid and obs.evidence_id:
                                ev_id = obs.evidence_id
                                break

                    # If still blank, fall back to case evidence citations
                    if not ev_id and case_status_result.explanation and case_status_result.explanation.evidence_citations:
                        ev_id = case_status_result.explanation.evidence_citations[0]

                    # Verify evidence is participant-visible
                    if not is_valid_evidence_id(ev_id):
                        omitted_unproven.append(
                            f"Verified resource '{rid}' in COMPLETE case lacks admissible evidence ID; omitted."
                        )
                        continue

                    # Determine verification operation
                    if cat == "DATA_FLOW":
                        op = StepOperation.VERIFY_DATA_FLOW_DISABLED.value
                        st = StepState.DISABLED.value
                    elif cat == "BACKUP_ARCHIVE":
                        op = StepOperation.VERIFY_RESTORE_BLOCKED.value
                        st = StepState.BLOCKED.value
                    elif cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD") or action == "RETAIN":
                        op = StepOperation.VERIFY_RECORD_PRESENT.value
                        st = StepState.PRESENT.value
                    elif cat == "ACCOUNT_TOMBSTONE" or action == "REDACT":
                        op = StepOperation.VERIFY_RECORD_REDACTED.value
                        st = StepState.REDACTED.value
                    elif cat in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY") or action == "ANONYMIZE":
                        op = StepOperation.VERIFY_RECORD_ANONYMIZED.value
                        st = StepState.ANONYMIZED.value
                    else:  # DELETE
                        op = StepOperation.VERIFY_RECORD_ABSENT.value
                        st = StepState.ABSENT.value

                    step = Step(
                        step_no=1,
                        phase=StepPhase.VERIFICATION.value,
                        system_id=dec.system_id,
                        resource_id=rid,
                        operation=op,
                        state=st,
                        evidence_id=ev_id,
                    )
                    candidates_map[rid] = VerificationCandidate(
                        step=step,
                        verification_type=op,
                        system_id=dec.system_id,
                        resource_id=rid,
                        target_state=st,
                        data_category=cat,
                        evidence_id=ev_id,
                        rule_id=dec.rule_id,
                        is_future_check=False,
                        rationale=f"Verified compliant state for {dec.system_id}.{rid} at cutoff.",
                    )
            else:
                # If policy_result is not passed, use explanation observations
                if case_status_result.explanation:
                    for obs in case_status_result.explanation.direct_observations:
                        rid = obs.resource_id
                        cat = obs.data_category
                        ev_id = obs.evidence_id

                        if not is_valid_evidence_id(ev_id):
                            continue

                        if cat == "DATA_FLOW":
                            op = StepOperation.VERIFY_DATA_FLOW_DISABLED.value
                            st = StepState.DISABLED.value
                        elif cat == "BACKUP_ARCHIVE":
                            op = StepOperation.VERIFY_RESTORE_BLOCKED.value
                            st = StepState.BLOCKED.value
                        elif cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
                            op = StepOperation.VERIFY_RECORD_PRESENT.value
                            st = StepState.PRESENT.value
                        elif cat == "ACCOUNT_TOMBSTONE":
                            op = StepOperation.VERIFY_RECORD_REDACTED.value
                            st = StepState.REDACTED.value
                        elif cat in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
                            op = StepOperation.VERIFY_RECORD_ANONYMIZED.value
                            st = StepState.ANONYMIZED.value
                        else:
                            op = StepOperation.VERIFY_RECORD_ABSENT.value
                            st = StepState.ABSENT.value

                        step = Step(
                            step_no=1,
                            phase=StepPhase.VERIFICATION.value,
                            system_id=obs.system_id,
                            resource_id=rid,
                            operation=op,
                            state=st,
                            evidence_id=ev_id,
                        )
                        candidates_map[rid] = VerificationCandidate(
                            step=step,
                            verification_type=op,
                            system_id=obs.system_id,
                            resource_id=rid,
                            target_state=st,
                            data_category=cat,
                            evidence_id=ev_id,
                            rule_id=None,
                            is_future_check=False,
                            rationale=f"Verified compliant state for {obs.system_id}.{rid}.",
                        )

        # -----------------------------------------------------------------
        # Branch 2: INCOMPLETE Cases (Future-State Checks with evidence_id="")
        # -----------------------------------------------------------------
        elif case_status_result.is_incomplete:
            # 1. Verification checks corresponding to proposed remediation plan
            if remediation_plan:
                for rem in remediation_plan.remediations:
                    rid = rem.resource_id
                    rem_op = rem.remediation_type

                    # Map remediation operation to future verification operation
                    if rem_op == StepOperation.DISABLE_DATA_FLOW.value:
                        verif_op = StepOperation.VERIFY_DATA_FLOW_DISABLED.value
                        verif_st = StepState.DISABLED.value
                    elif rem_op == StepOperation.BLOCK_RESTORE.value:
                        verif_op = StepOperation.VERIFY_RESTORE_BLOCKED.value
                        verif_st = StepState.BLOCKED.value
                    elif rem_op == StepOperation.REDACT_RECORD.value:
                        verif_op = StepOperation.VERIFY_RECORD_REDACTED.value
                        verif_st = StepState.REDACTED.value
                    elif rem_op == StepOperation.ANONYMIZE_RECORD.value:
                        verif_op = StepOperation.VERIFY_RECORD_ANONYMIZED.value
                        verif_st = StepState.ANONYMIZED.value
                    else:  # DELETE_RECORD
                        verif_op = StepOperation.VERIFY_RECORD_ABSENT.value
                        verif_st = StepState.ABSENT.value

                    step = Step(
                        step_no=1,
                        phase=StepPhase.VERIFICATION.value,
                        system_id=rem.system_id,
                        resource_id=rid,
                        operation=verif_op,
                        state=verif_st,
                        evidence_id="",  # Future check strictly has evidence_id=""
                    )
                    candidates_map[rid] = VerificationCandidate(
                        step=step,
                        verification_type=verif_op,
                        system_id=rem.system_id,
                        resource_id=rid,
                        target_state=verif_st,
                        data_category=rem.data_category,
                        evidence_id="",
                        rule_id=rem.rule_id,
                        is_future_check=True,
                        rationale=f"Future check confirming {rem_op} on {rem.system_id}.{rid}.",
                    )

            # 2. Plus verification of legitimately retained records and compliant tombstones
            if policy_result:
                for dec in getattr(policy_result, "decisions", []):
                    rid = dec.resource_id
                    if rid in candidates_map:
                        continue  # Already covered by remediation verification

                    cat = dec.data_category
                    action = dec.required_action

                    if dec.is_compliant:
                        if cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD") or action == "RETAIN":
                            op = StepOperation.VERIFY_RECORD_PRESENT.value
                            st = StepState.PRESENT.value
                        elif cat == "ACCOUNT_TOMBSTONE" or action == "REDACT":
                            op = StepOperation.VERIFY_RECORD_REDACTED.value
                            st = StepState.REDACTED.value
                        elif cat in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY") or action == "ANONYMIZE":
                            op = StepOperation.VERIFY_RECORD_ANONYMIZED.value
                            st = StepState.ANONYMIZED.value
                        elif cat == "DATA_FLOW":
                            op = StepOperation.VERIFY_DATA_FLOW_DISABLED.value
                            st = StepState.DISABLED.value
                        elif cat == "BACKUP_ARCHIVE":
                            op = StepOperation.VERIFY_RESTORE_BLOCKED.value
                            st = StepState.BLOCKED.value
                        else:  # DELETE
                            op = StepOperation.VERIFY_RECORD_ABSENT.value
                            st = StepState.ABSENT.value

                        step = Step(
                            step_no=1,
                            phase=StepPhase.VERIFICATION.value,
                            system_id=dec.system_id,
                            resource_id=rid,
                            operation=op,
                            state=st,
                            evidence_id="",  # In INCOMPLETE cases, all verification evidence is ""
                        )
                        candidates_map[rid] = VerificationCandidate(
                            step=step,
                            verification_type=op,
                            system_id=dec.system_id,
                            resource_id=rid,
                            target_state=st,
                            data_category=cat,
                            evidence_id="",
                            rule_id=dec.rule_id,
                            is_future_check=True,
                            rationale=f"Verification of compliant required state for {dec.system_id}.{rid}.",
                        )

        # -----------------------------------------------------------------
        # Deterministic Sorting Hierarchy
        # -----------------------------------------------------------------
        # Priority: operation rank -> system_id ascending -> resource_id ascending
        sorted_candidates = sorted(
            candidates_map.values(),
            key=lambda c: (
                VERIFICATION_OPERATION_ORDER.get(c.verification_type, 99),
                c.system_id,
                c.resource_id,
            ),
        )

        return VerificationPlan(
            case_id=case_id,
            case_status=status,
            verifications=sorted_candidates,
            omitted_unproven=omitted_unproven,
            diagnostics=diagnostics,
        )

    def _generate_from_policy_result(
        self,
        policy_result: Any,
        remediation_plan: Optional[RemediationPlan],
        case_status: str,
        case_id: str,
    ) -> VerificationPlan:
        """Fallback generation from raw policy decisions."""
        status = case_status.upper()
        if status == "NOT_APPLICABLE":
            return VerificationPlan(case_id=case_id, case_status=status, verifications=[])

        # Mock shell for uniform generation
        class _StatusShim:
            def __init__(self):
                self.case_id = case_id
                self.status_value = status
                self.is_complete = (status == "COMPLETE")
                self.is_incomplete = (status == "INCOMPLETE")
                self.is_not_applicable = (status == "NOT_APPLICABLE")
                self.diagnostics = list(getattr(policy_result, "diagnostics", []))
                self.explanation = None

        return self._generate_from_status_result(
            case_status_result=_StatusShim(),  # type: ignore
            policy_result=policy_result,
            remediation_plan=remediation_plan,
        )

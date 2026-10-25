"""Phase 8 Chunk 8.4: Policy-Compliant Remediation Planning.

Generates the complete ordered future remediation plan required for INCOMPLETE
cases from upstream Phase 6 policy decisions and Phase 7 case status results.

Permitted Remediation Operations (problem_statement.md & AGENTS.md §6.4):
1. DISABLE_DATA_FLOW (state: DISABLED) - Stop process copying/recreating data.
2. BLOCK_RESTORE (state: BLOCKED) - Prevent backup from restoring data.
3. DELETE_RECORD (state: ABSENT) - Remove prohibited record.
4. REDACT_RECORD (state: REDACTED) - Remove identifying fields from retained/tombstone record.
5. ANONYMIZE_RECORD (state: ANONYMIZED) - Irreversibly unlink record from user.

Remediation Contract Rules:
- Remediation is a plan of proposed future actions, not an evidence claim.
- For INCOMPLETE cases, phase="REMEDIATION" and evidence_id="" (strictly empty string).
- For COMPLETE cases, remediations=[] (no remediation required).
- For NOT_APPLICABLE cases, remediations=[] (no steps permitted).
- Strictly follows dependency hierarchy:
  DISABLE_DATA_FLOW -> BLOCK_RESTORE -> DELETE_RECORD -> REDACT_RECORD -> ANONYMIZE_RECORD
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
    DeletionStatus,
    ResidualFinding,
    RecreationRiskFinding,
)
from policy.mapper import PolicyOperationMapper


REMEDIATION_OPERATION_ORDER: dict[str, int] = {
    StepOperation.DISABLE_DATA_FLOW.value: 1,
    StepOperation.BLOCK_RESTORE.value: 2,
    StepOperation.DELETE_RECORD.value: 3,
    StepOperation.REDACT_RECORD.value: 4,
    StepOperation.ANONYMIZE_RECORD.value: 5,
}


@dataclass(frozen=True)
class RemediationCandidate:
    """
    Internal representation binding a proposed remediation Step to policy rationale.

    Preserves governance context without leaking extra fields into the serialized Step.
    """
    step: Step
    remediation_type: str              # DISABLE_DATA_FLOW | BLOCK_RESTORE | DELETE_RECORD | REDACT_RECORD | ANONYMIZE_RECORD
    system_id: str
    resource_id: str
    target_state: str                  # DISABLED | BLOCKED | ABSENT | REDACTED | ANONYMIZED
    data_category: str
    rule_id: Optional[str] = None
    rationale: str = ""
    is_replica: bool = False

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
                evidence_id="",  # Invariant: remediation evidence_id is strictly ""
            )
        return self.step


@dataclass(frozen=True)
class RemediationPlan:
    """
    Container for all remediation steps for a single case.
    """
    case_id: str
    case_status: str                   # COMPLETE | INCOMPLETE | NOT_APPLICABLE
    remediations: list[RemediationCandidate] = field(default_factory=list)
    retained_records_preserved: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def steps(self) -> list[Step]:
        """Return strictly consecutive, 1-indexed Steps."""
        return [r.to_step(step_no=i + 1) for i, r in enumerate(self.remediations)]

    @property
    def total_remediations(self) -> int:
        return len(self.remediations)


class RemediationStepGenerator:
    """
    Forensic planner generating safe, policy-compliant remediation plans.

    Enforces:
    1. Status boundaries: COMPLETE and NOT_APPLICABLE produce 0 remediation steps.
    2. Evidence invariants: Remediation steps strictly use empty string evidence_id="".
    3. Operation constraints: Only the 5 permitted challenge remediation operations.
    4. Dependency hierarchy:
       DISABLE_DATA_FLOW -> BLOCK_RESTORE -> DELETE_RECORD -> REDACT_RECORD -> ANONYMIZE_RECORD.
    5. Policy preservation: Retained records are preserved; never deleted.
    """

    def generate_remediation(
        self,
        case_status_result: Optional[CaseStatusResult] = None,
        policy_result: Optional[Any] = None,
        case_status: Optional[str] = None,
        case_id: str = "",
    ) -> RemediationPlan:
        """
        Generate remediation plan from either CaseStatusResult or policy result.
        """
        if case_status_result is not None:
            return self._generate_from_status_result(case_status_result)

        if policy_result is not None:
            status = case_status or "INCOMPLETE"
            return self._generate_from_policy_result(
                policy_result=policy_result,
                case_status=status,
                case_id=case_id or getattr(policy_result, "case_id", ""),
            )

        raise ValueError("Either case_status_result or policy_result must be provided.")

    def _generate_from_status_result(self, res: CaseStatusResult) -> RemediationPlan:
        """Generate remediation plan from an authoritative CaseStatusResult."""
        case_id = res.case_id
        status = res.status_value

        # Status Boundary 1: COMPLETE cases require NO remediation
        if res.is_complete:
            return RemediationPlan(
                case_id=case_id,
                case_status=status,
                remediations=[],
                retained_records_preserved=list(res.remaining_data.legitimately_retained_resources),
                diagnostics=["Case is COMPLETE; zero remediation actions required."],
            )

        # Status Boundary 2: NOT_APPLICABLE cases produce NO steps
        if res.is_not_applicable:
            return RemediationPlan(
                case_id=case_id,
                case_status=status,
                remediations=[],
                retained_records_preserved=[],
                diagnostics=["Case is NOT_APPLICABLE; steps_json must be empty."],
            )

        candidates_map: dict[str, RemediationCandidate] = {}
        retained_preserved: list[str] = list(res.remaining_data.legitimately_retained_resources)
        diagnostics: list[str] = list(res.diagnostics)

        # 1. Remediate Active Data Flows (DISABLE_DATA_FLOW)
        for rk in res.risk_assessment.findings:
            if rk.risk_type == StepOperation.REPORT_ACTIVE_DATA_FLOW.value:
                rid = rk.resource_id
                step = Step(
                    step_no=1,
                    phase=StepPhase.REMEDIATION.value,
                    system_id=rk.system_id,
                    resource_id=rid,
                    operation=StepOperation.DISABLE_DATA_FLOW.value,
                    state=StepState.DISABLED.value,
                    evidence_id="",  # Must be empty string
                )
                candidates_map[rid] = RemediationCandidate(
                    step=step,
                    remediation_type=StepOperation.DISABLE_DATA_FLOW.value,
                    system_id=rk.system_id,
                    resource_id=rid,
                    target_state=StepState.DISABLED.value,
                    data_category="DATA_FLOW",
                    rule_id=None,
                    rationale=f"Disable active data flow on {rk.system_id}.{rid} to prevent recreation.",
                    is_replica=False,
                )

        # 2. Remediate Restore Risks (BLOCK_RESTORE)
        for rk in res.risk_assessment.findings:
            if rk.risk_type == StepOperation.REPORT_RESTORE_RISK.value:
                rid = rk.resource_id
                step = Step(
                    step_no=1,
                    phase=StepPhase.REMEDIATION.value,
                    system_id=rk.system_id,
                    resource_id=rid,
                    operation=StepOperation.BLOCK_RESTORE.value,
                    state=StepState.BLOCKED.value,
                    evidence_id="",  # Must be empty string
                )
                candidates_map[rid] = RemediationCandidate(
                    step=step,
                    remediation_type=StepOperation.BLOCK_RESTORE.value,
                    system_id=rk.system_id,
                    resource_id=rid,
                    target_state=StepState.BLOCKED.value,
                    data_category="BACKUP_ARCHIVE",
                    rule_id=None,
                    rationale=f"Block restore access on {rk.system_id}.{rid} to prevent data restoration.",
                    is_replica=False,
                )

        # 3. Remediate Residual Records (DELETE_RECORD, REDACT_RECORD, ANONYMIZE_RECORD)
        for rf in res.remaining_data.findings:
            rid = rf.resource_id
            cat = rf.data_category

            # Retained records must never be remediated/deleted
            if cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
                if rid not in retained_preserved:
                    retained_preserved.append(rid)
                continue

            # Determine remediation operation based on data category and finding type
            if cat == "ACCOUNT_TOMBSTONE" or rf.finding_type == StepOperation.REPORT_EXPOSED_PII.value:
                # Check whether category requires ANONYMIZE or REDACT
                if cat in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
                    op = StepOperation.ANONYMIZE_RECORD.value
                    st = StepState.ANONYMIZED.value
                    rationale = f"Anonymize {cat} record on {rf.system_id}.{rid} to unlink personal identity."
                else:
                    op = StepOperation.REDACT_RECORD.value
                    st = StepState.REDACTED.value
                    rationale = f"Redact exposed direct PII from {cat} on {rf.system_id}.{rid}."
            else:
                op = StepOperation.DELETE_RECORD.value
                st = StepState.ABSENT.value
                rationale = f"Delete prohibited {cat} record from {rf.system_id}.{rid}."

            step = Step(
                step_no=1,
                phase=StepPhase.REMEDIATION.value,
                system_id=rf.system_id,
                resource_id=rid,
                operation=op,
                state=st,
                evidence_id="",  # Must be empty string
            )

            # Deduplicate per resource
            if rid not in candidates_map:
                candidates_map[rid] = RemediationCandidate(
                    step=step,
                    remediation_type=op,
                    system_id=rf.system_id,
                    resource_id=rid,
                    target_state=st,
                    data_category=cat,
                    rule_id=rf.rule_id,
                    rationale=rationale,
                    is_replica=rf.is_replica_drift,
                )

        # 4. Deterministic Sorting Hierarchy
        # Hierarchy: operation order -> system_id ascending -> resource_id ascending
        sorted_candidates = sorted(
            candidates_map.values(),
            key=lambda c: (
                REMEDIATION_OPERATION_ORDER.get(c.remediation_type, 99),
                c.system_id,
                c.resource_id,
            ),
        )

        return RemediationPlan(
            case_id=case_id,
            case_status=status,
            remediations=sorted_candidates,
            retained_records_preserved=retained_preserved,
            diagnostics=diagnostics,
        )

    def _generate_from_policy_result(
        self,
        policy_result: Any,
        case_status: str,
        case_id: str,
    ) -> RemediationPlan:
        """Fallback generation from raw policy decisions."""
        status = case_status.upper()
        if status in ("COMPLETE", "NOT_APPLICABLE"):
            return RemediationPlan(case_id=case_id, case_status=status, remediations=[])

        candidates_map: dict[str, RemediationCandidate] = {}
        retained_preserved: list[str] = []

        # 1. Active data flows
        for flow in getattr(policy_result, "active_data_flows", []):
            rid = flow.get("resource_id", "flow_unknown")
            sys_id = flow.get("system_id", "integration_service")
            step = Step(1, "REMEDIATION", sys_id, rid, "DISABLE_DATA_FLOW", "DISABLED", "")
            candidates_map[rid] = RemediationCandidate(
                step=step,
                remediation_type="DISABLE_DATA_FLOW",
                system_id=sys_id,
                resource_id=rid,
                target_state="DISABLED",
                data_category="DATA_FLOW",
            )

        # 2. Restore risks
        for risk in getattr(policy_result, "restore_risks", []):
            if risk.get("is_restore_blocked") is True or risk.get("observed_state") == "BLOCKED":
                continue
            rid = risk.get("resource_id", "backup_unknown")
            sys_id = risk.get("system_id", "backup_service")
            step = Step(1, "REMEDIATION", sys_id, rid, "BLOCK_RESTORE", "BLOCKED", "")
            candidates_map[rid] = RemediationCandidate(
                step=step,
                remediation_type="BLOCK_RESTORE",
                system_id=sys_id,
                resource_id=rid,
                target_state="BLOCKED",
                data_category="BACKUP_ARCHIVE",
            )

        # 3. Resource decisions
        for dec in getattr(policy_result, "decisions", []):
            rid = dec.resource_id
            cat = dec.data_category
            action = dec.required_action

            if cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD") or action == "RETAIN":
                retained_preserved.append(rid)
                continue

            if dec.compliance_result.value == "NON_COMPLIANT":
                if cat in ("DATA_FLOW", "BACKUP_ARCHIVE"):
                    continue

                if action == "REDACT" or cat == "ACCOUNT_TOMBSTONE":
                    op = "REDACT_RECORD"
                    st = "REDACTED"
                elif action == "ANONYMIZE":
                    op = "ANONYMIZE_RECORD"
                    st = "ANONYMIZED"
                else:
                    op = "DELETE_RECORD"
                    st = "ABSENT"

                step = Step(1, "REMEDIATION", dec.system_id, rid, op, st, "")
                if rid not in candidates_map:
                    candidates_map[rid] = RemediationCandidate(
                        step=step,
                        remediation_type=op,
                        system_id=dec.system_id,
                        resource_id=rid,
                        target_state=st,
                        data_category=cat,
                        rule_id=dec.rule_id,
                    )

        sorted_candidates = sorted(
            candidates_map.values(),
            key=lambda c: (
                REMEDIATION_OPERATION_ORDER.get(c.remediation_type, 99),
                c.system_id,
                c.resource_id,
            ),
        )

        return RemediationPlan(
            case_id=case_id,
            case_status=status,
            remediations=sorted_candidates,
            retained_records_preserved=retained_preserved,
        )

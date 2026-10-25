"""Phase 8 Chunk 8.7: Deterministic Ordering, Step Numbering, and Evidence Integrity.

Implements the authoritative final step-plan normalization, ordering, numbering,
and evidence-reference validation layer according to problem_statement.md and
AGENTS.md §6.3-6.6.

Ordering Contract:
1. Strict Phase Order:
   FINDING (1) -> REMEDIATION (2) -> VERIFICATION (3)
2. Operation Rank within Phase (problem_statement.md "Allowed Operations" table):
   Findings:
     1. REPORT_REMAINING_RECORD
     2. REPORT_EXPOSED_PII
     3. REPORT_ACTIVE_DATA_FLOW
     4. REPORT_RESTORE_RISK
   Remediation:
     1. DISABLE_DATA_FLOW
     2. BLOCK_RESTORE
     3. DELETE_RECORD
     4. REDACT_RECORD
     5. ANONYMIZE_RECORD
   Verification:
     1. VERIFY_RECORD_ABSENT
     2. VERIFY_RECORD_PRESENT
     3. VERIFY_RECORD_REDACTED
     4. VERIFY_RECORD_ANONYMIZED
     5. VERIFY_DATA_FLOW_DISABLED
     6. VERIFY_RESTORE_BLOCKED
3. Ascending system_id (lexicographical).
4. Ascending resource_id (lexicographical).
5. Stable Tie-Breaker: ascending evidence_id (lexicographical).

Step Numbering:
- Assigned strictly AFTER ordering and deduplication: step_no = 1, 2, 3, ...
- 1-indexed, consecutive, matching array order. Zero gaps.

Evidence Reference Integrity:
- Findings: must cite admissible evidence (file_id, activity_id, audit_id).
- COMPLETE verification: must cite admissible evidence.
- INCOMPLETE remediation and verification: evidence_id is strictly "" (empty string).
- Rejects malformed or invented references.
- Rejects post-cutoff citations.

Status Enforcement:
- COMPLETE: strictly VERIFICATION steps only.
- INCOMPLETE: FINDING -> REMEDIATION -> VERIFICATION steps.
- NOT_APPLICABLE: strictly empty array (steps_json = "[]").
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

# Setup path imports safely
CURRENT_DIR = Path(__file__).resolve().parent
CODE_DIR = CURRENT_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

try:
    from .contract import (
        StepPhase,
        StepOperation,
        StepState,
        REQUIRED_STEP_FIELDS,
        PERMITTED_PHASES,
        PERMITTED_OPERATIONS,
        PERMITTED_STATES,
        PERMITTED_COMBINATIONS,
        OPERATION_CANONICAL_INDEX,
        StepValidationError,
        StepContractValidator,
    )
    from .models import Step
    from .validator import (
        StepValidator,
        ValidationResult,
        ContextualValidationContext,
    )
except ImportError:
    from contract import (
        StepPhase,
        StepOperation,
        StepState,
        REQUIRED_STEP_FIELDS,
        PERMITTED_PHASES,
        PERMITTED_OPERATIONS,
        PERMITTED_STATES,
        PERMITTED_COMBINATIONS,
        OPERATION_CANONICAL_INDEX,
        StepValidationError,
        StepContractValidator,
    )
    from models import Step
    from validator import (
        StepValidator,
        ValidationResult,
        ContextualValidationContext,
    )


# Phase canonical rank
PHASE_CANONICAL_RANK: dict[str, int] = {
    StepPhase.FINDING.value: 1,
    StepPhase.REMEDIATION.value: 2,
    StepPhase.VERIFICATION.value: 3,
}

# Recognized admissible evidence prefixes
VALID_EVIDENCE_PREFIXES: tuple[str, ...] = (
    "evidence_",
    "activity_",
    "audit_",
)


def is_valid_evidence_format(evidence_id: str) -> bool:
    """Return True iff evidence_id has a recognized challenge evidence prefix."""
    if not evidence_id or not isinstance(evidence_id, str):
        return False
    val = evidence_id.strip()
    return any(val.startswith(p) for p in VALID_EVIDENCE_PREFIXES)


def get_step_sort_key(step: Step) -> tuple[int, int, str, str, str, str]:
    """
    Produce the canonical, deterministic sorting tuple for an atomic Step.

    Sort Order:
    1. Phase order: FINDING (1) < REMEDIATION (2) < VERIFICATION (3)
    2. Operation rank within phase (1..4 for findings, 1..5 for remediation, 1..6 for verification)
    3. Ascending system_id
    4. Ascending resource_id
    5. Ascending state
    6. Ascending evidence_id (tie-breaker)
    """
    phase_rank = PHASE_CANONICAL_RANK.get(step.phase, 99)
    op_rank = OPERATION_CANONICAL_INDEX.get(step.operation, 99)
    return (
        phase_rank,
        op_rank,
        step.system_id,
        step.resource_id,
        step.state,
        step.evidence_id,
    )


@dataclass(frozen=True)
class CaseStepPlan:
    """
    Immutable representation of the final assembled, ordered, numbered,
    and serialized step plan for an individual deletion request.

    Fields:
        case_id: Unique request identifier.
        case_status: COMPLETE | INCOMPLETE | NOT_APPLICABLE.
        steps: Sequenced, consecutively numbered list of Step objects.
        steps_json: Deterministically serialized JSON array matching challenge format.
        is_valid: True iff all ordering, schema, and status validations pass.
        errors: List of contract or integrity errors.
        diagnostics: Traceability and diagnostic messages.
    """
    case_id: str
    case_status: str
    steps: list[Step] = field(default_factory=list)
    steps_json: str = "[]"
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_csv_row(self) -> tuple[str, str, str]:
        """Return the exact (case_id, deletion_status, steps_json) tuple for output.csv."""
        return (self.case_id, self.case_status, self.steps_json)

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation for logging and diagnostics."""
        return {
            "case_id": self.case_id,
            "case_status": self.case_status,
            "step_count": len(self.steps),
            "is_valid": self.is_valid,
            "errors": self.errors,
            "steps": [s.to_dict() for s in self.steps],
        }


class StepSequencer:
    """
    Authoritative step sequencing, numbering, deduplication, and evidence integrity engine.
    """

    @classmethod
    def deduplicate_steps(cls, steps: Sequence[Step]) -> list[Step]:
        """
        Deduplicate identical candidate steps deterministically.

        Preserves first occurrence order before sorting.
        Two steps are identical if they share (phase, operation, system_id, resource_id, state, evidence_id).
        """
        seen: set[tuple[str, str, str, str, str, str]] = set()
        deduped: list[Step] = []

        for s in steps:
            key = (s.phase, s.operation, s.system_id, s.resource_id, s.state, s.evidence_id)
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        return deduped

    @classmethod
    def sort_steps(cls, steps: Sequence[Step]) -> list[Step]:
        """
        Sort steps strictly according to the challenge canonical ordering contract.

        Sort Hierarchy:
        1. Phase (FINDING -> REMEDIATION -> VERIFICATION)
        2. Operation Canonical Index (per problem_statement.md table)
        3. system_id (ascending)
        4. resource_id (ascending)
        5. evidence_id (ascending tie-breaker)
        """
        return sorted(steps, key=get_step_sort_key)

    @classmethod
    def renumber_steps(cls, steps: Sequence[Step]) -> list[Step]:
        """
        Re-number steps consecutively from 1 matching array position.

        Guarantees step_no = 1, 2, 3, ... with zero gaps.
        """
        numbered: list[Step] = []
        for i, s in enumerate(steps):
            numbered.append(Step(
                step_no=i + 1,
                phase=s.phase,
                system_id=s.system_id,
                resource_id=s.resource_id,
                operation=s.operation,
                state=s.state,
                evidence_id=s.evidence_id,
            ))
        return numbered

    @classmethod
    def order_and_number(cls, steps: Sequence[Step]) -> list[Step]:
        """Deduplicate, canonically sort, and consecutively number a sequence of steps."""
        deduped = cls.deduplicate_steps(steps)
        sorted_steps = cls.sort_steps(deduped)
        return cls.renumber_steps(sorted_steps)

    @classmethod
    def serialize_steps(cls, steps: Sequence[Step]) -> str:
        """
        Serialize steps to a deterministic compact JSON string array matching sample_output.csv.

        Uses compact separators without unnecessary whitespace.
        """
        if not steps:
            return "[]"
        step_dicts = [s.to_dict() for s in steps]
        return json.dumps(step_dicts, separators=(",", ":"))

    @classmethod
    def validate_evidence_integrity(
        cls,
        step: Step,
        case_status: str,
        context: Optional[ContextualValidationContext] = None,
    ) -> list[str]:
        """
        Validate evidence references against challenge integrity rules:
        - FINDING steps require valid non-empty admissible evidence references.
        - COMPLETE VERIFICATION steps require valid non-empty admissible evidence references.
        - INCOMPLETE REMEDIATION & VERIFICATION represent future actions and must have evidence_id == "".
        - If admissible_evidence_ids is supplied in context, citation must be present in that set.
        """
        errors: list[str] = []
        status = case_status.upper()
        ev_id = step.evidence_id

        # 1. NOT_APPLICABLE cases cannot have steps
        if status == "NOT_APPLICABLE":
            errors.append(
                f"Case is NOT_APPLICABLE; step {step.step_no} ({step.operation}) is not permitted."
            )
            return errors

        # 2. COMPLETE cases: strictly VERIFICATION with non-empty evidence
        if status == "COMPLETE":
            if step.phase != StepPhase.VERIFICATION.value:
                errors.append(
                    f"COMPLETE case cannot contain '{step.phase}' step {step.step_no} "
                    f"({step.operation}); only VERIFICATION steps are permitted."
                )
            if not ev_id or not ev_id.strip():
                errors.append(
                    f"COMPLETE verification step {step.step_no} ({step.operation}) must cite "
                    f"non-empty admissible evidence, got empty string."
                )
            elif not is_valid_evidence_format(ev_id):
                errors.append(
                    f"Step {step.step_no} cites malformed or invented evidence_id '{ev_id}'. "
                    f"Must start with one of {VALID_EVIDENCE_PREFIXES}."
                )
            elif context and context.admissible_evidence_ids is not None:
                if ev_id not in context.admissible_evidence_ids:
                    errors.append(
                        f"Step {step.step_no} cites evidence_id '{ev_id}' which is inadmissible "
                        f"at audit cutoff {context.audit_at}."
                    )

        # 3. INCOMPLETE cases
        elif status == "INCOMPLETE":
            if step.phase == StepPhase.FINDING.value:
                if not ev_id or not ev_id.strip():
                    errors.append(
                        f"FINDING step {step.step_no} ({step.operation}) in INCOMPLETE case must "
                        f"cite non-empty proving evidence, got empty string."
                    )
                elif not is_valid_evidence_format(ev_id):
                    errors.append(
                        f"FINDING step {step.step_no} cites malformed or invented evidence_id '{ev_id}'."
                    )
                elif context and context.admissible_evidence_ids is not None:
                    if ev_id not in context.admissible_evidence_ids:
                        errors.append(
                            f"FINDING step {step.step_no} cites evidence_id '{ev_id}' which is "
                            f"inadmissible at audit cutoff {context.audit_at}."
                        )
            elif step.phase in (StepPhase.REMEDIATION.value, StepPhase.VERIFICATION.value):
                if ev_id != "":
                    errors.append(
                        f"{step.phase} step {step.step_no} ({step.operation}) represents future action "
                        f"in INCOMPLETE case and must have evidence_id=\"\", got '{ev_id}'."
                    )

        return errors

    @classmethod
    def assemble_plan(
        cls,
        case_id: str,
        case_status: str,
        raw_steps: Sequence[Union[Step, Mapping[str, Any]]],
        context: Optional[ContextualValidationContext] = None,
    ) -> CaseStepPlan:
        """
        Assemble, order, number, validate, and serialize the final CaseStepPlan.

        Args:
            case_id: Case identifier.
            case_status: "COMPLETE" | "INCOMPLETE" | "NOT_APPLICABLE".
            raw_steps: Raw candidate steps or step dicts.
            context: Optional contextual validation context.
        """
        errors: list[str] = []
        diagnostics: list[str] = []
        norm_status = case_status.strip().upper()

        # Handle NOT_APPLICABLE case immediately
        if norm_status == "NOT_APPLICABLE":
            if raw_steps:
                diagnostics.append(
                    f"Case {case_id} is NOT_APPLICABLE; discarded {len(raw_steps)} candidate "
                    f"steps to enforce steps_json=[] contract."
                )
            return CaseStepPlan(
                case_id=case_id,
                case_status="NOT_APPLICABLE",
                steps=[],
                steps_json="[]",
                is_valid=True,
                errors=[],
                diagnostics=diagnostics,
            )

        # 1. Structural conversion and filtering of raw steps
        valid_steps: list[Step] = []
        for i, item in enumerate(raw_steps):
            if isinstance(item, Step):
                valid_steps.append(item)
            elif isinstance(item, Mapping):
                try:
                    s = Step.from_dict(item, allow_extra=False)
                    valid_steps.append(s)
                except StepValidationError as exc:
                    errors.append(f"Invalid candidate step at index {i}: {exc}")
            else:
                errors.append(f"Unexpected step item type at index {i}: {type(item).__name__}")

        # 2. Status-specific step filtering and phase check
        status_filtered_steps: list[Step] = []
        for s in valid_steps:
            if norm_status == "COMPLETE":
                if s.phase != StepPhase.VERIFICATION.value:
                    errors.append(
                        f"Case {case_id} is COMPLETE but contains {s.phase} step "
                        f"({s.operation} on {s.resource_id}). Only VERIFICATION allowed."
                    )
                    continue
            status_filtered_steps.append(s)

        # 3. Canonical ordering and 1-indexed consecutive numbering
        sequenced_steps = cls.order_and_number(status_filtered_steps)

        # 4. Contextual and evidence integrity checks
        ctx = context or ContextualValidationContext(
            case_id=case_id,
            case_status=norm_status,
        )

        for s in sequenced_steps:
            # Check individual contract
            c_res = StepContractValidator.validate_step(s)
            if not c_res.is_valid:
                errors.extend(c_res.errors)

            # Check evidence integrity
            ev_errors = cls.validate_evidence_integrity(s, norm_status, ctx)
            if ev_errors:
                errors.extend(ev_errors)

        # 5. Full sequence validation
        seq_res = StepValidator.validate_sequence(sequenced_steps, ctx)
        if not seq_res.is_valid:
            for err in seq_res.errors:
                if err not in errors:
                    errors.append(err)

        # 6. Serialization
        steps_json = cls.serialize_steps(sequenced_steps)
        is_valid = len(errors) == 0

        return CaseStepPlan(
            case_id=case_id,
            case_status=norm_status,
            steps=sequenced_steps,
            steps_json=steps_json,
            is_valid=is_valid,
            errors=errors,
            diagnostics=diagnostics,
        )

    @classmethod
    def assemble_from_plans(
        cls,
        case_id: str,
        case_status: str,
        findings_plan: Optional[Any] = None,
        remediation_plan: Optional[Any] = None,
        verification_plan: Optional[Any] = None,
        context: Optional[ContextualValidationContext] = None,
    ) -> CaseStepPlan:
        """
        Assemble from upstream generator plans (FindingsPlan, RemediationPlan, VerificationPlan).
        """
        combined_steps: list[Step] = []

        if findings_plan and hasattr(findings_plan, "steps"):
            combined_steps.extend(findings_plan.steps)
        if remediation_plan and hasattr(remediation_plan, "steps"):
            combined_steps.extend(remediation_plan.steps)
        if verification_plan and hasattr(verification_plan, "steps"):
            combined_steps.extend(verification_plan.steps)

        return cls.assemble_plan(
            case_id=case_id,
            case_status=case_status,
            raw_steps=combined_steps,
            context=context,
        )


def load_manifest_evidence_ids(
    manifest_path: Optional[Union[str, Path]] = None,
    dataset_dir: Optional[Union[str, Path]] = None,
) -> set[str]:
    """
    Load all valid participant-visible evidence identifiers (file_id, activity_id, audit_id).
    """
    path = Path(manifest_path or (CODE_DIR.parent / "dataset" / "evidence_files.csv")).resolve()
    ds_dir = Path(dataset_dir or path.parent).resolve()

    evidence_ids: set[str] = set()

    # 1. evidence_files.csv (file_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fid = row.get("file_id")
                if fid and fid.strip():
                    evidence_ids.add(fid.strip())

    # 2. system_activity.csv (activity_id)
    activity_path = ds_dir / "system_activity.csv"
    if activity_path.exists():
        with open(activity_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                aid = row.get("activity_id")
                if aid and aid.strip():
                    evidence_ids.add(aid.strip())

    # 3. user_audit_log.csv (audit_id)
    audit_path = ds_dir / "user_audit_log.csv"
    if audit_path.exists():
        with open(audit_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                auid = row.get("audit_id")
                if auid and auid.strip():
                    evidence_ids.add(auid.strip())

    return evidence_ids

"""Phase 6.5: Challenge Operation Vocabulary and Policy-to-Operation Mapper.

Defines the single source of truth for all permitted (phase, operation, state)
tuples as specified in AGENTS.md §6.4 and maps resource-level policy decisions
and risk states to valid challenge operations.

Constraints:
- Strictly enforces permitted operations and states.
- Rejects any unapproved operation, phase, or state combination.
- Decoupled from step numbering, sorting, and serialization (Phase 8).
- Does NOT assign case-level status (COMPLETE/INCOMPLETE) (Phase 7).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union, Any

# Local package imports
try:
    from .engine import (
        ResourceTreatmentDecision,
        ComplianceResult,
        RequiredAction,
    )
except ImportError:
    from engine import (
        ResourceTreatmentDecision,
        ComplianceResult,
        RequiredAction,
    )


class StepPhase(str, Enum):
    """The three official challenge phases."""
    FINDING = "FINDING"
    REMEDIATION = "REMEDIATION"
    VERIFICATION = "VERIFICATION"


class StepOperation(str, Enum):
    """The 15 official permitted challenge operations."""
    # Findings
    REPORT_REMAINING_RECORD = "REPORT_REMAINING_RECORD"
    REPORT_EXPOSED_PII = "REPORT_EXPOSED_PII"
    REPORT_ACTIVE_DATA_FLOW = "REPORT_ACTIVE_DATA_FLOW"
    REPORT_RESTORE_RISK = "REPORT_RESTORE_RISK"

    # Remediation
    DISABLE_DATA_FLOW = "DISABLE_DATA_FLOW"
    BLOCK_RESTORE = "BLOCK_RESTORE"
    DELETE_RECORD = "DELETE_RECORD"
    REDACT_RECORD = "REDACT_RECORD"
    ANONYMIZE_RECORD = "ANONYMIZE_RECORD"

    # Verification
    VERIFY_RECORD_ABSENT = "VERIFY_RECORD_ABSENT"
    VERIFY_RECORD_PRESENT = "VERIFY_RECORD_PRESENT"
    VERIFY_RECORD_REDACTED = "VERIFY_RECORD_REDACTED"
    VERIFY_RECORD_ANONYMIZED = "VERIFY_RECORD_ANONYMIZED"
    VERIFY_DATA_FLOW_DISABLED = "VERIFY_DATA_FLOW_DISABLED"
    VERIFY_RESTORE_BLOCKED = "VERIFY_RESTORE_BLOCKED"


class StepState(str, Enum):
    """The 6 official permitted step states."""
    PRESENT = "PRESENT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"
    ABSENT = "ABSENT"
    REDACTED = "REDACTED"
    ANONYMIZED = "ANONYMIZED"


# The authoritative single source of truth for allowed (phase, operation, state) combinations
PERMITTED_COMBINATIONS: set[tuple[str, str, str]] = {
    # Findings
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),

    # Remediation
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),

    # Verification
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
}


@dataclass(frozen=True)
class OperationSpec:
    """A validated, atomic step specification before numbering and ordering."""
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str = ""
    rationale: str = ""

    def __post_init__(self):
        triple = (self.phase, self.operation, self.state)
        if triple not in PERMITTED_COMBINATIONS:
            raise ValueError(
                f"Invalid challenge step combination: phase='{self.phase}', "
                f"operation='{self.operation}', state='{self.state}'. "
                f"Must be one of the permitted combinations defined in AGENTS.md §6.4."
            )


@dataclass
class PolicyOperationBundle:
    """Set of candidate operations generated for a single resource decision."""
    resource_id: str
    system_id: str
    data_category: str
    compliance_result: ComplianceResult
    findings: list[OperationSpec] = field(default_factory=list)
    remediations: list[OperationSpec] = field(default_factory=list)
    verifications: list[OperationSpec] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @property
    def finding_operation(self) -> Optional[str]:
        return self.findings[0].operation if self.findings else None

    @property
    def finding_state(self) -> Optional[str]:
        return self.findings[0].state if self.findings else None

    @property
    def remediation_operation(self) -> Optional[str]:
        return self.remediations[0].operation if self.remediations else None

    @property
    def remediation_state(self) -> Optional[str]:
        return self.remediations[0].state if self.remediations else None

    @property
    def verification_operation(self) -> Optional[str]:
        return self.verifications[0].operation if self.verifications else None

    @property
    def verification_state(self) -> Optional[str]:
        return self.verifications[0].state if self.verifications else None


class PolicyOperationMapper:
    """
    Translates resource-level policy decisions into validated challenge operations.
    """

    @staticmethod
    def is_valid_step(phase: str, operation: str, state: str) -> bool:
        """Verify whether a (phase, operation, state) tuple is officially permitted."""
        return (phase, operation, state) in PERMITTED_COMBINATIONS

    @classmethod
    def map_decision(
        cls,
        decision: ResourceTreatmentDecision,
        evidence_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> PolicyOperationBundle:
        """
        Map a ResourceTreatmentDecision to its corresponding Finding, Remediation,
        and Verification operation specs.

        Args:
            decision: ResourceTreatmentDecision from TreatmentEngine
            evidence_id: Grounded evidence identifier (file_id or activity_id)
        """
        bundle = PolicyOperationBundle(
            resource_id=decision.resource_id,
            system_id=decision.system_id,
            data_category=decision.data_category,
            compliance_result=decision.compliance_result,
        )

        ev_id = evidence_id or decision.evidence_id or ""
        cat = decision.data_category
        action = decision.required_action
        obs_state = decision.observed_state

        # Handle DATA_FLOW special entity
        if cat == "DATA_FLOW":
            if decision.is_non_compliant or obs_state == "ACTIVE":
                bundle.findings.append(OperationSpec(
                    phase="FINDING",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="REPORT_ACTIVE_DATA_FLOW",
                    state="ACTIVE",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
                bundle.remediations.append(OperationSpec(
                    phase="REMEDIATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="DISABLE_DATA_FLOW",
                    state="DISABLED",
                    evidence_id="",
                    rationale="Disable active data flow to prevent data recreation.",
                ))
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_DATA_FLOW_DISABLED",
                    state="DISABLED",
                    evidence_id="",
                    rationale="Confirm data flow remains disabled.",
                ))
            elif decision.is_compliant or obs_state in ("DISABLED", "BLOCKED"):
                # Compliant state verification
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_DATA_FLOW_DISABLED",
                    state="DISABLED",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
            return bundle

        # Handle BACKUP_ARCHIVE special entity
        if cat == "BACKUP_ARCHIVE":
            if decision.is_non_compliant or obs_state in ("ACTIVE", "PRESENT"):
                bundle.findings.append(OperationSpec(
                    phase="FINDING",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="REPORT_RESTORE_RISK",
                    state="ACTIVE",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
                bundle.remediations.append(OperationSpec(
                    phase="REMEDIATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="BLOCK_RESTORE",
                    state="BLOCKED",
                    evidence_id="",
                    rationale="Block restore access on backup archive to prevent data restoration.",
                ))
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RESTORE_BLOCKED",
                    state="BLOCKED",
                    evidence_id="",
                    rationale="Confirm backup restore access is blocked.",
                ))
            elif decision.is_compliant or obs_state in ("BLOCKED", "DISABLED"):
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RESTORE_BLOCKED",
                    state="BLOCKED",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
            return bundle

        # -----------------------------------------------------------------
        # Standard Record Categories (DELETE, REDACT, ANONYMIZE, RETAIN)
        # -----------------------------------------------------------------

        # Case 1: Treatment is DELETE
        if action == "DELETE":
            if decision.is_compliant or obs_state == "ABSENT":
                # Fully compliant deleted record: emit VERIFY_RECORD_ABSENT
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RECORD_ABSENT",
                    state="ABSENT",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
            else:
                # Violation: Remaining record
                bundle.findings.append(OperationSpec(
                    phase="FINDING",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="REPORT_REMAINING_RECORD",
                    state="PRESENT",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
                bundle.remediations.append(OperationSpec(
                    phase="REMEDIATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="DELETE_RECORD",
                    state="ABSENT",
                    evidence_id="",
                    rationale="Delete prohibited record.",
                ))
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RECORD_ABSENT",
                    state="ABSENT",
                    evidence_id="",
                    rationale="Confirm record is absent post-remediation.",
                ))

        # Case 2: Treatment is REDACT
        elif action == "REDACT":
            if decision.is_compliant or obs_state in ("REDACTED", "ABSENT", "ANONYMIZED"):
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RECORD_REDACTED",
                    state="REDACTED",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
            else:
                # Violation: Exposed PII
                bundle.findings.append(OperationSpec(
                    phase="FINDING",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="REPORT_EXPOSED_PII",
                    state="PRESENT",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
                bundle.remediations.append(OperationSpec(
                    phase="REMEDIATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="REDACT_RECORD",
                    state="REDACTED",
                    evidence_id="",
                    rationale="Redact direct identifying fields from record.",
                ))
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RECORD_REDACTED",
                    state="REDACTED",
                    evidence_id="",
                    rationale="Confirm direct identifiers are redacted post-remediation.",
                ))

        # Case 3: Treatment is ANONYMIZE
        elif action == "ANONYMIZE":
            if decision.is_compliant or obs_state in ("ANONYMIZED", "ABSENT"):
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RECORD_ANONYMIZED",
                    state="ANONYMIZED",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
            else:
                # Violation: In the challenge benchmark, un-anonymized analytics profiles
                # are reported as REPORT_EXPOSED_PII (or REPORT_REMAINING_RECORD if the whole profile should have been deleted).
                # For ANALYTICS_PROFILE where action is ANONYMIZE, the finding operation is REPORT_EXPOSED_PII.
                finding_op = "REPORT_EXPOSED_PII"
                bundle.findings.append(OperationSpec(
                    phase="FINDING",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation=finding_op,
                    state="PRESENT",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
                bundle.remediations.append(OperationSpec(
                    phase="REMEDIATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="ANONYMIZE_RECORD",
                    state="ANONYMIZED",
                    evidence_id="",
                    rationale="Irreversibly unlink record from user.",
                ))
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RECORD_ANONYMIZED",
                    state="ANONYMIZED",
                    evidence_id="",
                    rationale="Confirm record is anonymized post-remediation.",
                ))

        # Case 4: Treatment is RETAIN
        elif action == "RETAIN":
            if decision.is_compliant or obs_state in ("PRESENT", "RETAINED"):
                bundle.verifications.append(OperationSpec(
                    phase="VERIFICATION",
                    system_id=decision.system_id,
                    resource_id=decision.resource_id,
                    operation="VERIFY_RECORD_PRESENT",
                    state="PRESENT",
                    evidence_id=ev_id,
                    rationale=decision.reason,
                ))
            elif obs_state == "ABSENT":
                # Retention violation: required record is missing.
                # Per prompt instructions: The challenge does NOT define a RESTORE_RECORD remediation.
                # Do NOT invent unapproved operations. Surface as a diagnostic.
                bundle.diagnostics.append(
                    f"Retention violation: Mandatory record '{decision.resource_id}' ({cat}) is ABSENT. "
                    f"No challenge-approved remediation operation exists to restore deleted records."
                )

        return bundle

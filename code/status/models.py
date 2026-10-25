"""Phase 7: Case Status Models and Request Applicability Contracts.

Defines the core enumeration for deletion status, intent categories,
and the typed result contract for request applicability evaluation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DeletionStatus(str, Enum):
    """Authoritative case-level deletion status defined by the challenge contract."""
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RequestIntentCategory(str, Enum):
    """High-level classification of user intent extracted from request_text."""
    DELETION_AUTHORIZED = "DELETION_AUTHORIZED"
    NON_DELETION_PORTABILITY = "NON_DELETION_PORTABILITY"
    NON_DELETION_OPT_OUT = "NON_DELETION_OPT_OUT"
    NON_DELETION_RECTIFICATION = "NON_DELETION_RECTIFICATION"
    NON_DELETION_ACCESS_REQUEST = "NON_DELETION_ACCESS_REQUEST"
    NON_DELETION_SUPPORT_HELP = "NON_DELETION_SUPPORT_HELP"
    NON_DELETION_ACCOUNT_RETENTION = "NON_DELETION_ACCOUNT_RETENTION"
    AMBIGUOUS_CONTRADICTORY = "AMBIGUOUS_CONTRADICTORY"
    MALFORMED_EMPTY_TEXT = "MALFORMED_EMPTY_TEXT"


@dataclass(frozen=True)
class RequestApplicabilityResult:
    """
    Immutable result of evaluating whether a request authorizes personal data deletion.
    
    Attributes:
        case_id: The request identifier (e.g. 'case_01', 'case_533').
        is_applicable: True if the request genuinely authorizes personal data deletion.
        deletion_status: 'NOT_APPLICABLE' if is_applicable is False; None if deletion is authorized
                         and full case-level resolution must be performed by subsequent chunks.
        intent_category: Granular intent category.
        reason: Deterministic forensic explanation of the applicability verdict.
        detected_patterns: List of specific matched regex or keyword patterns.
        raw_text: The evaluated request_text.
        email: The email address associated with the request.
        audit_at: The cutoff timestamp associated with the request.
        reported_status: The unverified status claimed by the deletion workflow.
        diagnostics: Additional forensic warnings or diagnostic notes.
    """
    case_id: str
    is_applicable: bool
    deletion_status: Optional[str]
    intent_category: RequestIntentCategory
    reason: str
    detected_patterns: list[str] = field(default_factory=list)
    raw_text: str = ""
    email: str = ""
    audit_at: Optional[str] = None
    reported_status: str = ""
    diagnostics: list[str] = field(default_factory=list)

    @property
    def is_not_applicable(self) -> bool:
        """Helper to check if the request is NOT_APPLICABLE."""
        return not self.is_applicable


@dataclass(frozen=True)
class ResourceAggregationResult:
    """
    Immutable aggregation of all resource-level policy decisions and evidence for a case.
    
    Contains correlated compliance counts, lists of compliant vs violating resources,
    retained records breakdown, and diagnostic traceability.
    """
    case_id: str
    total_resources: int
    is_all_compliant: bool
    has_violations: bool
    has_indeterminate: bool
    has_retained_data: bool
    has_replica_drift: bool
    compliant_resources: list[str] = field(default_factory=list)
    non_compliant_resources: list[str] = field(default_factory=list)
    indeterminate_resources: list[str] = field(default_factory=list)
    retained_resources: list[str] = field(default_factory=list)
    evidence_provenance_by_resource: dict[str, str] = field(default_factory=dict)
    violations_by_resource: dict[str, str] = field(default_factory=dict)
    remediations_required_by_resource: dict[str, str] = field(default_factory=dict)
    rule_id_by_resource: dict[str, str] = field(default_factory=dict)
    contradictions: list[str] = field(default_factory=list)
    upstream_errors: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResidualFinding:
    """
    Typed forensic finding representing personal data that remains present at audit cutoff.
    """
    finding_type: str                   # "REPORT_REMAINING_RECORD" | "REPORT_EXPOSED_PII"
    system_id: str                      # System housing the record (e.g. account_service)
    resource_id: str                    # Unique resource locator (e.g. account_005, search_001)
    data_category: str                  # Governed data category (e.g. USER_PROFILE, SEARCH_INDEX_ENTRY)
    rule_id: Optional[str]              # Governing deletion policy rule ID (e.g. rule_01, rule_05)
    observed_state: str                 # "PRESENT"
    evidence_id: str                    # Participant-visible file_id or activity_id proving presence
    violation_reason: str               # Detailed reason why state violates policy
    exposed_fields: list[str] = field(default_factory=list)
    is_replica_drift: bool = False      # True if record exists due to replication lag/drift
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RemainingDataAssessmentResult:
    """
    Forensic assessment of all remaining data and residual violations for a case at cutoff.
    """
    case_id: str
    has_remaining_data: bool
    total_residual_findings: int
    findings: list[ResidualFinding] = field(default_factory=list)
    findings_by_resource: dict[str, ResidualFinding] = field(default_factory=dict)
    remaining_record_count: int = 0
    exposed_pii_count: int = 0
    replica_drift_count: int = 0
    unverified_resources: list[str] = field(default_factory=list)
    legitimately_retained_resources: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RecreationRiskFinding:
    """
    Forensic finding representing active synchronization, replication lag, recreation, or restore risk.
    """
    risk_type: str                      # "REPORT_ACTIVE_DATA_FLOW" | "REPORT_RESTORE_RISK" | "RECREATION_EVENT" | "REPLICA_DRIFT"
    system_id: str                      # System housing process/backup (e.g. integration_service, backup_service)
    resource_id: str                    # Unique locator (e.g. data_flow_9522, backup_4978)
    data_category: str                  # Governed category (DATA_FLOW, BACKUP_ARCHIVE, USER_PROFILE)
    observed_state: str                 # "ACTIVE" or "PRESENT"
    evidence_id: str                    # Participant-visible evidence locator
    risk_reason: str                    # Detailed explanation
    is_pre_cutoff: bool = True          # True if risk was active at or before audit_at
    remediation_operation: str = ""     # "DISABLE_DATA_FLOW" | "BLOCK_RESTORE" | "DELETE_RECORD"
    verification_operation: str = ""    # "VERIFY_DATA_FLOW_DISABLED" | "VERIFY_RESTORE_BLOCKED" | "VERIFY_RECORD_ABSENT"
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RecreationRiskAssessmentResult:
    """
    Structured assessment of all recreation, synchronization, replica drift, and restore risks.
    """
    case_id: str
    has_active_risks: bool
    total_risk_findings: int
    findings: list[RecreationRiskFinding] = field(default_factory=list)
    findings_by_resource: dict[str, RecreationRiskFinding] = field(default_factory=dict)
    active_flows_count: int = 0
    restore_risks_count: int = 0
    recreation_count: int = 0
    replica_drift_count: int = 0
    post_cutoff_events_excluded: list[str] = field(default_factory=list)
    failed_restores_verified_unrestored: list[str] = field(default_factory=list)
    blocked_backups_compliant: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceTrace:
    """
    Direct forensic trace linking an observation to an admissible evidence file or event.
    """
    evidence_id: str
    resource_id: str
    system_id: str
    data_category: str
    observed_state: str
    evidence_role: str                  # "DIRECT_OBSERVATION" | "VERIFICATION_PROOF" | "VIOLATION_FINDING" | "RISK_INDICATOR"
    admissible_at_cutoff: bool = True
    timestamp: Optional[str] = None
    description: str = ""


@dataclass(frozen=True)
class FindingExplanation:
    """
    Structured policy conclusion for a resource finding or verified compliant record.
    """
    finding_type: str                   # e.g. "REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK", "VERIFIED_RECORD_ABSENT", "VERIFIED_RECORD_PRESENT"
    resource_id: str
    system_id: str
    data_category: str
    rule_id: Optional[str]
    nature: str                         # "DIRECT_OBSERVATION" | "POLICY_DERIVED_CONCLUSION" | "UNRESOLVED_UNCERTAINTY"
    evidence_id: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContradictionTrace:
    """
    Forensic record of conflicting observations or timeline ambiguities.
    """
    resource_id: str
    conflicting_claims: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    nature: str = "UNRESOLVED_UNCERTAINTY"
    impact: str = "Forces status to INCOMPLETE due to evidence conflict."


@dataclass(frozen=True)
class DecisionExplanation:
    """
    Comprehensive, auditable explanation of a case-level status decision.
    
    Provides complete provenance, separating direct observations, policy-derived
    conclusions, and unresolved uncertainties without fabricating evidence citations.
    """
    case_id: str
    deletion_status: DeletionStatus
    status_value: str
    summary_reason: str
    primary_deciding_factor: str
    cutoff_iso: Optional[str] = None
    applicability_summary: dict = field(default_factory=dict)
    direct_observations: list[EvidenceTrace] = field(default_factory=list)
    policy_conclusions: list[FindingExplanation] = field(default_factory=list)
    unresolved_uncertainties: list[ContradictionTrace] = field(default_factory=list)
    excluded_post_cutoff_items: list[str] = field(default_factory=list)
    evidence_citations: list[str] = field(default_factory=list)
    sanitized_diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert explanation to a JSON-serializable dictionary."""
        return {
            "case_id": self.case_id,
            "deletion_status": self.status_value,
            "summary_reason": self.summary_reason,
            "primary_deciding_factor": self.primary_deciding_factor,
            "cutoff_iso": self.cutoff_iso,
            "applicability_summary": dict(self.applicability_summary),
            "evidence_citations": list(self.evidence_citations),
            "direct_observations_count": len(self.direct_observations),
            "policy_conclusions_count": len(self.policy_conclusions),
            "unresolved_uncertainties_count": len(self.unresolved_uncertainties),
            "excluded_post_cutoff_count": len(self.excluded_post_cutoff_items),
            "direct_observations": [
                {
                    "evidence_id": t.evidence_id,
                    "resource_id": t.resource_id,
                    "system_id": t.system_id,
                    "data_category": t.data_category,
                    "observed_state": t.observed_state,
                    "evidence_role": t.evidence_role,
                    "admissible_at_cutoff": t.admissible_at_cutoff,
                    "timestamp": t.timestamp,
                    "description": t.description,
                }
                for t in self.direct_observations
            ],
            "policy_conclusions": [
                {
                    "finding_type": f.finding_type,
                    "resource_id": f.resource_id,
                    "system_id": f.system_id,
                    "data_category": f.data_category,
                    "rule_id": f.rule_id,
                    "nature": f.nature,
                    "evidence_id": f.evidence_id,
                    "summary": f.summary,
                    "details": list(f.details),
                }
                for f in self.policy_conclusions
            ],
            "unresolved_uncertainties": [
                {
                    "resource_id": u.resource_id,
                    "conflicting_claims": list(u.conflicting_claims),
                    "evidence_ids": list(u.evidence_ids),
                    "nature": u.nature,
                    "impact": u.impact,
                }
                for u in self.unresolved_uncertainties
            ],
            "excluded_post_cutoff_items": list(self.excluded_post_cutoff_items),
            "sanitized_diagnostics": list(self.sanitized_diagnostics),
        }

    def to_audit_markdown(self) -> str:
        """Format a human-readable, auditable forensic markdown explanation."""
        lines = [
            f"### Forensic Decision Audit: Case `{self.case_id}`",
            f"- **Authoritative Status:** `{self.status_value}`",
            f"- **Primary Deciding Factor:** `{self.primary_deciding_factor}`",
            f"- **Cutoff Timestamp:** `{self.cutoff_iso or 'Not configured'}`",
            f"- **Forensic Summary:** {self.summary_reason}",
            "",
            "#### 1. Request Applicability",
            f"- **Deletion Authorized:** {self.applicability_summary.get('is_applicable', False)}",
            f"- **Intent Category:** `{self.applicability_summary.get('intent_category', 'UNKNOWN')}`",
            f"- **Applicability Reason:** {self.applicability_summary.get('reason', 'N/A')}",
        ]
        if self.applicability_summary.get("detected_patterns"):
            lines.append(f"- **Matched Patterns:** {', '.join(self.applicability_summary['detected_patterns'])}")

        lines.extend(["", "#### 2. Policy-Derived Conclusions"])
        if self.policy_conclusions:
            for f in self.policy_conclusions:
                ev_str = f" [Evidence: `{f.evidence_id}`]" if f.evidence_id else " [No Evidence / Future]"
                rule_str = f" (Rule: `{f.rule_id}`)" if f.rule_id else ""
                lines.append(f"- **{f.finding_type}** on `{f.system_id}.{f.resource_id}`{rule_str}: {f.summary}{ev_str} *({f.nature})*")
        else:
            lines.append("- *No specific resource-level findings.*")

        lines.extend(["", "#### 3. Direct Evidence Observations"])
        if self.direct_observations:
            for o in self.direct_observations:
                admit_str = "Admissible" if o.admissible_at_cutoff else "INADMISSIBLE (Post-Cutoff)"
                lines.append(f"- Evidence `{o.evidence_id}`: Resource `{o.resource_id}` observed as `{o.observed_state}` ({admit_str}) - {o.description}")
        else:
            lines.append("- *No direct evidence observations recorded.*")

        if self.unresolved_uncertainties:
            lines.extend(["", "#### 4. Unresolved Uncertainties & Contradictions"])
            for u in self.unresolved_uncertainties:
                ev_str = f" [Evidence: {', '.join(u.evidence_ids)}]" if u.evidence_ids else ""
                lines.append(f"- **Resource `{u.resource_id}`:** {'; '.join(u.conflicting_claims)}{ev_str}")
                lines.append(f"  *Impact:* {u.impact}")

        if self.excluded_post_cutoff_items:
            lines.extend(["", "#### 5. Excluded Post-Cutoff Events"])
            for item in self.excluded_post_cutoff_items:
                lines.append(f"- *Excluded:* {item}")

        lines.extend(["", f"#### 6. Admissible Evidence Citations ({len(self.evidence_citations)})"])
        if self.evidence_citations:
            lines.append(f"- `{', '.join(self.evidence_citations)}`")
        else:
            lines.append("- *Zero participant-visible evidence citations.*")

        return "\n".join(lines)


@dataclass(frozen=True)
class CaseStatusResult:
    """
    Authoritative case-level resolution verdict produced by Phase 7.
    
    Combines request applicability, aggregated resource compliance, residual-data
    findings, and recreation/restore risks into the exact challenge-permitted status.
    """
    case_id: str
    deletion_status: DeletionStatus
    reason: str
    is_non_deletion_request: bool
    resolution_status: str
    applicability: RequestApplicabilityResult
    resource_aggregation: ResourceAggregationResult
    remaining_data: RemainingDataAssessmentResult
    risk_assessment: RecreationRiskAssessmentResult
    diagnostics: list[str] = field(default_factory=list)
    explanation: Optional[DecisionExplanation] = None

    @property
    def is_complete(self) -> bool:
        return self.deletion_status == DeletionStatus.COMPLETE

    @property
    def is_incomplete(self) -> bool:
        return self.deletion_status == DeletionStatus.INCOMPLETE

    @property
    def is_not_applicable(self) -> bool:
        return self.deletion_status == DeletionStatus.NOT_APPLICABLE

    @property
    def status_value(self) -> str:
        return self.deletion_status.value






"""Phase 6.3: Deterministic Resource-Treatment Engine.

Defines the typed decision contract and implements deterministic policy
evaluation across all supported actions: DELETE, REDACT, ANONYMIZE, and RETAIN.

Ensures:
- Strict separation of concerns (resource-level decision, not case status).
- Complete determinism without LLM invocation.
- Evidence grounding: cites valid evidence_id or activity_id without fabrication.
- Explicit representation of uncertainty (UNRESOLVED, INDETERMINATE, UNKNOWN_STATE).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union, Any
from pathlib import Path

try:
    from .loader import PolicyLoader, PolicyRule, DEFAULT_RULES_PATH
    from .temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
    )
except ImportError:
    from loader import PolicyLoader, PolicyRule, DEFAULT_RULES_PATH
    from temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
    )


class ComplianceResult(str, Enum):
    """Compliance state of a resource under a policy rule."""
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    INDETERMINATE = "INDETERMINATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RequiredAction(str, Enum):
    """The required policy action / treatment."""
    DELETE = "DELETE"
    REDACT = "REDACT"
    ANONYMIZE = "ANONYMIZE"
    RETAIN = "RETAIN"


# Mapping from resource category to default system ID
CATEGORY_TO_DEFAULT_SYSTEM = {
    "USER_PROFILE": "account_service",
    "SECONDARY_IDENTIFIER": "account_service",
    "SEARCH_INDEX_ENTRY": "search_service",
    "CACHE_ENTRY": "cache_service",
    "SUPPORT_MESSAGE": "support_platform",
    "SUPPORT_ATTACHMENT": "support_platform",
    "ANALYTICS_PROFILE": "analytics_platform",
    "PRODUCT_TELEMETRY": "telemetry_service",
    "USER_EXPORT": "export_service",
    "MARKETING_PROFILE": "marketing_service",
    "EMAIL_DELIVERY_LOG": "email_service",
    "SECURITY_AUDIT_LOG": "security_service",
    "LEGAL_HOLD_RECORD": "compliance_service",
    "BACKUP_ARCHIVE": "backup_service",
    "ACCOUNT_TOMBSTONE": "identity_service",
}

# Standard resource-id prefix to default data category mapping
PREFIX_TO_CATEGORY = {
    "account_": "USER_PROFILE",
    "search_": "SEARCH_INDEX_ENTRY",
    "cache_": "CACHE_ENTRY",
    "export_": "USER_EXPORT",
    "analytics_": "ANALYTICS_PROFILE",
    "telemetry_": "PRODUCT_TELEMETRY",
    "email_": "EMAIL_DELIVERY_LOG",
    "audit_record_": "SECURITY_AUDIT_LOG",
    "legal_": "LEGAL_HOLD_RECORD",
    "backup_": "BACKUP_ARCHIVE",
    "tombstone_": "ACCOUNT_TOMBSTONE",
    "data_flow_": "DATA_FLOW",
}


# Prohibited direct identifiers for account tombstones and redacted records
PROHIBITED_DIRECT_IDENTIFIERS = {
    "name",
    "full_name",
    "first_name",
    "last_name",
    "email",
    "email_address",
    "phone",
    "phone_number",
    "telephone",
    "mobile",
    "email_hash",
    "emailhash",
    "hash",
}

# Permitted stable reference fields for account tombstones
PERMITTED_STABLE_REFERENCES = {
    "subject_reference",
    "user_id",
    "userid",
    "customer_id",
    "customer_reference",
    "internal_id",
    "account_id",
}


@dataclass(frozen=True)
class TombstoneInspectionResult:
    """Detailed field-level audit result for an account tombstone record."""
    is_valid_tombstone: bool
    has_stable_reference: bool
    stable_reference_value: Optional[str]
    exposed_direct_identifiers: list[str] = field(default_factory=list)
    prohibited_fields_found: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


def inspect_tombstone_fields(record_data: dict[str, Any]) -> TombstoneInspectionResult:
    """
    Inspect the fields of an account tombstone record.

    Verifies that:
    1. A permitted stable reference (e.g. subject_reference / user_id) is present and non-empty.
    2. Prohibited direct identifiers (name, email, phone, email_hash) are absent or null/empty.
    Normalizes known field aliases (e.g. emailHash, email_hash, phone_number).
    """
    if not isinstance(record_data, dict):
        return TombstoneInspectionResult(
            is_valid_tombstone=False,
            has_stable_reference=False,
            stable_reference_value=None,
            diagnostics=["Record data is not a dictionary"],
        )

    stable_ref_val = None
    has_stable_ref = False
    exposed_direct_identifiers = []
    prohibited_fields_found = {}
    diagnostics = []

    for raw_key, raw_val in record_data.items():
        if raw_val is None:
            continue
        val_str = str(raw_val).strip()
        if not val_str or val_str.lower() in ("null", "none"):
            continue

        # Normalize key: lowercase, strip underscores/hyphens for alias matching
        key_norm = str(raw_key).strip().lower()
        key_condensed = key_norm.replace("_", "").replace("-", "")

        # Check stable reference
        if key_norm in PERMITTED_STABLE_REFERENCES or key_condensed in ("subjectreference", "userid", "customerid", "customerreference"):
            has_stable_ref = True
            stable_ref_val = val_str
            continue

        # Check prohibited direct identifiers
        is_prohibited = False
        if key_norm in PROHIBITED_DIRECT_IDENTIFIERS:
            is_prohibited = True
        elif key_condensed in ("emailhash", "phonenumber", "fullname", "firstname", "lastname", "emailaddress"):
            is_prohibited = True

        if is_prohibited:
            exposed_direct_identifiers.append(raw_key)
            prohibited_fields_found[raw_key] = val_str

    if not has_stable_ref:
        diagnostics.append("Missing required stable internal user reference in account tombstone.")

    if exposed_direct_identifiers:
        diagnostics.append(f"Prohibited direct identifiers exposed: {sorted(exposed_direct_identifiers)}")

    is_valid = has_stable_ref and len(exposed_direct_identifiers) == 0

    return TombstoneInspectionResult(
        is_valid_tombstone=is_valid,
        has_stable_reference=has_stable_ref,
        stable_reference_value=stable_ref_val,
        exposed_direct_identifiers=sorted(exposed_direct_identifiers),
        prohibited_fields_found=prohibited_fields_found,
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class ResourceTreatmentDecision:
    """Immutable, typed decision contract for a single evaluated resource."""
    resource_id: str
    system_id: str
    data_category: str
    rule_id: Optional[str]
    required_action: Optional[str]
    observed_state: str
    compliance_result: ComplianceResult
    reason: str
    evidence_id: Optional[str] = None
    diagnostics: list[str] = field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        return self.compliance_result == ComplianceResult.COMPLIANT

    @property
    def is_non_compliant(self) -> bool:
        return self.compliance_result == ComplianceResult.NON_COMPLIANT

    @property
    def is_indeterminate(self) -> bool:
        return self.compliance_result == ComplianceResult.INDETERMINATE


class TreatmentEngine:
    """
    Deterministic Resource-Treatment Evaluator.

    Evaluates whether an observed resource state satisfies the governing
    policy rule at the case's audit cutoff.
    """

    def __init__(self, policy_loader: Optional[PolicyLoader] = None):
        if policy_loader is None:
            policy_loader = PolicyLoader()
        self.policy_loader = policy_loader
        self._policy_result = self.policy_loader.load()

    def categorize_resource(
        self,
        resource_id: str,
        system_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> tuple[str, Optional[str]]:
        """
        Map a resource_id and its context to a policy data_category.
        
        Returns:
            (data_category, disambiguation_reason)
        """
        rid = resource_id.strip()
        rid_lower = rid.lower()
        context = context or {}

        # 1. Explicit category in context (e.g. from shift handover or database schema)
        explicit_cat = context.get("data_category") or context.get("resource_category")
        if explicit_cat and explicit_cat.upper() in self._policy_result.rules_by_category:
            return explicit_cat.upper(), "Explicit category provided in context"

        # 2. Contextual disambiguation for support_ resources
        if rid_lower.startswith("support_"):
            record_type = str(context.get("record_type") or "").upper()
            if record_type == "SUPPORT_ATTACHMENT":
                return "SUPPORT_ATTACHMENT", "Context indicates SUPPORT_ATTACHMENT"
            elif record_type == "SUPPORT_MESSAGE":
                return "SUPPORT_MESSAGE", "Context indicates SUPPORT_MESSAGE"

            # Check if any evidence sighting indicates attachment or document
            source_path = str(context.get("source_path") or "").lower()
            if source_path.endswith(".pdf") or "attachment" in source_path:
                return "SUPPORT_ATTACHMENT", "Source file extension/name indicates attachment"

            # Default for support_ messages when shared conversation context is retained
            # Note: In production data, support tickets with identifiable text default to SUPPORT_MESSAGE
            # unless confirmed as subject-only attachment.
            return "SUPPORT_MESSAGE", "Default support category for support conversation"

        # 3. Contextual disambiguation for marketing vs analytics
        if rid_lower.startswith("analytics_"):
            if context.get("is_marketing") or "marketing" in str(context.get("details", "")).lower():
                return "MARKETING_PROFILE", "Context indicates MARKETING_PROFILE"
            return "ANALYTICS_PROFILE", "Prefix matches ANALYTICS_PROFILE"

        # 4. Standard prefix mapping
        for prefix, cat in PREFIX_TO_CATEGORY.items():
            if rid_lower.startswith(prefix):
                return cat, f"Prefix '{prefix}' matches {cat}"

        return "UNKNOWN", f"Unrecognized resource prefix for '{resource_id}'"

    def evaluate_timeline_resource(
        self,
        timeline: Any,
        audit_at: Optional[Union[str, datetime]] = None,
        context: Optional[dict] = None,
    ) -> ResourceTreatmentDecision:
        """
        Evaluate a Phase 5 ResourceTimeline against governing deletion policies.
        
        Enforces:
        - Strict temporal contract at audit_at cutoff.
        - Isolation of post-cutoff events (cannot alter pre-cutoff decision).
        - Replica drift detection: if replica retains record, state is PRESENT (non-compliant).
        - Active data flows and restore risks: evaluated under flow and restore rules.
        - Preserves evidence provenance without fabricating evidence IDs.
        - Explicit handling of contradictions and unknown states (INDETERMINATE).
        """
        context = dict(context or {})
        diagnostics = []

        # 1. Audit cutoff and temporal contract validation
        audit_val = inspect_timeline_temporal_contract(timeline, audit_at)
        diagnostics.extend(audit_val.diagnostics)

        resource_id = getattr(timeline, "resource_id", "unknown_resource")
        system_id = getattr(timeline, "system_id", None)
        category = getattr(timeline, "resource_category", None)
        raw_state = getattr(timeline, "state_at_cutoff", "UNKNOWN")
        evidence_id = getattr(timeline, "latest_admissible_evidence_id", "")
        replica_drift = getattr(timeline, "replica_drift", False)
        is_active_flow = getattr(timeline, "is_active_flow", False)
        is_restore_risk = getattr(timeline, "is_restore_risk", False)
        contradictions = getattr(timeline, "contradictions", [])

        # Store provenance and context flags
        context["evidence_provenance"] = getattr(timeline, "evidence_provenance", [])
        context["replica_drift"] = replica_drift
        context["is_active_flow"] = is_active_flow
        context["is_restore_risk"] = is_restore_risk
        context["has_corroborated_deletion"] = getattr(timeline, "has_corroborated_deletion", False)
        context["has_failed_deletion"] = getattr(timeline, "has_failed_deletion", False)
        context["contradictions"] = contradictions

        # Validate evidence_id
        if evidence_id and not validate_evidence_id(evidence_id):
            diagnostics.append(f"Unverified evidence_id '{evidence_id}' rejected")
            evidence_id = ""

        # Check for temporal contradiction in evidence citations
        if not audit_val.is_valid:
            diagnostics.extend(audit_val.contradictions)
            for c in audit_val.contradictions:
                if "only appears in post-cutoff events" in c:
                    evidence_id = ""

        # 2. Reconcile observed state with forensic findings
        # A) Replica drift: primary reported deleted/absent, but replica retains record
        if replica_drift:
            observed_state = "PRESENT"
            diagnostics.append("Replica drift detected: record remains PRESENT on replica at cutoff.")
        # B) Active flow or restore risk
        elif category == "DATA_FLOW" and (is_active_flow or raw_state == "ACTIVE"):
            observed_state = "ACTIVE"
        elif category == "BACKUP_ARCHIVE" and (is_restore_risk or raw_state == "ACTIVE"):
            observed_state = "ACTIVE"
        else:
            observed_state = raw_state

        # 3. Evaluate resource against policy rules
        decision = self.evaluate_resource(
            resource_id=resource_id,
            observed_state=observed_state,
            system_id=system_id,
            data_category=category,
            evidence_id=evidence_id,
            context=context,
        )

        # Merge diagnostics
        all_diagnostics = list(decision.diagnostics)
        for d in diagnostics:
            if d not in all_diagnostics:
                all_diagnostics.append(d)

        # 4. Uncertainty handling: missing or conflicting evidence cannot be converted to compliance
        if decision.compliance_result == ComplianceResult.COMPLIANT:
            if contradictions:
                has_corroborated = getattr(timeline, "has_corroborated_deletion", False)
                if not has_corroborated and not evidence_id:
                    return ResourceTreatmentDecision(
                        resource_id=decision.resource_id,
                        system_id=decision.system_id,
                        data_category=decision.data_category,
                        rule_id=decision.rule_id,
                        required_action=decision.required_action,
                        observed_state=decision.observed_state,
                        compliance_result=ComplianceResult.INDETERMINATE,
                        reason="Unresolved contradictions in evidence/activity stream; compliance cannot be verified.",
                        evidence_id=decision.evidence_id,
                        diagnostics=all_diagnostics,
                    )

        return ResourceTreatmentDecision(
            resource_id=decision.resource_id,
            system_id=decision.system_id,
            data_category=decision.data_category,
            rule_id=decision.rule_id,
            required_action=decision.required_action,
            observed_state=decision.observed_state,
            compliance_result=decision.compliance_result,
            reason=decision.reason,
            evidence_id=decision.evidence_id,
            diagnostics=all_diagnostics,
        )

    def evaluate_resource(
        self,
        resource_id: str,
        observed_state: str,
        system_id: Optional[str] = None,
        data_category: Optional[str] = None,
        evidence_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> ResourceTreatmentDecision:
        """
        Evaluate a single resource against the policy.

        Args:
            resource_id: Unique resource identifier (e.g. "account_005")
            observed_state: State at cutoff (ABSENT, PRESENT, REDACTED, ANONYMIZED, ACTIVE, BLOCKED, UNKNOWN)
            system_id: Owning system name (e.g. "account_service")
            data_category: Policy data_category, or None to infer
            evidence_id: Admissible evidence or activity identifier proving the state
            context: Additional metadata or flags for contextual matching
        """
        diagnostics = []
        context = context or {}

        # 1. Resolve Data Category
        if not data_category or data_category == "UNKNOWN":
            data_category, cat_reason = self.categorize_resource(resource_id, system_id, context)
            diagnostics.append(f"Categorization: {cat_reason}")
        else:
            data_category = data_category.strip().upper()

        # Resolve system_id
        if not system_id or system_id == "unknown_system":
            system_id = CATEGORY_TO_DEFAULT_SYSTEM.get(data_category, "unknown_system")

        # Normalize observed state
        state_norm = (observed_state or "").strip().upper()

        # Handle UNKNOWN or empty observed state
        if not state_norm or state_norm in ("UNKNOWN", "INDETERMINATE"):
            return ResourceTreatmentDecision(
                resource_id=resource_id,
                system_id=system_id,
                data_category=data_category,
                rule_id=None,
                required_action=None,
                observed_state=state_norm or "UNKNOWN",
                compliance_result=ComplianceResult.INDETERMINATE,
                reason="Observed resource state is UNKNOWN or undetermined; compliance cannot be established.",
                evidence_id=evidence_id,
                diagnostics=diagnostics,
            )

        # 2. Look up governing policy rule
        rules = self.policy_loader.get_rules_for_category(data_category)

        # If data category is DATA_FLOW (special infrastructure entity)
        if data_category == "DATA_FLOW":
            # Active data flows can recreate deleted data
            if state_norm in ("DISABLED", "ABSENT", "BLOCKED"):
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=None,
                    required_action="DISABLE_DATA_FLOW",
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.COMPLIANT,
                    reason=f"Data flow is inactive ({state_norm}); no recreation risk.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            elif state_norm == "ACTIVE":
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=None,
                    required_action="DISABLE_DATA_FLOW",
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.NON_COMPLIANT,
                    reason="Data flow is ACTIVE and can copy or recreate user data.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            else:
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=None,
                    required_action="DISABLE_DATA_FLOW",
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.INDETERMINATE,
                    reason=f"Unsupported state '{state_norm}' for DATA_FLOW.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )

        if not rules:
            diagnostics.append(f"No policy rule defined for category '{data_category}'")
            return ResourceTreatmentDecision(
                resource_id=resource_id,
                system_id=system_id,
                data_category=data_category,
                rule_id=None,
                required_action=None,
                observed_state=state_norm,
                compliance_result=ComplianceResult.INDETERMINATE,
                reason=f"No governing policy rule found for data category '{data_category}'.",
                evidence_id=evidence_id,
                diagnostics=diagnostics,
            )

        # Policy validation check for conflicts
        if len(rules) > 1:
            # Check if rules have identical or conflicting actions
            actions = {r.required_action for r in rules}
            if len(actions) > 1:
                diagnostics.append(f"Multiple conflicting rules for category '{data_category}': {[r.rule_id for r in rules]}")
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=None,
                    required_action=None,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.INDETERMINATE,
                    reason=f"Ambiguous policy: multiple conflicting rules match category '{data_category}'.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )

        # Select the governing rule (deterministic: lowest rule_id if identical action)
        rule = rules[0]
        action = rule.required_action

        # 3. Apply Treatment Semantics Deterministically

        # ---------------------------------------------------------
        # Treatment: DELETE
        # A prohibited record must be ABSENT.
        # ---------------------------------------------------------
        if action == "DELETE":
            if state_norm == "ABSENT":
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.COMPLIANT,
                    reason=f"Rule {rule.rule_id} requires DELETE; resource is ABSENT at audit cutoff.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            elif state_norm in ("PRESENT", "ACTIVE", "REDACTED", "ANONYMIZED"):
                # Even if redacted or anonymized, if rule mandates DELETE, the entire record must be absent.
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.NON_COMPLIANT,
                    reason=f"Rule {rule.rule_id} requires DELETE; resource remains {state_norm}.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            else:
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.INDETERMINATE,
                    reason=f"Unsupported state '{state_norm}' under DELETE treatment.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )

        # ---------------------------------------------------------
        # Treatment: REDACT
        # Identifying fields must be removed.
        # Compliant if REDACTED (or ABSENT, as deletion is strictly cleaner).
        # Non-compliant if PRESENT (direct identifiers still exposed).
        # ---------------------------------------------------------
        elif action == "REDACT":
            # If detailed record fields are provided in context (e.g. from JSON or database snapshot)
            record_fields = context.get("record_data") or context.get("raw_record")
            if data_category == "ACCOUNT_TOMBSTONE" and isinstance(record_fields, dict):
                inspection = inspect_tombstone_fields(record_fields)
                for diag in inspection.diagnostics:
                    diagnostics.append(f"TombstoneAudit: {diag}")

                if not inspection.has_stable_reference:
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.NON_COMPLIANT,
                        reason=f"Rule {rule.rule_id} requires stable reference preserved in tombstone; stable reference is missing.",
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )

                if inspection.exposed_direct_identifiers:
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.NON_COMPLIANT,
                        reason=(
                            f"Rule {rule.rule_id} requires direct identifiers redacted; "
                            f"prohibited fields exposed: {inspection.exposed_direct_identifiers}."
                        ),
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )

                # Has stable reference and no direct PII
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state="REDACTED",
                    compliance_result=ComplianceResult.COMPLIANT,
                    reason=(
                        f"Rule {rule.rule_id} permits account tombstone with stable reference "
                        f"'{inspection.stable_reference_value}'; direct identifiers are absent/redacted."
                    ),
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )

            if state_norm in ("REDACTED", "ABSENT", "ANONYMIZED"):
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.COMPLIANT,
                    reason=f"Rule {rule.rule_id} requires REDACT; identifiers are removed ({state_norm}).",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            elif state_norm in ("PRESENT", "ACTIVE"):
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.NON_COMPLIANT,
                    reason=f"Rule {rule.rule_id} requires REDACT; record remains {state_norm} with direct identifiers exposed.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            else:
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.INDETERMINATE,
                    reason=f"Unsupported state '{state_norm}' under REDACT treatment.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )

        # ---------------------------------------------------------
        # Treatment: ANONYMIZE
        # Record may remain only when irreversible unlinking is complete.
        # Compliant if ANONYMIZED (or ABSENT).
        # Non-compliant if PRESENT (still attributable to subject).
        # ---------------------------------------------------------
        elif action == "ANONYMIZE":
            if state_norm in ("ANONYMIZED", "ABSENT"):
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.COMPLIANT,
                    reason=f"Rule {rule.rule_id} requires ANONYMIZE; record is unlinked ({state_norm}).",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            elif state_norm in ("PRESENT", "ACTIVE", "REDACTED"):
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.NON_COMPLIANT,
                    reason=f"Rule {rule.rule_id} requires ANONYMIZE; record remains {state_norm} and attributable to user.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )
            else:
                return ResourceTreatmentDecision(
                    resource_id=resource_id,
                    system_id=system_id,
                    data_category=data_category,
                    rule_id=rule.rule_id,
                    required_action=action,
                    observed_state=state_norm,
                    compliance_result=ComplianceResult.INDETERMINATE,
                    reason=f"Unsupported state '{state_norm}' under ANONYMIZE treatment.",
                    evidence_id=evidence_id,
                    diagnostics=diagnostics,
                )

        # ---------------------------------------------------------
        # Treatment: RETAIN
        # A policy-required record must remain available.
        # For BACKUP_ARCHIVE: restore access must be BLOCKED.
        # For SECURITY_AUDIT_LOG / LEGAL_HOLD_RECORD: record must be PRESENT.
        # ---------------------------------------------------------
        elif action == "RETAIN":
            if data_category == "BACKUP_ARCHIVE":
                if state_norm in ("BLOCKED", "DISABLED"):
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.COMPLIANT,
                        reason=f"Rule {rule.rule_id} requires RETAIN with blocked restore; backup restore is {state_norm}.",
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )
                elif state_norm in ("ACTIVE", "PRESENT"):
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.NON_COMPLIANT,
                        reason=f"Rule {rule.rule_id} requires RETAIN with restore blocked; backup restore is ACTIVE.",
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )
                else:
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.INDETERMINATE,
                        reason=f"Unsupported state '{state_norm}' for BACKUP_ARCHIVE.",
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )
            else:
                # Standard retained record (e.g. SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD)
                # Check condition if provided in context
                if rule.condition:
                    cond_lower = rule.condition.lower()
                    if "retention period" in cond_lower:
                        # e.g. "Record is within the supplied retention period"
                        within_period = context.get("within_retention_period")
                        if within_period is False:
                            return ResourceTreatmentDecision(
                                resource_id=resource_id,
                                system_id=system_id,
                                data_category=data_category,
                                rule_id=rule.rule_id,
                                required_action=action,
                                observed_state=state_norm,
                                compliance_result=ComplianceResult.NON_COMPLIANT,
                                reason=f"Rule {rule.rule_id} condition failed: Record is outside the retention period.",
                                evidence_id=evidence_id,
                                diagnostics=diagnostics,
                            )
                    elif "legal hold" in cond_lower:
                        # e.g. "A supplied legal hold is active"
                        legal_hold_active = context.get("legal_hold_active")
                        if legal_hold_active is False:
                            return ResourceTreatmentDecision(
                                resource_id=resource_id,
                                system_id=system_id,
                                data_category=data_category,
                                rule_id=rule.rule_id,
                                required_action=action,
                                observed_state=state_norm,
                                compliance_result=ComplianceResult.NOT_APPLICABLE,
                                reason=f"Rule {rule.rule_id} condition not met: No active legal hold.",
                                evidence_id=evidence_id,
                                diagnostics=diagnostics,
                            )

                # Check if retained record also requires identifier restrictions / redaction
                record_fields = context.get("record_data") or context.get("raw_record")
                if isinstance(record_fields, dict):
                    # Check if prohibited identifiers (e.g. unredacted direct PII) remain where prohibited
                    prohibited_present = []
                    for k, v in record_fields.items():
                        if v and str(v).strip().lower() not in ("null", "none"):
                            k_norm = str(k).strip().lower().replace("_", "").replace("-", "")
                            if k_norm in ("password", "rawauth", "cardnumber", "cvv"):
                                prohibited_present.append(k)
                    if prohibited_present:
                        return ResourceTreatmentDecision(
                            resource_id=resource_id,
                            system_id=system_id,
                            data_category=data_category,
                            rule_id=rule.rule_id,
                            required_action=action,
                            observed_state=state_norm,
                            compliance_result=ComplianceResult.NON_COMPLIANT,
                            reason=f"Rule {rule.rule_id} requires retention, but record contains prohibited sensitive fields: {prohibited_present}.",
                            evidence_id=evidence_id,
                            diagnostics=diagnostics,
                        )

                if state_norm in ("PRESENT", "RETAINED"):
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.COMPLIANT,
                        reason=f"Rule {rule.rule_id} requires RETAIN; record is PRESENT as mandated.",
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )
                elif state_norm == "ABSENT":
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.NON_COMPLIANT,
                        reason=f"Rule {rule.rule_id} requires RETAIN; mandatory record is prematurely ABSENT.",
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )
                else:
                    return ResourceTreatmentDecision(
                        resource_id=resource_id,
                        system_id=system_id,
                        data_category=data_category,
                        rule_id=rule.rule_id,
                        required_action=action,
                        observed_state=state_norm,
                        compliance_result=ComplianceResult.INDETERMINATE,
                        reason=f"Unsupported state '{state_norm}' for RETAIN record.",
                        evidence_id=evidence_id,
                        diagnostics=diagnostics,
                    )

        # Fallback for unexpected actions
        return ResourceTreatmentDecision(
            resource_id=resource_id,
            system_id=system_id,
            data_category=data_category,
            rule_id=rule.rule_id,
            required_action=action,
            observed_state=state_norm,
            compliance_result=ComplianceResult.INDETERMINATE,
            reason=f"Unsupported policy action '{action}'.",
            evidence_id=evidence_id,
            diagnostics=diagnostics,
        )

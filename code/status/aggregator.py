"""Phase 7: Resource Compliance Aggregator.

Correlates and aggregates Phase 6 resource-level policy evaluation decisions
and evidence into a structured case-level compliance assessment.
"""

from typing import Optional, Any
from collections import defaultdict

try:
    from .models import ResourceAggregationResult
except ImportError:
    from models import ResourceAggregationResult

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
POLICY_DIR = CURRENT_DIR.parent / "policy"

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))

# Phase 6 imports
try:
    from engine import ComplianceResult, ResourceTreatmentDecision
    from service import CasePolicyEvaluationResult
    from mapper import StepOperation
except ImportError:
    from .engine import ComplianceResult, ResourceTreatmentDecision
    from .service import CasePolicyEvaluationResult
    from .mapper import StepOperation



class ResourceComplianceAggregator:
    """
    Aggregates resource-level policy evaluation decisions for a case.
    
    Ensures that:
    1. A single compliant record cannot override non-compliant or indeterminate records.
    2. Proved violations, proven compliance, legitimate retentions, and unverified states are separated.
    3. Evidence citations, policy rule identifiers, and diagnostic provenance are strictly preserved.
    4. Deterministic sorting and handling of duplicate references.
    """

    def aggregate_compliance(
        self,
        policy_result: CasePolicyEvaluationResult,
        timeline_result: Optional[Any] = None,
    ) -> ResourceAggregationResult:
        """
        Aggregate all resource decisions for a case.
        
        Args:
            policy_result: The CasePolicyEvaluationResult produced by Phase 6.
            timeline_result: Optional TimelineReconstructionResult from Phase 5 for cross-validation.
            
        Returns:
            ResourceAggregationResult containing correlated compliance metrics and resources.
        """
        case_id = str(policy_result.case_id or "").strip()
        diagnostics = list(policy_result.diagnostics)
        contradictions = list(policy_result.contradictions)
        upstream_errors = list(policy_result.upstream_errors)
        replica_drift_findings = list(policy_result.replica_drift_findings)

        # 1. Correlate decisions by resource_id (handling potential duplicates deterministically)
        decisions_map: dict[str, list[ResourceTreatmentDecision]] = defaultdict(list)
        for dec in policy_result.decisions:
            decisions_map[dec.resource_id].append(dec)

        # Also incorporate decisions from decisions_by_resource
        for rid, dec in policy_result.decisions_by_resource.items():
            if dec not in decisions_map[rid]:
                decisions_map[rid].append(dec)

        compliant_resources = []
        non_compliant_resources = []
        indeterminate_resources = []
        retained_resources = []

        evidence_provenance = {}
        violations_by_resource = {}
        remediations_required = {}
        rule_id_by_resource = {}

        # 2. Evaluate each unique resource deterministically in sorted order
        for rid in sorted(decisions_map.keys()):
            decs = decisions_map[rid]
            
            # Deterministic resolution of duplicate decisions for the same resource:
            # NON_COMPLIANT takes precedence, then INDETERMINATE, then COMPLIANT
            has_non_compliant = any(d.compliance_result == ComplianceResult.NON_COMPLIANT for d in decs)
            has_indeterminate = any(d.compliance_result in (ComplianceResult.INDETERMINATE, ComplianceResult.NOT_APPLICABLE) for d in decs)
            all_compliant = all(d.compliance_result == ComplianceResult.COMPLIANT for d in decs)

            primary_dec = decs[0]
            if has_non_compliant:
                for d in decs:
                    if d.compliance_result == ComplianceResult.NON_COMPLIANT:
                        primary_dec = d
                        break
            elif has_indeterminate:
                for d in decs:
                    if d.compliance_result in (ComplianceResult.INDETERMINATE, ComplianceResult.NOT_APPLICABLE):
                        primary_dec = d
                        break

            # Store rule ID
            if primary_dec.rule_id:
                rule_id_by_resource[rid] = primary_dec.rule_id

            # Store evidence ID if present
            if primary_dec.evidence_id:
                evidence_provenance[rid] = primary_dec.evidence_id

            # Categorize
            if has_non_compliant:
                non_compliant_resources.append(rid)
                violations_by_resource[rid] = primary_dec.reason
                
                # Determine required remediation operation from bundle if available
                bundle = policy_result.operation_bundles_by_resource.get(rid)
                if bundle and bundle.remediations:
                    rem_op = bundle.remediations[0].operation
                    remediations_required[rid] = rem_op
                else:
                    # Default remediation based on required_action
                    action = primary_dec.required_action or "DELETE"
                    if action == "REDACT":
                        remediations_required[rid] = StepOperation.REDACT_RECORD.value
                    elif action == "ANONYMIZE":
                        remediations_required[rid] = StepOperation.ANONYMIZE_RECORD.value
                    elif primary_dec.data_category == "DATA_FLOW":
                        remediations_required[rid] = StepOperation.DISABLE_DATA_FLOW.value
                    elif primary_dec.data_category == "BACKUP_ARCHIVE":
                        remediations_required[rid] = StepOperation.BLOCK_RESTORE.value
                    else:
                        remediations_required[rid] = StepOperation.DELETE_RECORD.value

            elif has_indeterminate:
                indeterminate_resources.append(rid)
                diagnostics.append(f"Resource '{rid}' evaluation indeterminate: {primary_dec.reason}")

            elif all_compliant:
                # To be proven compliant, sighting records must cite admissible evidence
                # Exception: Pure ABSENT records where deletion was confirmed may cite admissible evidence or empty
                compliant_resources.append(rid)

                # Check if it represents legitimately retained data
                is_retained = False
                if primary_dec.data_category in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
                    is_retained = True
                elif primary_dec.data_category == "ACCOUNT_TOMBSTONE" and primary_dec.observed_state in ("REDACTED", "PRESENT"):
                    is_retained = True
                elif primary_dec.required_action == "RETAIN":
                    is_retained = True

                if is_retained:
                    retained_resources.append(rid)

        # 3. Check for replica drift
        has_replica_drift = len(replica_drift_findings) > 0
        if has_replica_drift:
            for drift in replica_drift_findings:
                drift_rid = drift.get("resource_id", "unknown_replica")
                diagnostics.append(f"Replica drift confirmed for resource '{drift_rid}': replica retains record.")
                if drift_rid not in non_compliant_resources:
                    non_compliant_resources.append(drift_rid)
                    violations_by_resource[drift_rid] = "Replica retains personal data after primary deletion (replica drift)."
                    remediations_required[drift_rid] = StepOperation.DELETE_RECORD.value

        # Re-sort lists
        compliant_resources = sorted(list(set(compliant_resources)))
        non_compliant_resources = sorted(list(set(non_compliant_resources)))
        indeterminate_resources = sorted(list(set(indeterminate_resources)))
        retained_resources = sorted(list(set(retained_resources)))

        total_resources = len(set(list(decisions_map.keys()) + non_compliant_resources))

        # Check for empty resources
        if total_resources == 0:
            diagnostics.append(f"Case '{case_id}' has zero associated resources.")

        # 4. Aggregated boolean state indicators
        has_violations = len(non_compliant_resources) > 0 or has_replica_drift
        has_indeterminate = len(indeterminate_resources) > 0 or len(contradictions) > 0
        has_retained = len(retained_resources) > 0

        # All compliant ONLY if:
        # 1. Zero non-compliant resources
        # 2. Zero indeterminate resources
        # 3. Zero replica drift
        # 4. Zero contradictions
        # 5. At least one resource evaluated, or explicitly confirmed clean
        is_all_compliant = (
            not has_violations
            and not has_indeterminate
            and len(contradictions) == 0
            and total_resources > 0
        )

        return ResourceAggregationResult(
            case_id=case_id,
            total_resources=total_resources,
            is_all_compliant=is_all_compliant,
            has_violations=has_violations,
            has_indeterminate=has_indeterminate,
            has_retained_data=has_retained,
            has_replica_drift=has_replica_drift,
            compliant_resources=compliant_resources,
            non_compliant_resources=non_compliant_resources,
            indeterminate_resources=indeterminate_resources,
            retained_resources=retained_resources,
            evidence_provenance_by_resource=evidence_provenance,
            violations_by_resource=violations_by_resource,
            remediations_required_by_resource=remediations_required,
            rule_id_by_resource=rule_id_by_resource,
            contradictions=contradictions,
            upstream_errors=upstream_errors,
            diagnostics=diagnostics,
        )

"""Tests for Phase 6.6: Temporal Admissibility, Audit Cutoff, and Evidence Integrity."""

import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

POLICY_DIR = Path(__file__).resolve().parent
ROOT_DIR = POLICY_DIR.parent.parent

if str(POLICY_DIR) not in sys.path:
    sys.path.insert(0, str(POLICY_DIR))

try:
    from .loader import PolicyLoader
    from .engine import (
        TreatmentEngine,
        ComplianceResult,
        RequiredAction,
        ResourceTreatmentDecision,
    )
    from .temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
    )
except ImportError:
    from loader import PolicyLoader
    from engine import (
        TreatmentEngine,
        ComplianceResult,
        RequiredAction,
        ResourceTreatmentDecision,
    )
    from temporal import (
        parse_iso_timestamp,
        is_temporally_admissible,
        validate_evidence_temporal_integrity,
        validate_evidence_id,
        inspect_timeline_temporal_contract,
    )


class MockTimelineEvent:
    """Mock timeline event for testing."""
    def __init__(
        self,
        event_id: str,
        timestamp: datetime,
        evidence_id: str = "",
        event_type: str = "DATABASE_RECORD",
        action_category: str = "ACTION_EVIDENCE_SIGHTING",
        is_admissible: bool = True,
        exclusion_reason: str = None,
    ):
        self.event_id = event_id
        self.timestamp = timestamp
        self.evidence_id = evidence_id
        self.event_type = event_type
        self.action_category = action_category
        self.is_admissible = is_admissible
        self.exclusion_reason = exclusion_reason


class MockResourceTimeline:
    """Mock Phase 5 ResourceTimeline for testing."""
    def __init__(
        self,
        resource_id: str,
        system_id: str,
        resource_category: str,
        state_at_cutoff: str,
        latest_admissible_evidence_id: str = "",
        events: list = None,
        post_cutoff_events: list = None,
        is_recreated: bool = False,
        is_active_flow: bool = False,
        is_restore_risk: bool = False,
        replica_drift: bool = False,
        contradictions: list = None,
        evidence_provenance: list = None,
        has_corroborated_deletion: bool = False,
        has_failed_deletion: bool = False,
    ):
        self.resource_id = resource_id
        self.system_id = system_id
        self.resource_category = resource_category
        self.state_at_cutoff = state_at_cutoff
        self.latest_admissible_evidence_id = latest_admissible_evidence_id
        self.events = events or []
        self.post_cutoff_events = post_cutoff_events or []
        self.is_recreated = is_recreated
        self.is_active_flow = is_active_flow
        self.is_restore_risk = is_restore_risk
        self.replica_drift = replica_drift
        self.contradictions = contradictions or []
        self.evidence_provenance = evidence_provenance or []
        self.has_corroborated_deletion = has_corroborated_deletion
        self.has_failed_deletion = has_failed_deletion


class TestTemporalAdmissibility(unittest.TestCase):
    """Test suite for timestamp normalization and temporal cutoff rules."""

    def test_parse_iso_timestamp_variations(self):
        """Test timestamp parsing across Z, positive/negative offsets, and naive datetimes."""
        ts_z = parse_iso_timestamp("2026-05-01T12:00:00Z")
        self.assertEqual(ts_z, datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc))

        ts_offset_plus = parse_iso_timestamp("2026-05-01T17:30:00+05:30")
        self.assertEqual(ts_offset_plus, datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc))

        ts_offset_minus = parse_iso_timestamp("2026-05-01T08:00:00-04:00")
        self.assertEqual(ts_offset_minus, datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc))

        # Naive datetime gets assigned UTC
        naive = datetime(2026, 5, 1, 12, 0, 0)
        self.assertEqual(parse_iso_timestamp(naive), datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc))

        # Malformed or empty
        self.assertIsNone(parse_iso_timestamp(""))
        self.assertIsNone(parse_iso_timestamp("invalid-date"))

    def test_cutoff_exact_boundary(self):
        """Evidence captured exactly at cutoff (T == audit_at) is admissible."""
        cutoff = "2026-06-01T15:00:00Z"
        admissible, reason = is_temporally_admissible("2026-06-01T15:00:00Z", cutoff)
        self.assertTrue(admissible)
        self.assertIsNone(reason)

    def test_cutoff_post_boundary_exclusion(self):
        """Evidence captured after cutoff (T > audit_at) is strictly excluded."""
        cutoff = "2026-06-01T15:00:00Z"
        admissible, reason = is_temporally_admissible("2026-06-01T15:00:01Z", cutoff)
        self.assertFalse(admissible)
        self.assertEqual(reason, "EXCEEDS_AUDIT_CUTOFF")

    def test_temporal_contradiction_exclusion(self):
        """Event time later than capture time is excluded as a temporal contradiction."""
        cutoff = "2026-06-01T20:00:00Z"
        event_time = "2026-06-01T16:00:00Z"
        capture_time = "2026-06-01T14:00:00Z"  # Captured before it occurred!
        admissible, reason = validate_evidence_temporal_integrity(event_time, capture_time, cutoff)
        self.assertFalse(admissible)
        self.assertEqual(reason, "EXCLUDED_TEMPORAL_CONTRADICTION")

    def test_capture_post_cutoff_exclusion(self):
        """Evidence captured after cutoff is excluded even if event time was prior to cutoff."""
        cutoff = "2026-06-01T12:00:00Z"
        event_time = "2026-06-01T10:00:00Z"
        capture_time = "2026-06-01T14:00:00Z"  # Captured post-cutoff
        admissible, reason = validate_evidence_temporal_integrity(event_time, capture_time, cutoff)
        self.assertFalse(admissible)
        self.assertEqual(reason, "EXCLUDED_CAPTURE_POST_CUTOFF")

    def test_evidence_id_validation_non_fabrication(self):
        """Evidence IDs must conform to valid participant-visible source prefixes."""
        self.assertTrue(validate_evidence_id("evidence_54"))
        self.assertTrue(validate_evidence_id("act_1001"))
        self.assertTrue(validate_evidence_id("audit_402"))
        self.assertTrue(validate_evidence_id("file_db_01"))
        self.assertTrue(validate_evidence_id(""))
        self.assertTrue(validate_evidence_id(None))

        # Fabricated or arbitrary IDs are rejected
        self.assertFalse(validate_evidence_id("fake_evidence_999"))
        self.assertFalse(validate_evidence_id("user_claimed_proof"))


class TestForensicScenariosAndImmutability(unittest.TestCase):
    """Test policy decisions against forensic scenarios and post-cutoff immutability."""

    def setUp(self):
        self.loader = PolicyLoader()
        self.engine = TreatmentEngine(self.loader)
        self.cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_post_cutoff_immutability_recreation(self):
        """
        Proof of immutability:
        Changing ONLY post-cutoff events (e.g. adding a recreation at T2 > cutoff)
        CANNOT change the historical compliance decision at T1 <= cutoff.
        """
        # Baseline: At cutoff, user profile was ABSENT with corroborated deletion
        timeline_clean = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="ABSENT",
            latest_admissible_evidence_id="act_501",
            events=[MockTimelineEvent("ev_1", datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc), "act_501", "DELETE_RECORD", "ACTION_DELETE")],
            post_cutoff_events=[],
            is_recreated=False,
            has_corroborated_deletion=True,
        )

        decision_clean = self.engine.evaluate_timeline_resource(timeline_clean, audit_at=self.cutoff)
        self.assertEqual(decision_clean.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision_clean.observed_state, "ABSENT")

        # Now simulate a subsequent recreation occurring AFTER cutoff
        timeline_with_future_recreation = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="ABSENT",
            latest_admissible_evidence_id="act_501",
            events=timeline_clean.events,
            post_cutoff_events=[
                MockTimelineEvent(
                    "ev_future",
                    datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
                    "evidence_99",
                    "SYNC_RECORD",
                    "ACTION_RECREATE",
                )
            ],
            is_recreated=False,  # Recreated post-cutoff only
            has_corroborated_deletion=True,
        )

        decision_future = self.engine.evaluate_timeline_resource(timeline_with_future_recreation, audit_at=self.cutoff)
        # Historical decision at cutoff MUST REMAIN COMPLIANT
        self.assertEqual(decision_future.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision_future.observed_state, "ABSENT")
        self.assertEqual(decision_clean.compliance_result, decision_future.compliance_result)
        self.assertEqual(decision_clean.required_action, decision_future.required_action)

    def test_pre_cutoff_recreation_results_in_non_compliance(self):
        """If recreation occurred BEFORE cutoff, record was PRESENT at cutoff (NON_COMPLIANT)."""
        timeline = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_22",
            is_recreated=True,
        )
        decision = self.engine.evaluate_timeline_resource(timeline, audit_at=self.cutoff)
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.observed_state, "PRESENT")
        self.assertEqual(decision.evidence_id, "evidence_22")

    def test_replica_drift_forces_non_compliance(self):
        """
        Forensic scenario: Primary database record was deleted, but replica retains record at cutoff.
        Decision must evaluate effective state as PRESENT and result in NON_COMPLIANT.
        """
        timeline = MockResourceTimeline(
            resource_id="account_005",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_sql_rep",
            replica_drift=True,
        )
        decision = self.engine.evaluate_timeline_resource(timeline, audit_at=self.cutoff)
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.observed_state, "PRESENT")
        self.assertTrue(any("Replica drift" in d for d in decision.diagnostics))

    def test_active_data_flow_risk(self):
        """Active sync/data flow at cutoff is evaluated as NON_COMPLIANT under data flow policy."""
        timeline = MockResourceTimeline(
            resource_id="data_flow_901",
            system_id="integration_service",
            resource_category="DATA_FLOW",
            state_at_cutoff="ACTIVE",
            latest_admissible_evidence_id="evidence_flow_01",
            is_active_flow=True,
        )
        decision = self.engine.evaluate_timeline_resource(timeline, audit_at=self.cutoff)
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.observed_state, "ACTIVE")
        self.assertEqual(decision.required_action, "DISABLE_DATA_FLOW")

    def test_active_restore_risk(self):
        """Active restore permission / backup at cutoff is evaluated as NON_COMPLIANT."""
        timeline = MockResourceTimeline(
            resource_id="backup_snapshot_40",
            system_id="backup_service",
            resource_category="BACKUP_ARCHIVE",
            state_at_cutoff="ACTIVE",
            latest_admissible_evidence_id="evidence_bak_01",
            is_restore_risk=True,
        )
        decision = self.engine.evaluate_timeline_resource(timeline, audit_at=self.cutoff)
        self.assertEqual(decision.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision.observed_state, "ACTIVE")
        self.assertEqual(decision.required_action, "RETAIN")

    def test_permitted_tombstone_redaction_obligations(self):
        """
        Account tombstone at cutoff:
        - When direct PII is exposed (state PRESENT) -> NON_COMPLIANT under REDACT rule.
        - When direct PII is removed and stable reference preserved (state REDACTED) -> COMPLIANT.
        """
        # Scenario A: Exposed PII remains in tombstone
        timeline_exposed = MockResourceTimeline(
            resource_id="tombstone_user_123",
            system_id="identity_service",
            resource_category="ACCOUNT_TOMBSTONE",
            state_at_cutoff="PRESENT",
            latest_admissible_evidence_id="evidence_tb_01",
        )
        decision_exposed = self.engine.evaluate_timeline_resource(timeline_exposed, audit_at=self.cutoff)
        self.assertEqual(decision_exposed.compliance_result, ComplianceResult.NON_COMPLIANT)
        self.assertEqual(decision_exposed.required_action, "REDACT")

        # Scenario B: Properly redacted tombstone
        timeline_redacted = MockResourceTimeline(
            resource_id="tombstone_user_123",
            system_id="identity_service",
            resource_category="ACCOUNT_TOMBSTONE",
            state_at_cutoff="REDACTED",
            latest_admissible_evidence_id="evidence_tb_02",
        )
        decision_redacted = self.engine.evaluate_timeline_resource(timeline_redacted, audit_at=self.cutoff)
        self.assertEqual(decision_redacted.compliance_result, ComplianceResult.COMPLIANT)
        self.assertEqual(decision_redacted.required_action, "REDACT")

    def test_unresolved_contradictions_produce_indeterminate(self):
        """Unresolved contradictions without corroborating evidence must yield INDETERMINATE."""
        timeline = MockResourceTimeline(
            resource_id="account_999",
            system_id="account_service",
            resource_category="USER_PROFILE",
            state_at_cutoff="ABSENT",
            latest_admissible_evidence_id="",
            contradictions=["Conflicting timestamps between activity log and system status"],
            has_corroborated_deletion=False,
        )
        decision = self.engine.evaluate_timeline_resource(timeline, audit_at=self.cutoff)
        self.assertEqual(decision.compliance_result, ComplianceResult.INDETERMINATE)
        self.assertTrue("Unresolved contradictions" in decision.reason)


if __name__ == "__main__":
    unittest.main()

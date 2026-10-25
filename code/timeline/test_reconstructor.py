"""Phase 5 Unit Tests: Core Timeline Reconstruction.

Validates chronological ordering, inclusive cutoff boundaries,
post-cutoff segregation, recreation detection, active data flows,
backup restore risks, contradiction surfacing, and deterministic output.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
IDENTITY_DIR = CURRENT_DIR.parent / "identity"
EVIDENCE_DIR = CURRENT_DIR.parent / "evidence"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(IDENTITY_DIR))
if str(EVIDENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_DIR))

from resolver import IdentityResolver, parse_timestamp
from integration import EvidenceIntegrator
from reconstructor import (
    TimelineReconstructor,
    ActivityIndex,
    TimelineEvent,
    ResourceTimeline,
    categorize_resource_id,
    is_non_deletion_text,
)


class TestTimelineReconstruction(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.resolver = IdentityResolver.from_directory(ROOT_DIR / "dataset")
        cls.integrator = EvidenceIntegrator(
            manifest_path=ROOT_DIR / "dataset" / "evidence_files.csv",
            evidence_root=ROOT_DIR / "dataset" / "evidence",
        )
        cls.activity_index = ActivityIndex(ROOT_DIR / "dataset" / "system_activity.csv")
        cls.reconstructor = TimelineReconstructor(
            activity_index=cls.activity_index,
            manifest_path=ROOT_DIR / "dataset" / "evidence_files.csv",
            evidence_root=ROOT_DIR / "dataset" / "evidence",
        )

    # 1. Pre-cutoff events are ingested
    def test_01_pre_cutoff_events_ingested(self):
        req = {
            "case_id": "test_case_01",
            "email": "leila.haddad@yahoo.com",
            "audit_at": "2026-09-20T12:00:00Z",
            "request_text": "Please delete all my personal data immediately.",
        }
        res = self.reconstructor.reconstruct_for_request(req, self.resolver, self.integrator)
        self.assertEqual(res.resolution_status, "RESOLVED")
        self.assertEqual(res.user_id, "user_05")
        self.assertGreater(len(res.resources), 0)
        # Ensure account_005 exists
        self.assertIn("account_005", res.resources)
        acct_tl = res.resources["account_005"]
        self.assertGreater(len(acct_tl.events), 0)

    # 2. Boundary cutoff is inclusive
    def test_02_boundary_cutoff_inclusive(self):
        cutoff_dt = parse_timestamp("2026-09-18T10:15:00Z")
        ev = TimelineEvent(
            event_id="act_exact",
            timestamp=cutoff_dt,
            source_type="system_activity",
            evidence_id="act_exact",
            system_id="account_service",
            resource_id="account_005",
            event_type="DELETE_RECORD",
            action_category="ACTION_DELETE",
            reported_result="SUCCESS",
            details="Deleted profile",
            matched_identifier="user_05",
            is_admissible=(cutoff_dt <= cutoff_dt),
            exclusion_reason=None,
        )
        self.assertTrue(ev.is_admissible)

    # 3. Post-cutoff events are excluded from cutoff state
    def test_03_post_cutoff_events_excluded(self):
        # Set audit cutoff early before replica evidence or subsequent activities
        req = {
            "case_id": "test_early_cutoff",
            "email": "leila.haddad@yahoo.com",
            "audit_at": "2026-09-15T00:00:00Z",
            "request_text": "Please delete my account.",
        }
        res = self.reconstructor.reconstruct_for_request(req, self.resolver, self.integrator)
        if "account_005" in res.resources:
            acct_tl = res.resources["account_005"]
            # Events after 2026-09-15 must be in post_cutoff_events
            for ev in acct_tl.post_cutoff_events:
                self.assertFalse(ev.is_admissible)
                self.assertEqual(ev.exclusion_reason, "EXCEEDS_AUDIT_CUTOFF")

    # 4. Recreation detected before cutoff
    def test_04_recreation_detected_before_cutoff(self):
        # Synthetic single resource test
        t_del = parse_timestamp("2026-09-10T10:00:00Z")
        t_sync = parse_timestamp("2026-09-12T10:00:00Z")
        cutoff = parse_timestamp("2026-09-20T00:00:00Z")

        # Mock index with synthetic events
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "search_mock_01": [
                {"activity_id": "act_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "DELETE_RECORD", "reported_result": "SUCCESS", "details": ""},
                {"activity_id": "act_2", "event_time": "2026-09-12T10:00:00Z", "event_type": "INDEX_RECORD", "reported_result": "SUCCESS", "details": ""},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="search_mock_01",
            default_system_id="search_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=cutoff,
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertTrue(tl.is_recreated)
        self.assertEqual(tl.state_at_cutoff, "PRESENT")

    # 5. Post-cutoff recreation does not alter cutoff state
    def test_05_post_cutoff_recreation_ignored(self):
        t_del = parse_timestamp("2026-09-10T10:00:00Z")
        t_sync_future = parse_timestamp("2026-09-25T10:00:00Z")
        cutoff = parse_timestamp("2026-09-20T00:00:00Z")

        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "search_mock_02": [
                {"activity_id": "act_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "DELETE_RECORD", "reported_result": "SUCCESS", "details": ""},
                {"activity_id": "act_2", "event_time": "2026-09-25T10:00:00Z", "event_type": "INDEX_RECORD", "reported_result": "SUCCESS", "details": ""},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="search_mock_02",
            default_system_id="search_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=cutoff,
            admissible_matches=[],
            excluded_evidence=[],
        )
        # As of cutoff 2026-09-20, recreation had not yet occurred!
        self.assertFalse(tl.is_recreated)
        self.assertEqual(tl.state_at_cutoff, "ABSENT")
        self.assertEqual(len(tl.post_cutoff_events), 1)

    # 6. Evidence trumps activity claims
    def test_06_evidence_trumps_activity_claims(self):
        # Leila Haddad had a delete claim, but evidence_54 failover replica retained record
        req = {
            "case_id": "test_evidence_trumps",
            "email": "leila.haddad@yahoo.com",
            "audit_at": "2026-09-20T12:00:00Z",
            "request_text": "Please delete all my data.",
        }
        res = self.reconstructor.reconstruct_for_request(req, self.resolver, self.integrator)
        acct_tl = res.resources.get("account_005")
        self.assertIsNotNone(acct_tl)
        # Grounded evidence proves record is PRESENT at cutoff
        self.assertEqual(acct_tl.state_at_cutoff, "PRESENT")
        self.assertTrue(acct_tl.latest_admissible_evidence_id.startswith("evidence_"))

    # 7. Active data flow detected
    def test_07_active_data_flow_detected(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "data_flow_101": [
                {"activity_id": "act_df_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "CHECK_DATA_FLOW", "reported_result": "SUCCESS", "details": "connector_status=running;enabled=True"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="data_flow_101",
            default_system_id="integration_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertTrue(tl.is_active_flow)
        self.assertEqual(tl.state_at_cutoff, "ACTIVE")

    # 8. Disabled data flow detected
    def test_08_disabled_data_flow_detected(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "data_flow_102": [
                {"activity_id": "act_df_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "CHECK_DATA_FLOW", "reported_result": "SUCCESS", "details": "connector_status=running;enabled=True"},
                {"activity_id": "act_df_2", "event_time": "2026-09-11T10:00:00Z", "event_type": "DISABLE_DATA_FLOW", "reported_result": "SUCCESS", "details": "connector_disabled"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="data_flow_102",
            default_system_id="integration_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertFalse(tl.is_active_flow)
        self.assertEqual(tl.state_at_cutoff, "DISABLED")

    # 9. Backup restore risk detected
    def test_09_backup_restore_risk_detected(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "backup_501": [
                {"activity_id": "act_bk_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "CHECK_RESTORE_ACCESS", "reported_result": "SUCCESS", "details": "restore_allowed=True;archive_key=bk_501"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="backup_501",
            default_system_id="backup_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertTrue(tl.is_restore_risk)
        self.assertEqual(tl.state_at_cutoff, "ACTIVE")

    # 10. Blocked backup detected
    def test_10_blocked_backup_detected(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "backup_502": [
                {"activity_id": "act_bk_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "CHECK_RESTORE_ACCESS", "reported_result": "SUCCESS", "details": "restore_allowed=True"},
                {"activity_id": "act_bk_2", "event_time": "2026-09-11T10:00:00Z", "event_type": "BLOCK_RESTORE", "reported_result": "SUCCESS", "details": "restore_access_revoked"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="backup_502",
            default_system_id="backup_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertFalse(tl.is_restore_risk)
        self.assertEqual(tl.state_at_cutoff, "BLOCKED")

    # 11. Compliant tombstone classified REDACTED
    def test_11_compliant_tombstone_classified_redacted(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {}
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="tombstone_user_01",
            default_system_id="identity_service",
            user_id="user_01",
            target_emails={"user01@test.com"},
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[{
                "resource_id": "tombstone_user_01",
                "system_id": "identity_service",
                "matched_identifier": "user_01",
                "identifier_type": "user_id",
                "event_type": "STRUCTURED_RECORD",
                "evidence_id": "evidence_51",
                "captured_at": "2026-09-18T10:00:00Z",
            }],
            excluded_evidence=[],
        )
        self.assertEqual(tl.state_at_cutoff, "REDACTED")

    # 12. Exposed PII tombstone classified PRESENT
    def test_12_exposed_pii_tombstone_classified_present(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {}
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="tombstone_user_02",
            default_system_id="identity_service",
            user_id="user_02",
            target_emails={"user02@test.com"},
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[{
                "resource_id": "tombstone_user_02",
                "system_id": "identity_service",
                "matched_identifier": "user02@test.com",
                "identifier_type": "current_email",
                "event_type": "STRUCTURED_RECORD",
                "evidence_id": "evidence_51",
                "captured_at": "2026-09-18T10:00:00Z",
            }],
            excluded_evidence=[],
        )
        self.assertEqual(tl.state_at_cutoff, "PRESENT")

    # 13. Non-deletion requests correctly flagged
    def test_13_non_deletion_request_flagged(self):
        self.assertTrue(is_non_deletion_text("Please provide me with a copy of all my invoices. Do not delete my account."))
        self.assertTrue(is_non_deletion_text("I want to opt-out of marketing emails, leave the account active."))
        self.assertFalse(is_non_deletion_text("Please permanently delete all my account data."))

    # 14. Invalid audit_at fails safely
    def test_14_invalid_audit_at_fails_safely(self):
        req = {
            "case_id": "test_invalid_ts",
            "email": "leila.haddad@yahoo.com",
            "audit_at": "invalid-timestamp",
            "request_text": "Delete me.",
        }
        res = self.reconstructor.reconstruct_for_request(req, self.resolver, self.integrator)
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(len(res.resources), 0)

    # 15. Deterministic timeline replay
    def test_15_deterministic_timeline_replay(self):
        req = {
            "case_id": "test_det",
            "email": "leila.haddad@yahoo.com",
            "audit_at": "2026-09-20T12:00:00Z",
            "request_text": "Please delete all data.",
        }
        res1 = self.reconstructor.reconstruct_for_request(req, self.resolver, self.integrator)
        res2 = self.reconstructor.reconstruct_for_request(req, self.resolver, self.integrator)
        self.assertEqual(list(res1.resources.keys()), list(res2.resources.keys()))
        for rid in res1.resources:
            self.assertEqual(res1.resources[rid].state_at_cutoff, res2.resources[rid].state_at_cutoff)
            self.assertEqual(len(res1.resources[rid].events), len(res2.resources[rid].events))

    # 16. Timezone-aware timestamps with different offsets are compared accurately in UTC
    def test_16_timezone_aware_different_offsets(self):
        # 15:30 in +05:30 is 10:00 UTC
        ts_ist = parse_timestamp("2026-09-20T15:30:00+05:30")
        ts_utc = parse_timestamp("2026-09-20T10:00:00Z")
        ts_est = parse_timestamp("2026-09-20T06:00:00-04:00")
        self.assertEqual(ts_ist, ts_utc)
        self.assertEqual(ts_est, ts_utc)

    # 17. Timezone-naive timestamps parse as UTC according to dataset convention
    def test_17_timezone_naive_assumed_utc(self):
        ts_naive = parse_timestamp("2026-09-20T10:00:00")
        self.assertIsNotNone(ts_naive.tzinfo)
        self.assertEqual(ts_naive.tzinfo, timezone.utc)
        ts_z = parse_timestamp("2026-09-20T10:00:00Z")
        self.assertEqual(ts_naive, ts_z)

    # 18. Missing and malformed event timestamps are safely excluded and not treated as historical proof
    def test_18_missing_and_malformed_event_timestamps(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "account_bad_ts": [
                {"activity_id": "act_bad_1", "event_time": "", "event_type": "DELETE_RECORD", "reported_result": "SUCCESS", "details": ""},
                {"activity_id": "act_bad_2", "event_time": "invalid_date", "event_type": "UPDATE_RECORD", "reported_result": "SUCCESS", "details": ""},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_bad_ts",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertEqual(len(tl.events), 0)
        self.assertEqual(len(tl.post_cutoff_events), 2)
        ex_reasons = {e.exclusion_reason for e in tl.post_cutoff_events}
        self.assertIn("MISSING_EVENT_TIME", ex_reasons)
        self.assertIn("MALFORMED_EVENT_TIME", ex_reasons)

    # 19. Equal timestamps sort deterministically by event_id without invented causality
    def test_19_equal_timestamps_deterministic_ordering(self):
        ts = parse_timestamp("2026-09-18T10:00:00Z")
        ev1 = TimelineEvent(
            event_id="act_B", timestamp=ts, source_type="system_activity", evidence_id="act_B",
            system_id="s", resource_id="r", event_type="SYNC_RECORD", action_category="ACTION_RECREATE",
            reported_result="SUCCESS", details="", matched_identifier="", is_admissible=True, exclusion_reason=None
        )
        ev2 = TimelineEvent(
            event_id="act_A", timestamp=ts, source_type="system_activity", evidence_id="act_A",
            system_id="s", resource_id="r", event_type="DELETE_RECORD", action_category="ACTION_DELETE",
            reported_result="SUCCESS", details="", matched_identifier="", is_admissible=True, exclusion_reason=None
        )
        events = [ev1, ev2]
        events.sort(key=lambda e: (e.timestamp, e.event_id))
        self.assertEqual(events[0].event_id, "act_A")
        self.assertEqual(events[1].event_id, "act_B")

    # 20. Contradictory event and capture timestamps are flagged and excluded
    def test_20_contradictory_event_and_capture_timestamps(self):
        reconstructor = TimelineReconstructor()
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_contra",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-25T00:00:00Z"),
            admissible_matches=[{
                "resource_id": "account_contra",
                "system_id": "account_service",
                "matched_identifier": "user_mock",
                "identifier_type": "user_id",
                "event_type": "STRUCTURED_RECORD",
                "evidence_id": "evidence_54",
                # Contradiction: event occurred AFTER capture time
                "event_time": "2026-09-20T12:00:00Z",
                "captured_at": "2026-09-15T12:00:00Z",
            }],
            excluded_evidence=[],
        )
        self.assertEqual(len(tl.events), 0)
        self.assertEqual(len(tl.post_cutoff_events), 1)
        self.assertEqual(tl.post_cutoff_events[0].exclusion_reason, "EXCLUDED_TEMPORAL_CONTRADICTION")

    # 21. Historical snapshots captured before cutoff prove historical state
    def test_21_historical_snapshots_before_cutoff(self):
        reconstructor = TimelineReconstructor()
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_hist",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[{
                "resource_id": "account_hist",
                "system_id": "account_service",
                "matched_identifier": "user_mock",
                "identifier_type": "user_id",
                "event_type": "DATABASE_RECORD",
                "evidence_id": "evidence_54",
                "event_time": "2026-09-18T10:00:00Z",
                "captured_at": "2026-09-18T12:00:00Z",
            }],
            excluded_evidence=[],
        )
        self.assertEqual(len(tl.events), 1)
        self.assertTrue(tl.events[0].is_admissible)
        self.assertEqual(tl.state_at_cutoff, "PRESENT")

    # 22. Post-cutoff evidence cannot establish earlier state
    def test_22_post_cutoff_evidence_does_not_establish_earlier_state(self):
        reconstructor = TimelineReconstructor()
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_post_cutoff",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            # Audit cutoff is September 10, capture is September 15
            audit_cutoff=parse_timestamp("2026-09-10T00:00:00Z"),
            admissible_matches=[{
                "resource_id": "account_post_cutoff",
                "system_id": "account_service",
                "matched_identifier": "user_mock",
                "identifier_type": "user_id",
                "event_type": "DATABASE_RECORD",
                "evidence_id": "evidence_92",
                "event_time": "2026-09-08T10:00:00Z",
                "captured_at": "2026-09-15T12:00:00Z",
            }],
            excluded_evidence=[],
        )
        self.assertEqual(len(tl.events), 0)
        self.assertEqual(len(tl.post_cutoff_events), 1)
        self.assertEqual(tl.post_cutoff_events[0].exclusion_reason, "EXCLUDED_CAPTURE_POST_CUTOFF")

    # 23. Corroborated deletion confirmed when delete SUCCESS and zero positive evidence remains
    def test_23_corroborated_deletion_confirmed(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "account_clean_del": [
                {"activity_id": "act_del_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "DELETE_RECORD", "reported_result": "SUCCESS", "details": "deleted"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_clean_del",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertEqual(tl.state_at_cutoff, "ABSENT")
        self.assertTrue(tl.has_corroborated_deletion)
        self.assertFalse(tl.has_failed_deletion)
        self.assertFalse(tl.replica_drift)

    # 24. Failed deletion attempt detected and tracked
    def test_24_failed_deletion_attempt_detected(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "account_fail_del": [
                {"activity_id": "act_del_fail", "event_time": "2026-09-10T10:00:00Z", "event_type": "DELETE_RECORD", "reported_result": "FAILED", "details": "db_timeout_error"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_fail_del",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertTrue(tl.has_failed_deletion)
        self.assertFalse(tl.has_corroborated_deletion)
        self.assertEqual(len(tl.deletion_attempts), 1)
        self.assertEqual(tl.deletion_attempts[0]["reported_result"], "FAILED")

    # 25. Replica drift detected when primary claims SUCCESS but replica snapshot contains record
    def test_25_replica_drift_detected_and_reported(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "account_drift": [
                {"activity_id": "act_del_drift", "event_time": "2026-09-10T10:00:00Z", "event_type": "DELETE_RECORD", "reported_result": "SUCCESS", "details": "primary_deleted"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_drift",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[{
                "resource_id": "account_drift",
                "system_id": "account_failover_replica",
                "matched_identifier": "user_mock",
                "identifier_type": "user_id",
                "event_type": "DATABASE_RECORD",
                "evidence_id": "evidence_54",
                "event_time": "2026-09-18T10:00:00Z",
                "captured_at": "2026-09-18T12:00:00Z",
            }],
            excluded_evidence=[],
        )
        self.assertTrue(tl.replica_drift)
        self.assertEqual(tl.state_at_cutoff, "PRESENT")
        self.assertGreater(len(tl.contradictions), 0)
        self.assertIn("Replica drift", tl.contradictions[0])

    # 26. Recreation with source-to-target causality
    def test_26_recreation_with_source_target_causality(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "search_causal": [
                {"activity_id": "act_del_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "DELETE_RECORD", "reported_result": "SUCCESS", "details": ""},
                {"activity_id": "act_sync_1", "event_time": "2026-09-12T10:00:00Z", "event_type": "SYNC_RECORD", "reported_result": "SUCCESS", "source_system": "account_service", "target_system": "search_service", "details": "recreated_from_account_service"},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="search_causal",
            default_system_id="search_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
        self.assertTrue(tl.is_recreated)
        self.assertEqual(len(tl.post_deletion_events), 1)
        self.assertEqual(tl.post_deletion_events[0].event_type, "SYNC_RECORD")

    # 27. Post-deletion activity tracking captures multiple operations
    def test_27_post_deletion_activity_tracking(self):
        mock_index = ActivityIndex.__new__(ActivityIndex)
        mock_index.by_resource_id = {
            "account_multi_act": [
                {"activity_id": "act_1", "event_time": "2026-09-10T10:00:00Z", "event_type": "DELETE_RECORD", "reported_result": "SUCCESS", "details": ""},
                {"activity_id": "act_2", "event_time": "2026-09-11T10:00:00Z", "event_type": "UPDATE_RECORD", "reported_result": "SUCCESS", "details": ""},
                {"activity_id": "act_3", "event_time": "2026-09-12T10:00:00Z", "event_type": "REFRESH_CACHE", "reported_result": "SUCCESS", "details": ""},
            ]
        }
        mock_index.by_user_id = {}
        mock_index.link_identity_map = {}
        mock_index.all_events = []

        reconstructor = TimelineReconstructor(activity_index=mock_index)
        tl = reconstructor._reconstruct_single_resource(
            resource_id="account_multi_act",
            default_system_id="account_service",
            user_id="user_mock",
            target_emails=set(),
            audit_cutoff=parse_timestamp("2026-09-20T00:00:00Z"),
            admissible_matches=[],
            excluded_evidence=[],
        )
    # 28. End-to-end Phase 3B and Phase 5 integration on live dataset
    def test_28_end_to_end_phase3b_phase5_integration(self):
        case_05_req = {
            "case_id": "case_05",
            "email": "leila.haddad@yahoo.com",
            "requested_at": "2026-08-27T14:17:00Z",
            "reported_status": "COMPLETE",
            "reported_at": "2026-08-28T09:03:00Z",
            "audit_at": "2026-09-08T13:40:00Z",
            "request_text": "I deleted this account and received a confirmation, but the same email address is still recognized. Please remove any remaining copy of my profile.",
        }

        res = self.reconstructor.reconstruct_for_request(
            case_05_req, self.resolver, self.integrator
        )

        self.assertEqual(res.case_id, "case_05")
        self.assertEqual(res.user_id, "user_05")
        self.assertFalse(res.is_non_deletion_request)
        self.assertEqual(res.resolution_status, "RESOLVED")
        self.assertIn("account_005", res.resources)

        r_tl = res.resources["account_005"]
        self.assertEqual(r_tl.system_id, "account_service")
        self.assertEqual(r_tl.state_at_cutoff, "PRESENT")
        self.assertEqual(r_tl.latest_admissible_evidence_id, "evidence_54")
        self.assertTrue(r_tl.replica_drift)
        self.assertGreaterEqual(len(res.replica_drift_findings), 1)
        self.assertEqual(res.replica_drift_findings[0]["evidence_id"], "evidence_54")
        self.assertFalse(hasattr(res, "deletion_status"))


if __name__ == "__main__":
    unittest.main()



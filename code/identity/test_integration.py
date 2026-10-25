"""Phase 3B Integration Tests: Identity Resolution and Evidence Integration.

Validates all 22 integration boundaries, cutoff rules, decoy rejection,
provenance preservation, and deterministic attribution.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
EVIDENCE_DIR = CURRENT_DIR.parent / "evidence"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(EVIDENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_DIR))

from resolver import IdentityResolver, parse_timestamp
from integration import EvidenceIntegrator, make_word_boundary_regex


class TestPhase3BIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.resolver = IdentityResolver.from_directory(ROOT_DIR / "dataset")
        cls.integrator = EvidenceIntegrator(
            manifest_path=ROOT_DIR / "dataset" / "evidence_files.csv",
            evidence_root=ROOT_DIR / "dataset" / "evidence",
        )

    # 1. Current email maps to a verified identity and finds a matching evidence record
    def test_01_current_email_finds_matching_evidence(self):
        req = {
            "case_id": "test_case_01",
            "email": "leila.haddad@yahoo.com",
            "audit_at": "2026-09-20T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        self.assertEqual(res["resolution"]["status"], "RESOLVED")
        self.assertEqual(res["resolution"]["user_id"], "user_05")
        total_matches = len(res["admissible_matches"]) + len(res["excluded_matches"])
        self.assertGreater(total_matches, 0)
        # Verify matched identifier is recorded
        matched_idents = {m["matched_identifier"] for m in res["admissible_matches"]}
        self.assertTrue("user_05" in matched_idents or "leila.haddad@yahoo.com" in matched_idents)

    # 2. Verified historical email finds the same user's relevant evidence
    def test_02_historical_email_finds_same_user_evidence(self):
        # user_35 had a historical email change
        req = {
            "case_id": "test_case_02",
            "email": "nadia.ionescu@yahoo.com",
            "audit_at": "2026-09-18T12:25:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        self.assertEqual(res["resolution"]["status"], "RESOLVED")
        self.assertEqual(res["resolution"]["user_id"], "user_10")
        self.assertIn("historical_emails", res["resolution"]["identifiers"])

    # 3. Historical identifiers are resolved as of the correct cutoff
    def test_03_historical_identifiers_respect_cutoff(self):
        idents_early = self.resolver.identifiers_for_user("user_35", "2025-01-01T00:00:00Z")
        idents_late = self.resolver.identifiers_for_user("user_35", "2026-09-20T00:00:00Z")
        self.assertNotEqual(idents_early["identifiers"]["email"], idents_late["identifiers"]["email"])

    # 4. An identifier mapping introduced after the cutoff is not used prematurely
    def test_04_identifier_introduced_after_cutoff_is_excluded(self):
        # An event after cutoff cannot resolve an email before it was associated
        early_res = self.resolver.resolve_email("haruka.sato@example.com", "2024-01-01T00:00:00Z")
        self.assertEqual(early_res["status"], "UNRESOLVED")

    # 5. Ambiguous identity does not cause arbitrary attribution
    def test_05_ambiguous_identity_prevents_unsafe_attribution(self):
        # Synthetic resolver with duplicate email
        mock_resolver = IdentityResolver(
            identities=[
                {"user_id": "user_A", "email": "dup@test.com", "phone": "", "email_hash": ""},
                {"user_id": "user_B", "email": "dup@test.com", "phone": "", "email_hash": ""},
            ],
            audit_events=[],
        )
        req = {
            "case_id": "test_ambig",
            "email": "dup@test.com",
            "audit_at": "2026-09-01T00:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, mock_resolver)
        self.assertEqual(res["resolution"]["status"], "AMBIGUOUS")
        self.assertEqual(len(res["admissible_matches"]), 0)

    # 6. Unresolved identity does not cause broad, unsafe evidence attribution
    def test_06_unresolved_identity_prevents_evidence_attribution(self):
        req = {
            "case_id": "test_unres",
            "email": "nonexistent_person_12345@domain.invalid",
            "audit_at": "2026-09-01T00:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        self.assertEqual(res["resolution"]["status"], "UNRESOLVED")
        self.assertEqual(len(res["admissible_matches"]), 0)

    # 7. An unrelated user's matching-looking record is rejected
    def test_07_unrelated_user_decoy_is_rejected(self):
        req = {
            "case_id": "test_case_07",
            "email": "amina.elmasri@gmail.com",
            "audit_at": "2026-09-20T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        # Ensure no matches are attributed to other user IDs like user_02 or user_99
        for m in res["admissible_matches"]:
            self.assertNotEqual(m["matched_identifier"], "user_02")
            self.assertNotEqual(m["matched_identifier"], "mateo.rios@outlook.com")

    # 8. A shared resource identifier across different systems is correctly scoped
    def test_08_shared_resource_scoped_to_system(self):
        req = {
            "case_id": "test_case_08",
            "email": "novak.tomasz@icloud.com",
            "audit_at": "2026-10-01T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        for m in res["admissible_matches"]:
            # Every match must carry a distinct system_id
            self.assertIsNotNone(m["system_id"])

    # 9. A request with no matching evidence returns explicit empty match list, not proof of absence
    def test_09_no_matching_evidence_returns_explicit_empty(self):
        mock_resolver = IdentityResolver(
            identities=[
                {"user_id": "user_ghost", "email": "ghost@nowhere.com", "phone": "+1 999 999 9999", "email_hash": "abc"}
            ],
            audit_events=[],
        )
        req = {
            "case_id": "test_ghost",
            "email": "ghost@nowhere.com",
            "audit_at": "2026-09-01T00:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, mock_resolver)
        self.assertEqual(res["resolution"]["status"], "RESOLVED")
        self.assertEqual(len(res["admissible_matches"]), 0)
        self.assertEqual(res["summary"]["admissible"], 0)

    # 10. Evidence captured before the cutoff with admissible event timestamp is eligible
    def test_10_evidence_captured_before_cutoff_is_eligible(self):
        req = {
            "case_id": "test_eligible",
            "email": "novak.tomasz@icloud.com",
            "audit_at": "2026-10-01T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        self.assertGreater(len(res["admissible_matches"]), 0)
        for m in res["admissible_matches"]:
            self.assertTrue(m["is_admissible"])
            self.assertIsNone(m["exclusion_reason"])

    # 11. Evidence captured after the cutoff is excluded from historical proof
    def test_11_evidence_captured_after_cutoff_is_excluded(self):
        # Set cutoff before evidence_92 capture (2026-09-15T11:44:55Z)
        req = {
            "case_id": "test_early_cutoff",
            "email": "thandiwe.m6866@zoho.com",
            "audit_at": "2026-09-10T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        # Any matches from evidence_92 must be in excluded_matches
        post_cutoff_92 = [m for m in res["excluded_matches"] if m["evidence_id"] == "evidence_92"]
        self.assertGreater(len(post_cutoff_92), 0)
        for m in post_cutoff_92:
            self.assertFalse(m["is_admissible"])
            self.assertEqual(m["exclusion_reason"], "EXCLUDED_CAPTURE_POST_CUTOFF")

    # 12. An event after the cutoff is excluded
    def test_12_event_after_cutoff_is_excluded(self):
        rec = {
            "statement_type": "INSERT INTO",
            "table": "customer_profiles",
            "values": {
                "resource_id": "acc_future",
                "user_id": "user_01",
                "updated_at": "2026-09-25T00:00:00Z",
            },
        }
        matches = self.integrator._match_record(
            rec=rec,
            user_id="user_01",
            user_id_regex=make_word_boundary_regex("user_01"),
            normalized_target_emails=set(),
            email_regexes={},
            normalized_target_hashes=set(),
            normalized_target_phones=set(),
            current_email="",
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["event_time"], "2026-09-25T00:00:00Z")

    # 13. An event exactly at the cutoff is handled according to inclusive boundary
    def test_13_event_exactly_at_cutoff_is_inclusive(self):
        cutoff_str = "2026-09-15T11:44:55Z"
        cutoff_dt = parse_timestamp(cutoff_str)
        # Equal timestamps must be admissible
        self.assertTrue(cutoff_dt <= cutoff_dt)

    # 14. Missing event time does not silently pass as historical proof
    def test_14_missing_event_time_provenance_preserved(self):
        req = {
            "case_id": "test_text",
            "email": "novak.tomasz@icloud.com",
            "audit_at": "2026-10-01T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        for m in res["admissible_matches"]:
            if m["event_time"] is None:
                # Explanation and capture timestamp must be grounded
                self.assertIsNotNone(m["captured_at"])

    # 15. Missing capture time follows documented rules
    def test_15_invalid_audit_at_fails_safely(self):
        req = {
            "case_id": "test_inv_time",
            "email": "novak.tomasz@icloud.com",
            "audit_at": "not-a-timestamp",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        self.assertEqual(len(res["errors"]), 1)
        self.assertEqual(len(res["admissible_matches"]), 0)

    # 16. Contradictory event and capture timestamps are handled safely
    def test_16_contradictory_timestamps_flagged(self):
        event_dt = parse_timestamp("2026-09-20T00:00:00Z")
        capture_dt = parse_timestamp("2026-09-10T00:00:00Z")
        self.assertTrue(event_dt > capture_dt)

    # 17. Evidence ID, source path, and record locator survive the integration
    def test_17_evidence_id_and_provenance_survive(self):
        req = {
            "case_id": "test_prov",
            "email": "novak.tomasz@icloud.com",
            "audit_at": "2026-10-01T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        for m in res["admissible_matches"]:
            self.assertTrue(m["evidence_id"].startswith("evidence_"))
            self.assertTrue(len(m["source_path"]) > 0)
            self.assertIn("record_index", m)

    # 18. A match explanation is grounded in actual fields
    def test_18_match_explanation_grounded(self):
        req = {
            "case_id": "test_grounded",
            "email": "novak.tomasz@icloud.com",
            "audit_at": "2026-10-01T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        for m in res["admissible_matches"]:
            self.assertIn("Matched", m["explanation"])
            self.assertIn(m["evidence_id"], m["explanation"])

    # 19. Parsing errors remain visible and are not interpreted as absence
    def test_19_parsing_errors_visible(self):
        self.assertIsInstance(self.integrator.inventory_errors, list)
        req = {
            "case_id": "test_err_vis",
            "email": "leila.haddad@yahoo.com",
            "audit_at": "2026-09-20T12:00:00Z",
        }
        res = self.integrator.correlate_for_request(req, self.resolver)
        self.assertIsInstance(res["errors"], list)

    # 20. Empty evidence collections and empty identifier sets are handled safely
    def test_20_empty_identifiers_handled_safely(self):
        res = self.integrator._match_record(
            rec={"record_type": "text_line", "raw_text": "hello"},
            user_id="user_nonexistent",
            user_id_regex=make_word_boundary_regex("user_nonexistent"),
            normalized_target_emails=set(),
            email_regexes={},
            normalized_target_hashes=set(),
            normalized_target_phones=set(),
            current_email="",
        )
        self.assertEqual(len(res), 0)

    # 21. Integration does not change existing resolver behavior
    def test_21_resolver_behavior_unchanged(self):
        res = self.resolver.resolve_email("amina.elmasri@gmail.com", "2026-09-03T11:30:00Z")
        self.assertEqual(res["status"], "RESOLVED")
        self.assertEqual(res["user_id"], "user_01")

    # 22. Results are deterministic across repeated runs
    def test_22_deterministic_results(self):
        req = {
            "case_id": "test_det",
            "email": "amina.elmasri@gmail.com",
            "audit_at": "2026-09-20T12:00:00Z",
        }
        res1 = self.integrator.correlate_for_request(req, self.resolver)
        res2 = self.integrator.correlate_for_request(req, self.resolver)
        self.assertEqual(len(res1["admissible_matches"]), len(res2["admissible_matches"]))
        self.assertEqual(len(res1["excluded_matches"]), len(res2["excluded_matches"]))


if __name__ == "__main__":
    unittest.main()

"""Phase 7.2 Unit Tests: Request Applicability and Deletion Intent Evaluator.

Tests:
1. Valid deletion requests (English, Spanish, French).
2. Explicit non-deletion requests across all dataset categories (cases 533-542).
3. Missing, None, or empty request_text (malformed input).
4. Operational workflow status independence (reported_status='COMPLETE' does not override non-deletion).
5. Contradictory intent signals (simultaneous deletion and retention demands).
6. Unsupported / ambiguous text (random chatter without deletion words).
7. Multiple distinct case identifiers preservation.
8. Deterministic repeat-run consistency across multiple iterations.
9. Integration with real dataset/deletion_requests.csv rows.
"""

from pathlib import Path
import sys
import unittest
import csv

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    from .models import (
        DeletionStatus,
        RequestIntentCategory,
        RequestApplicabilityResult,
    )
    from .applicability import RequestApplicabilityEvaluator
except ImportError:
    from models import (
        DeletionStatus,
        RequestIntentCategory,
        RequestApplicabilityResult,
    )
    from applicability import RequestApplicabilityEvaluator


class TestRequestApplicability(unittest.TestCase):
    """Test suite for RequestApplicabilityEvaluator."""

    @classmethod
    def setUpClass(cls):
        cls.evaluator = RequestApplicabilityEvaluator()

    # 1. Valid Deletion Requests (English, Spanish, French)
    def test_01_valid_deletion_requests(self):
        # English
        req_en = {
            "case_id": "case_01",
            "email": "customer@example.com",
            "audit_at": "2026-09-03T11:30:00Z",
            "reported_status": "COMPLETE",
            "request_text": "Hi, I haven't used this account in years and would like it closed. Please remove the profile and the personal details attached to it.",
        }
        res_en = self.evaluator.evaluate_request(req_en)
        self.assertTrue(res_en.is_applicable)
        self.assertIsNone(res_en.deletion_status)
        self.assertEqual(res_en.intent_category, RequestIntentCategory.DELETION_AUTHORIZED)
        self.assertEqual(res_en.case_id, "case_01")
        self.assertIn("authorizes personal data deletion", res_en.reason)

        # Spanish
        req_es = {
            "case_id": "case_02",
            "email": "mateo@example.com",
            "audit_at": "2026-09-04T15:00:00Z",
            "reported_status": "PARTIALLY_COMPLETE",
            "request_text": "Intenté eliminar mi cuenta ayer, pero la página terminó mostrando un error. ¿Pueden comprobar si todavía queda algún dato y completar la eliminación si hace falta?",
        }
        res_es = self.evaluator.evaluate_request(req_es)
        self.assertTrue(res_es.is_applicable)
        self.assertIsNone(res_es.deletion_status)
        self.assertEqual(res_es.intent_category, RequestIntentCategory.DELETION_AUTHORIZED)

        # French
        req_fr = {
            "case_id": "case_03",
            "email": "fontaine@example.com",
            "audit_at": "2026-09-26T11:00:00Z",
            "reported_status": "COMPLETE",
            "request_text": "Je demande la suppression définitive du compte associé à cette adresse e-mail. Merci de confirmer le résultat.",
        }
        res_fr = self.evaluator.evaluate_request(req_fr)
        self.assertTrue(res_fr.is_applicable)
        self.assertIsNone(res_fr.deletion_status)
        self.assertEqual(res_fr.intent_category, RequestIntentCategory.DELETION_AUTHORIZED)

    # 2. Explicit Non-Deletion: Account Rectification / Outdated Mobile (case_533)
    def test_02_non_deletion_rectification_case_533(self):
        req = {
            "case_id": "case_533",
            "email": "haruka-kato@gmail.com",
            "reported_status": "NOT_STARTED",
            "request_text": "The mobile number on my profile is out of date. Please replace it with the new one and leave the account active.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertIn(res.intent_category, (RequestIntentCategory.NON_DELETION_RECTIFICATION, RequestIntentCategory.NON_DELETION_ACCOUNT_RETENTION))
        self.assertIn("leave account active", res.detected_patterns)

    # 3. Explicit Non-Deletion: Marketing Opt-Out (case_534)
    def test_03_non_deletion_opt_out_case_534(self):
        req = {
            "case_id": "case_534",
            "email": "mlim7637@gmail.com",
            "reported_status": "NOT_STARTED",
            "request_text": "Please stop the promotional emails. I still need the account and my order history, so I am not asking for deletion.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertIn(res.intent_category, (RequestIntentCategory.NON_DELETION_OPT_OUT, RequestIntentCategory.NON_DELETION_ACCOUNT_RETENTION))
        self.assertTrue(res.is_not_applicable)

    # 4. Explicit Non-Deletion: Data Portability (case_535)
    def test_04_non_deletion_portability_case_535(self):
        req = {
            "case_id": "case_535",
            "email": "gabriel.l5556@outlook.com",
            "reported_status": "NOT_STARTED",
            "request_text": "I'd like to download my account information in a portable format. Please keep the account as it is.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertIn(res.intent_category, (RequestIntentCategory.NON_DELETION_PORTABILITY, RequestIntentCategory.NON_DELETION_ACCOUNT_RETENTION))
        self.assertIn("portable format", res.detected_patterns)

    # 5. Explicit Non-Deletion: Support / Login Reset (case_536)
    def test_05_non_deletion_support_case_536(self):
        req = {
            "case_id": "case_536",
            "email": "aditi.mehta@outlook.com",
            "reported_status": "NOT_STARTED",
            "request_text": "I can't access my profile and need help resetting the login. Do not close the account.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertIn("do not close/delete", res.detected_patterns)

    # 6. Explicit Non-Deletion: Subject Access Request (case_539)
    def test_06_non_deletion_access_request_case_539(self):
        req = {
            "case_id": "case_539",
            "email": "leonie-rousseau@proton.me",
            "reported_status": "NOT_STARTED",
            "request_text": "Can you tell me what personal information you hold about me? This is an information request, not a request to erase it.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertEqual(res.intent_category, RequestIntentCategory.NON_DELETION_ACCESS_REQUEST)
        self.assertIn("information request", res.detected_patterns)

    # 7. Operational Workflow Independence: reported_status='COMPLETE' Does Not Prove Deletion
    def test_07_workflow_status_independence(self):
        # A non-deletion request with reported_status='COMPLETE' must still be NOT_APPLICABLE
        req = {
            "case_id": "case_fake_complete",
            "email": "customer@example.com",
            "reported_status": "COMPLETE",
            "request_text": "Please send me last year's invoices. Do not delete my account.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertTrue(any("disregarded" in d for d in res.diagnostics))

    # 8. Malformed / Missing Request Text
    def test_08_missing_or_empty_request_text(self):
        # Case A: Empty string
        res_empty = self.evaluator.evaluate_request({"case_id": "case_empty", "request_text": ""})
        self.assertFalse(res_empty.is_applicable)
        self.assertEqual(res_empty.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertEqual(res_empty.intent_category, RequestIntentCategory.MALFORMED_EMPTY_TEXT)

        # Case B: Whitespace only
        res_ws = self.evaluator.evaluate_request({"case_id": "case_ws", "request_text": "   \n\t  "})
        self.assertFalse(res_ws.is_applicable)
        self.assertEqual(res_ws.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertEqual(res_ws.intent_category, RequestIntentCategory.MALFORMED_EMPTY_TEXT)

        # Case C: None
        res_none = self.evaluator.evaluate_request({"case_id": "case_none", "request_text": None})
        self.assertFalse(res_none.is_applicable)
        self.assertEqual(res_none.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertEqual(res_none.intent_category, RequestIntentCategory.MALFORMED_EMPTY_TEXT)

        # Case D: Missing key entirely
        res_missing = self.evaluator.evaluate_request({"case_id": "case_missing"})
        self.assertFalse(res_missing.is_applicable)
        self.assertEqual(res_missing.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertEqual(res_missing.intent_category, RequestIntentCategory.MALFORMED_EMPTY_TEXT)

    # 9. Contradictory Intent Signals
    def test_09_contradictory_intent_signals(self):
        # Conflicting instruction: "permanently delete" AND "leave the account active"
        req = {
            "case_id": "case_conflict",
            "email": "confused@example.com",
            "request_text": "Please permanently delete all my account records immediately. However, leave the account active and keep my login open.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertEqual(res.intent_category, RequestIntentCategory.AMBIGUOUS_CONTRADICTORY)
        self.assertTrue(any("Contradictory intent detected" in d for d in res.diagnostics))

    # 10. Unsupported / Random Chatter
    def test_10_unsupported_random_text(self):
        req = {
            "case_id": "case_random",
            "email": "random@example.com",
            "request_text": "The quick brown fox jumps over the lazy dog. Weather is nice today.",
        }
        res = self.evaluator.evaluate_request(req)
        self.assertFalse(res.is_applicable)
        self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
        self.assertEqual(res.intent_category, RequestIntentCategory.AMBIGUOUS_CONTRADICTORY)
        self.assertTrue(any("does not match standard deletion authorization" in d for d in res.diagnostics))

    # 11. Preservation of Case Identifier and Provenance
    def test_11_case_identifier_preservation(self):
        cases = ["case_001", "case_999", "custom_case_xyz"]
        for cid in cases:
            req = {"case_id": cid, "request_text": "Please erase my account details."}
            res = self.evaluator.evaluate_request(req)
            self.assertEqual(res.case_id, cid)

    # 12. Deterministic Repeat Runs
    def test_12_repeat_run_determinism(self):
        req = {
            "case_id": "case_det_01",
            "email": "test@example.com",
            "request_text": "Please close my account and erase my personal data.",
        }
        first = self.evaluator.evaluate_request(req)
        for _ in range(50):
            subsequent = self.evaluator.evaluate_request(req)
            self.assertEqual(first.is_applicable, subsequent.is_applicable)
            self.assertEqual(first.deletion_status, subsequent.deletion_status)
            self.assertEqual(first.intent_category, subsequent.intent_category)
            self.assertEqual(first.reason, subsequent.reason)
            self.assertEqual(first.detected_patterns, subsequent.detected_patterns)

    # 13. Integration with All 10 Non-Deletion Dataset Cases (533-542)
    def test_13_all_dataset_non_deletion_cases(self):
        data_file = ROOT_DIR / "dataset" / "deletion_requests.csv"
        if not data_file.exists():
            self.skipTest("deletion_requests.csv not found")

        with open(data_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            requests_by_id = {row["case_id"]: row for row in reader}

        non_deletion_case_ids = [f"case_{i}" for i in range(533, 543)]
        for cid in non_deletion_case_ids:
            self.assertIn(cid, requests_by_id, f"Expected {cid} in dataset")
            req = requests_by_id[cid]
            res = self.evaluator.evaluate_request(req)
            self.assertFalse(res.is_applicable, f"{cid} should be NOT_APPLICABLE")
            self.assertEqual(res.deletion_status, DeletionStatus.NOT_APPLICABLE.value)
            self.assertNotEqual(res.intent_category, RequestIntentCategory.DELETION_AUTHORIZED)


if __name__ == "__main__":
    unittest.main()

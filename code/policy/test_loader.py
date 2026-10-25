"""Phase 6.2 Unit Tests: Policy Loader, Schema Validation, and Lookup.

Validates policy loading against the real dataset/deletion_rules.csv,
as well as error handling on missing files, malformed headers, duplicate columns,
missing mandatory fields, invalid treatments, duplicate rule IDs, conflicting
actions, and contextual rule ordering.
"""

import io
from pathlib import Path
import sys
import unittest

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from loader import (
    PolicyLoader,
    PolicyRule,
    PolicyValidationResult,
    SUPPORTED_ACTIONS,
    KNOWN_CATEGORIES,
    DEFAULT_RULES_PATH,
)


class TestPolicyLoader(unittest.TestCase):

    # 1. Valid loading of the real challenge policy file
    def test_01_load_real_deletion_rules(self):
        loader = PolicyLoader(DEFAULT_RULES_PATH)
        res = loader.load()

        self.assertTrue(res.is_valid, f"Validation errors: {res.errors}")
        self.assertEqual(len(res.errors), 0)
        self.assertEqual(len(res.rules), 15)
        self.assertEqual(len(res.rules_by_id), 15)
        self.assertIn("USER_PROFILE", res.rules_by_category)
        self.assertIn("ACCOUNT_TOMBSTONE", res.rules_by_category)

        # Check rule_01
        rule_01 = loader.get_rule_by_id("rule_01")
        self.assertIsNotNone(rule_01)
        self.assertEqual(rule_01.data_category, "USER_PROFILE")
        self.assertEqual(rule_01.required_action, "DELETE")
        self.assertEqual(rule_01.condition, "Always")

        # Check rule_15 (Tombstone)
        rule_15 = loader.get_rule_by_id("rule_15")
        self.assertIsNotNone(rule_15)
        self.assertEqual(rule_15.data_category, "ACCOUNT_TOMBSTONE")
        self.assertEqual(rule_15.required_action, "REDACT")

    # 2. Missing policy file behavior
    def test_02_missing_policy_file(self):
        loader = PolicyLoader(Path("/non/existent/path/deletion_rules.csv"))
        res = loader.load()

        self.assertFalse(res.is_valid)
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0]["error_type"], "FILE_NOT_FOUND")

    # 3. Empty policy file
    def test_03_empty_policy_file(self):
        loader = PolicyLoader(io.StringIO(""))
        res = loader.load()

        self.assertFalse(res.is_valid)
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0]["error_type"], "EMPTY_FILE")

    # 4. Missing required columns in header
    def test_04_missing_required_column(self):
        csv_data = "rule_id,data_category,required_action\nrule_01,USER_PROFILE,DELETE\n"
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertFalse(res.is_valid)
        self.assertTrue(any(e["error_type"] == "MISSING_COLUMN" for e in res.errors))
        err = [e for e in res.errors if e["error_type"] == "MISSING_COLUMN"][0]
        self.assertIn("condition", err["missing_columns"])

    # 5. Duplicate column in header
    def test_05_duplicate_column_in_header(self):
        csv_data = "rule_id,data_category,condition,required_action,condition\nrule_01,USER_PROFILE,Always,DELETE,Always\n"
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertFalse(res.is_valid)
        self.assertTrue(any(e["error_type"] == "DUPLICATE_COLUMN" for e in res.errors))

    # 6. Missing mandatory field in row
    def test_06_missing_mandatory_field(self):
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_01,,Always,DELETE\n"
            ",SECONDARY_IDENTIFIER,Always,DELETE\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertFalse(res.is_valid)
        missing_errors = [e for e in res.errors if e["error_type"] == "MISSING_FIELD"]
        self.assertEqual(len(missing_errors), 2)
        self.assertIn("data_category", missing_errors[0]["missing_fields"])
        self.assertIn("rule_id", missing_errors[1]["missing_fields"])

    # 7. Invalid treatment action
    def test_07_invalid_treatment_action(self):
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_01,USER_PROFILE,Always,PURGE_FOREVER\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertFalse(res.is_valid)
        invalid_errors = [e for e in res.errors if e["error_type"] == "INVALID_TREATMENT"]
        self.assertEqual(len(invalid_errors), 1)
        self.assertEqual(invalid_errors[0]["required_action"], "PURGE_FOREVER")

    # 8. Duplicate rule_id
    def test_08_duplicate_rule_id(self):
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_01,USER_PROFILE,Always,DELETE\n"
            "rule_01,SEARCH_INDEX_ENTRY,Always,DELETE\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertFalse(res.is_valid)
        dup_errors = [e for e in res.errors if e["error_type"] == "DUPLICATE_RULE_ID"]
        self.assertEqual(len(dup_errors), 1)
        self.assertEqual(dup_errors[0]["rule_id"], "rule_01")

    # 9. Conflicting rules (same category & condition, conflicting action)
    def test_09_conflicting_rules(self):
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_01,USER_PROFILE,Always,DELETE\n"
            "rule_02,USER_PROFILE,Always,RETAIN\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertFalse(res.is_valid)
        conflict_errors = [e for e in res.errors if e["error_type"] == "CONFLICTING_RULE"]
        self.assertEqual(len(conflict_errors), 1)
        self.assertEqual(conflict_errors[0]["rule_id"], "rule_02")
        self.assertEqual(conflict_errors[0]["conflicting_with"], "rule_01")

    # 10. Legitimate contextual rules for same category with different conditions
    def test_10_contextual_rules_same_category(self):
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_05,SUPPORT_MESSAGE,Conversation contains shared customer context,REDACT\n"
            "rule_06,SUPPORT_MESSAGE,Message is customer personal note only,DELETE\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertTrue(res.is_valid)
        rules = loader.get_rules_for_category("SUPPORT_MESSAGE")
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].rule_id, "rule_05")
        self.assertEqual(rules[0].required_action, "REDACT")
        self.assertEqual(rules[1].rule_id, "rule_06")
        self.assertEqual(rules[1].required_action, "DELETE")

    # 11. Deterministic lookup and ordering
    def test_11_deterministic_ordering(self):
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_10,MARKETING_PROFILE,Always,DELETE\n"
            "rule_01,USER_PROFILE,Always,DELETE\n"
            "rule_03,SEARCH_INDEX_ENTRY,Always,DELETE\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        self.assertTrue(res.is_valid)
        # Rules should be deterministically sorted by (category, rule_id)
        categories = [r.data_category for r in res.rules]
        self.assertEqual(categories, ["MARKETING_PROFILE", "SEARCH_INDEX_ENTRY", "USER_PROFILE"])

    # 12. Unrecognized category produces structured warning without crashing
    def test_12_unrecognized_category_warning(self):
        csv_data = (
            "rule_id,data_category,condition,required_action\n"
            "rule_99,FUTURE_QUANTUM_STORE,Always,DELETE\n"
        )
        loader = PolicyLoader(io.StringIO(csv_data))
        res = loader.load()

        # Should still be valid, but with a warning
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.warnings), 1)
        self.assertEqual(res.warnings[0]["warning_type"], "UNKNOWN_CATEGORY")
        self.assertEqual(res.warnings[0]["data_category"], "FUTURE_QUANTUM_STORE")


if __name__ == "__main__":
    unittest.main()

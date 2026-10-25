import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sql_parser import (
    extract_schemas,
    parse_create_table,
    parse_insert_statement,
    extract_identifiers,
)


class TestSQLParser(unittest.TestCase):

    def test_create_table_extracts_columns(self):
        statement = (
            "CREATE TABLE users "
            "(user_id TEXT, email TEXT, status TEXT);"
        )
        result = parse_create_table(statement)

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["columns"],
            ["user_id", "email", "status"],
        )

    def test_extract_schemas_finds_multiple_tables(self):
        sql = (
            "CREATE TABLE users (user_id TEXT, email TEXT);"
            "CREATE TABLE exports (export_id TEXT, status TEXT);"
        )
        schemas, errors = extract_schemas(sql)

        self.assertEqual(len(schemas), 2)
        self.assertEqual(schemas["users"], ["user_id", "email"])
        self.assertEqual(
            schemas["exports"],
            ["export_id", "status"],
        )
        self.assertEqual(errors, [])

    def test_insert_maps_values_to_schema_columns(self):
        schemas = {
            "users": ["user_id", "email", "status"],
        }
        statement = (
            "INSERT INTO users VALUES "
            "('u1', 'test@example.com', 'deleted');"
        )

        result = parse_insert_statement(statement, schemas)

        self.assertTrue(result["ok"])
        self.assertEqual(result["values"]["user_id"], "u1")
        self.assertEqual(
            result["values"]["email"],
            "test@example.com",
        )
        self.assertEqual(result["values"]["status"], "deleted")

    def test_insert_extracts_identifier_fields(self):
        schemas = {
            "users": ["user_id", "email", "status"],
        }
        statement = (
            "INSERT INTO users VALUES "
            "('u1', 'test@example.com', 'deleted');"
        )

        result = parse_insert_statement(statement, schemas)

        self.assertIn(
            {"field": "user_id", "value": "u1"},
            result["identifiers"],
        )
        self.assertIn(
            {"field": "email", "value": "test@example.com"},
            result["identifiers"],
        )

    def test_insert_rejects_value_count_mismatch(self):
        schemas = {
            "users": ["user_id", "email", "status"],
        }
        statement = "INSERT INTO users VALUES ('u1', 'test@example.com');"

        result = parse_insert_statement(statement, schemas)

        self.assertFalse(result["ok"])
        self.assertIn("columns but INSERT has", result["error"])

    def test_insert_rejects_unknown_table_when_schema_supplied(self):
        result = parse_insert_statement(
            "INSERT INTO unknown_table VALUES ('u1');",
            {"users": ["user_id"]},
        )

        self.assertFalse(result["ok"])
        self.assertIn("No CREATE TABLE schema", result["error"])

    def test_null_and_escaped_quotes_are_preserved(self):
        schemas = {
            "users": ["user_id", "email", "note"],
        }
        statement = (
            "INSERT INTO users VALUES "
            "('u1', NULL, 'user''s record');"
        )

        result = parse_insert_statement(statement, schemas)

        self.assertTrue(result["ok"])
        self.assertIsNone(result["values"]["email"])
        self.assertEqual(
            result["values"]["note"],
            "user's record",
        )

    def test_identifier_extraction_does_not_infer_identity(self):
        fields = [
            {"field": "email", "value": "test@example.com"},
            {"field": "status", "value": "deleted"},
            {"field": "trace_id", "value": "tr-123"},
        ]

        result = extract_identifiers(fields)

        self.assertEqual(
            result,
            [{"field": "email", "value": "test@example.com"}],
        )

    def test_real_sql_files_have_no_schema_errors(self):
        dataset = Path("dataset/evidence")

        if not dataset.exists():
            self.skipTest("Dataset evidence directory not found")

        sql_files = sorted(dataset.rglob("*.sql"))
        self.assertEqual(len(sql_files), 24)

        for path in sql_files:
            with self.subTest(file=path.name):
                sql_text = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                schemas, errors = extract_schemas(sql_text)

                self.assertTrue(schemas, f"No schemas extracted from {path}")
                self.assertEqual(errors, [], f"Schema errors in {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


"""Tests for the evidence inventory validator."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector import build_inventory


class TestEvidenceInventory(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.evidence_dir = self.root / "evidence"
        self.evidence_dir.mkdir()
        self.manifest = self.root / "evidence_files.csv"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_manifest(self, rows, columns=None):
        if columns is None:
            columns = [
                "file_id",
                "file_path",
                "origin",
                "captured_at",
            ]

        with self.manifest.open(
            "w", newline="", encoding="utf-8"
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=columns,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)

    def make_row(
        self,
        file_id="evidence_01",
        file_path="evidence/sample.txt",
        captured_at="2026-09-15T11:00:00Z",
    ):
        return {
            "file_id": file_id,
            "file_path": file_path,
            "origin": "test_source",
            "captured_at": captured_at,
        }

    def test_real_manifest_has_94_valid_entries(self):
        repo_root = Path(__file__).resolve().parents[2]
        manifest = repo_root / "dataset" / "evidence_files.csv"
        evidence_root = repo_root / "dataset" / "evidence"

        result = build_inventory(manifest, evidence_root)

        self.assertEqual(result["manifest_rows"], 94)
        self.assertEqual(len(result["entries"]), 94)
        self.assertEqual(
            sum(entry["valid"] for entry in result["entries"]),
            94,
        )
        self.assertEqual(result["errors"], [])

    def test_valid_file_passes(self):
        sample = self.evidence_dir / "sample.txt"
        sample.write_text("test evidence", encoding="utf-8")

        self.write_manifest([self.make_row()])

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertTrue(result["entries"][0]["valid"])
        self.assertEqual(result["entries"][0]["errors"], [])

    def test_missing_file_is_reported(self):
        self.write_manifest([self.make_row()])

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertFalse(result["entries"][0]["valid"])
        self.assertTrue(
            any(
                "does not exist" in error
                for error in result["entries"][0]["errors"]
            )
        )

    def test_path_traversal_is_rejected(self):
        outside_file = self.root / "outside.txt"
        outside_file.write_text("not evidence", encoding="utf-8")

        self.write_manifest([
            self.make_row(file_path="../outside.txt")
        ])

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertFalse(result["entries"][0]["valid"])
        self.assertIn(
            "Path escapes evidence directory",
            result["entries"][0]["errors"],
        )

    def test_absolute_path_is_rejected(self):
        outside_file = self.root / "outside.txt"
        outside_file.write_text("not evidence", encoding="utf-8")

        self.write_manifest([
            self.make_row(file_path=str(outside_file))
        ])

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertFalse(result["entries"][0]["valid"])
        self.assertIn(
            "Absolute paths are not allowed",
            result["entries"][0]["errors"],
        )

    def test_duplicate_file_id_is_reported(self):
        sample = self.evidence_dir / "sample.txt"
        sample.write_text("test evidence", encoding="utf-8")

        self.write_manifest([
            self.make_row(file_id="duplicate"),
            self.make_row(file_id="duplicate"),
        ])

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertTrue(result["entries"][0]["valid"])
        self.assertFalse(result["entries"][1]["valid"])
        self.assertIn(
            "Duplicate file_id",
            result["entries"][1]["errors"],
        )

    def test_invalid_timestamp_is_reported(self):
        sample = self.evidence_dir / "sample.txt"
        sample.write_text("test evidence", encoding="utf-8")

        self.write_manifest([
            self.make_row(captured_at="not-a-timestamp")
        ])

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertFalse(result["entries"][0]["valid"])
        self.assertIn(
            "Invalid captured_at timestamp",
            result["entries"][0]["errors"],
        )

    def test_missing_required_column_is_reported(self):
        self.write_manifest(
            [self.make_row()],
            columns=["file_id", "file_path", "origin"],
        )

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertEqual(result["entries"], [])
        self.assertTrue(
            any(
                "Missing required columns" in error
                for error in result["errors"]
            )
        )

    def test_empty_manifest_is_reported(self):
        self.manifest.write_text("", encoding="utf-8")

        result = build_inventory(self.manifest, self.evidence_dir)

        self.assertEqual(result["entries"], [])
        self.assertTrue(
            any(
                "Manifest is empty" in error
                for error in result["errors"]
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)


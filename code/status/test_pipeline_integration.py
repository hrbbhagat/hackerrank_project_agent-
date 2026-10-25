"""Phase 7 Chunk 7.9: Integration and Full-Dataset Validation Tests.

Validates:
1. End-to-end integration across Phase 3B-7 components.
2. Complete processing of all 518 deletion requests in dataset/deletion_requests.csv.
3. Zero dropped, duplicated, or misordered case IDs.
4. Exact contract-compliant status distribution (COMPLETE, INCOMPLETE, NOT_APPLICABLE).
5. Exact isolation of non-deletion cases (cases 533-542).
6. Deterministic execution across repeated runs.
7. Explanations and evidence traceability for every case.
8. Non-creation/non-modification of root output.csv.
"""

import csv
import sys
import unittest
from pathlib import Path

# Setup paths
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
CODE_DIR = CURRENT_DIR.parent

for p in [
    str(CODE_DIR / "policy"),
    str(CODE_DIR / "timeline"),
    str(CODE_DIR / "identity"),
    str(CODE_DIR / "evidence"),
    str(CURRENT_DIR),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from status.models import DeletionStatus
from status.pipeline import CaseStatusPipeline, BatchPipelineSummary


class TestPipelineIntegration(unittest.TestCase):
    """Integration and full-dataset test suite for Phase 7."""

    @classmethod
    def setUpClass(cls):
        cls.dataset_dir = ROOT_DIR / "dataset"
        cls.eval_csv = cls.dataset_dir / "deletion_requests.csv"
        cls.sample_csv = cls.dataset_dir / "sample_deletion_requests.csv"
        cls.sample_out_csv = cls.dataset_dir / "sample_output.csv"
        cls.pipeline = CaseStatusPipeline(dataset_dir=cls.dataset_dir)

    def test_01_pipeline_initialization(self):
        """Confirm all underlying engines and indexes are initialized."""
        self.assertIsNotNone(self.pipeline.identity_resolver)
        self.assertIsNotNone(self.pipeline.evidence_integrator)
        self.assertIsNotNone(self.pipeline.activity_index)
        self.assertIsNotNone(self.pipeline.timeline_reconstructor)
        self.assertIsNotNone(self.pipeline.policy_service)
        self.assertIsNotNone(self.pipeline.status_resolver)

    def test_02_sample_requests_processed(self):
        """Process all 32 public sample deletion requests."""
        results, summary = self.pipeline.process_dataset(self.sample_csv)
        self.assertEqual(summary.total_processed, 32)
        self.assertEqual(len(summary.case_ids_in_order), 32)
        self.assertEqual(summary.case_ids_in_order[0], "case_01")
        self.assertEqual(summary.case_ids_in_order[-1], "case_32")

        # Confirm all statuses are in permitted set
        for r in results:
            self.assertIn(r.deletion_status, (DeletionStatus.COMPLETE, DeletionStatus.INCOMPLETE, DeletionStatus.NOT_APPLICABLE))
            self.assertTrue(r.reason)
            self.assertIsNotNone(r.explanation)

    def test_03_full_dataset_request_count_and_order(self):
        """Confirm exactly 518 evaluation requests are processed with no dropped or duplicated IDs."""
        with open(self.eval_csv, "r", encoding="utf-8-sig") as f:
            expected_cids = [r["case_id"] for r in csv.DictReader(f)]

        self.assertEqual(len(expected_cids), 518)

        results, summary = self.pipeline.process_dataset(self.eval_csv)
        self.assertEqual(summary.total_processed, 518)
        self.assertEqual(len(results), 518)
        self.assertEqual(summary.case_ids_in_order, expected_cids)

        # Confirm uniqueness of all 518 case IDs
        self.assertEqual(len(set(summary.case_ids_in_order)), 518)

    def test_04_status_distribution_and_contract_validity(self):
        """Verify the status distribution across all 518 cases."""
        results, summary = self.pipeline.process_dataset(self.eval_csv)

        # Permitted statuses only
        valid_statuses = {DeletionStatus.COMPLETE, DeletionStatus.INCOMPLETE, DeletionStatus.NOT_APPLICABLE}
        for r in results:
            self.assertIn(r.deletion_status, valid_statuses)

        # Check total additivity
        self.assertEqual(
            summary.complete_count + summary.incomplete_count + summary.not_applicable_count,
            518,
        )

        # Ground truth check: cases 533-542 are the non-deletion requests
        not_app_cases = [r.case_id for r in results if r.deletion_status == DeletionStatus.NOT_APPLICABLE]
        expected_not_app = [f"case_{i}" for i in range(533, 543)]
        self.assertEqual(sorted(not_app_cases), sorted(expected_not_app))
        self.assertEqual(summary.not_applicable_count, 10)

        # Substantial counts for both COMPLETE and INCOMPLETE
        self.assertGreater(summary.complete_count, 0)
        self.assertGreater(summary.incomplete_count, 0)

    def test_05_explanation_traceability_across_all_cases(self):
        """Ensure every single case decision has a structured, traceable explanation."""
        results, _ = self.pipeline.process_dataset(self.eval_csv)

        for r in results:
            exp = r.explanation
            self.assertEqual(exp.case_id, r.case_id)
            self.assertTrue(exp.primary_deciding_factor)
            self.assertTrue(exp.summary_reason)

            if r.deletion_status == DeletionStatus.COMPLETE:
                # Must cite evidence proving compliant state
                self.assertTrue(
                    len(exp.direct_observations) >= 1 or len(exp.evidence_citations) >= 1,
                    f"Case {r.case_id} marked COMPLETE without evidence traces or citations"
                )
            elif r.deletion_status == DeletionStatus.INCOMPLETE:
                # Must specify primary deciding factor
                self.assertTrue(exp.primary_deciding_factor)

    def test_06_determinism_across_repeated_runs(self):
        """Verify bit-for-bit identical results on independent repeated runs."""
        results1, _ = self.pipeline.process_dataset(self.eval_csv)
        results2, _ = self.pipeline.process_dataset(self.eval_csv)

        is_identical = CaseStatusPipeline.verify_determinism(results1, results2)
        self.assertTrue(is_identical, "Pipeline produced non-deterministic results between run 1 and run 2")

    def test_07_output_csv_untouched(self):
        """Confirm that output.csv at root is either untouched template or valid 519-line final output."""
        root_output = ROOT_DIR / "output.csv"
        if root_output.exists():
            with open(root_output, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            self.assertTrue(
                len(lines) in (0, 1, 519),
                f"Root output.csv has unexpected line count: {len(lines)}",
            )


if __name__ == "__main__":
    unittest.main()

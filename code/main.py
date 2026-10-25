#!/usr/bin/env python3
"""
Main Production Entry Point for HackerRank Orchestrate (October 2026)
Challenge: Ghost Data Still Exists

Executes the complete, deterministic forensic deletion-audit pipeline:
1. Loads and validates deletion requests from dataset/deletion_requests.csv
2. Preloads evidence files, identity snapshots, historical audit logs, and system activity
3. Performs identity resolution, evidence correlation, timeline reconstruction, and policy evaluation
4. Resolves authoritative deletion status (COMPLETE, INCOMPLETE, NOT_APPLICABLE)
5. Generates deterministically sequenced, consecutively numbered, contract-validated step plans
6. Writes output.csv to the repository root sorted by case_id
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Setup import paths safely
REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = REPO_ROOT / "code"

for p in [str(CODE_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from status.pipeline import CaseStatusPipeline
from planner.orchestrator import StepPlannerOrchestrator
from planner.sequencer import CaseStepPlan


def setup_logging(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("orchestrate.main")
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Ghost Data Still Exists forensic deletion-audit pipeline."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=REPO_ROOT / "dataset" / "deletion_requests.csv",
        help="Path to input deletion_requests.csv",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=REPO_ROOT / "output.csv",
        help="Path to destination output.csv (default: repo root output.csv)",
    )
    parser.add_argument(
        "--manifest",
        "-m",
        type=Path,
        default=REPO_ROOT / "dataset" / "evidence_files.csv",
        help="Path to evidence manifest file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of cases to process (for benchmarking)",
    )
    return parser.parse_args()


def run_pipeline(
    input_path: Path,
    output_path: Path,
    manifest_path: Optional[Path] = None,
    limit: Optional[int] = None,
    logger: Optional[logging.Logger] = None,
) -> tuple[int, list[CaseStepPlan], dict[str, Any]]:
    """
    Execute the forensic deletion-audit pipeline and write output.csv.
    """
    if logger is None:
        logger = logging.getLogger("orchestrate.main")

    logger.info("Starting Ghost Data Still Exists forensic audit pipeline...")
    logger.info("Repository Root: %s", REPO_ROOT)
    logger.info("Input Dataset:   %s", input_path)
    logger.info("Output Target:   %s", output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input request file not found: {input_path}")

    # Read and sort input requests by case_id
    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        requests = list(reader)

    total_requests = len(requests)
    logger.info("Loaded %d requests from input CSV", total_requests)

    # Challenge specification requires rows sorted by case_id
    requests.sort(key=lambda r: r.get("case_id", ""))

    if limit is not None and limit > 0:
        requests = requests[:limit]
        logger.info("Processing limited to %d requests", len(requests))

    # Initialize production pipeline with preloaded evidence
    logger.info("Initializing CaseStatusPipeline and preloading evidence catalog...")
    pipeline_start = time.perf_counter()
    pipeline = CaseStatusPipeline(preload_evidence=True)
    orchestrator = StepPlannerOrchestrator(
        pipeline=pipeline,
        manifest_path=manifest_path or (REPO_ROOT / "dataset" / "evidence_files.csv"),
    )
    logger.info("Pipeline initialized in %.2fs", time.perf_counter() - pipeline_start)

    # Process all cases
    plans: list[CaseStepPlan] = []
    status_counts: dict[str, int] = {"COMPLETE": 0, "INCOMPLETE": 0, "NOT_APPLICABLE": 0}
    phase_counts: dict[str, int] = {"FINDING": 0, "REMEDIATION": 0, "VERIFICATION": 0}
    errors: list[dict[str, Any]] = []

    logger.info("Executing end-to-end audit and step planning across %d requests...", len(requests))
    plan_start = time.perf_counter()

    for idx, req in enumerate(requests, start=1):
        case_id = req.get("case_id", f"unknown_{idx}")
        try:
            plan, _ = orchestrator.plan_request(req)
            plans.append(plan)

            status = plan.case_status
            status_counts[status] = status_counts.get(status, 0) + 1

            for s in plan.steps:
                phase_counts[s.phase] = phase_counts.get(s.phase, 0) + 1

            if not plan.is_valid:
                errors.append({"case_id": case_id, "errors": plan.errors})
                logger.error("Validation error for %s: %s", case_id, plan.errors)

        except Exception as exc:
            logger.exception("Fatal planning exception on %s: %s", case_id, exc)
            errors.append({"case_id": case_id, "exception": str(exc)})

        if idx % 100 == 0 or idx == len(requests):
            logger.info("Processed %d/%d requests (%.1f%%)...", idx, len(requests), (idx / len(requests)) * 100)

    elapsed = time.perf_counter() - plan_start
    throughput = len(plans) / elapsed if elapsed > 0 else 0.0
    logger.info("Planning completed in %.2fs (%.2f cases/sec)", elapsed, throughput)
    logger.info("Status distribution: %s", status_counts)
    logger.info("Step counts by phase: %s (Total steps: %d)", phase_counts, sum(phase_counts.values()))

    if errors:
        logger.error("%d cases encountered validation or planning errors!", len(errors))
        raise RuntimeError(f"Pipeline produced {len(errors)} invalid plans. Output writing aborted.")

    # Write output.csv with exact required header: case_id,deletion_status,steps_json
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Writing verified predictions to %s ...", output_path)

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for plan in plans:
            writer.writerow([plan.case_id, plan.case_status, plan.steps_json])

    logger.info("Successfully generated %s with %d data rows.", output_path.name, len(plans))

    metrics = {
        "total_requests": len(requests),
        "successful_plans": len(plans),
        "status_distribution": status_counts,
        "phase_distribution": phase_counts,
        "total_steps": sum(phase_counts.values()),
        "elapsed_seconds": elapsed,
        "throughput_cases_per_sec": throughput,
    }

    return 0, plans, metrics


def main() -> int:
    args = parse_args()
    logger = setup_logging(verbose=args.verbose)

    try:
        exit_code, _, metrics = run_pipeline(
            input_path=args.input,
            output_path=args.output,
            manifest_path=args.manifest,
            limit=args.limit,
            logger=logger,
        )
        logger.info("=" * 60)
        logger.info("PIPELINE EXECUTION COMPLETE - EXIT CODE %d", exit_code)
        logger.info("=" * 60)
        return exit_code
    except Exception as exc:
        logger.critical("PIPELINE EXECUTION FAILED: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

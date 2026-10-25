#!/usr/bin/env python3
"""
Comprehensive Output Validator for HackerRank Orchestrate: Ghost Data Still Exists.

Enforces:
1. CSV and row integrity:
   - Exact header: case_id,deletion_status,steps_json
   - Exactly 518 data rows matching input requests
   - Correct sorting by case_id
   - No duplicate, missing, or extraneous case IDs
   - Valid statuses in {COMPLETE, INCOMPLETE, NOT_APPLICABLE}
2. JSON and Step Schema integrity:
   - Valid JSON array
   - Exact 7 fields per step: step_no, phase, system_id, resource_id, operation, state, evidence_id
   - 1-based consecutive numbering starting at 1
   - Canonical phase ordering: FINDING -> REMEDIATION -> VERIFICATION
   - Operation canonical rank ordering within phase
   - Allowed (phase, operation, state) combinations
3. Status-specific invariants:
   - NOT_APPLICABLE: strictly empty array []
   - COMPLETE: strictly VERIFICATION steps with non-empty admissible evidence citations
   - INCOMPLETE: strictly 3-phase lifecycle (FINDING -> REMEDIATION -> VERIFICATION) with >= 1 step per phase;
     findings cite valid evidence, remediation and verification have evidence_id == ""
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = REPO_ROOT / "code"

for p in [str(CODE_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from planner.contract import (
    REQUIRED_STEP_FIELDS,
    PERMITTED_PHASES,
    PERMITTED_OPERATIONS,
    PERMITTED_STATES,
    PERMITTED_COMBINATIONS,
    OPERATION_CANONICAL_INDEX,
)
from planner.sequencer import PHASE_CANONICAL_RANK, get_step_sort_key
from planner.models import Step

ALLOWED_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
VALID_EVIDENCE_PREFIXES = ("evidence_", "activity_", "audit_")


@dataclass
class OutputValidationReport:
    output_file: str
    total_rows: int = 0
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=lambda: {
        "COMPLETE": 0, "INCOMPLETE": 0, "NOT_APPLICABLE": 0
    })
    phase_counts: dict[str, int] = field(default_factory=lambda: {
        "FINDING": 0, "REMEDIATION": 0, "VERIFICATION": 0
    })
    total_steps: int = 0
    lifecycle_violations_count: int = 0
    numbering_violations_count: int = 0
    ordering_violations_count: int = 0
    invalid_combinations_count: int = 0
    invalid_evidence_citations_count: int = 0


def validate_output_file(
    output_path: Path,
    input_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> OutputValidationReport:
    rep = OutputValidationReport(output_file=str(output_path))

    if not output_path.exists():
        rep.is_valid = False
        rep.errors.append(f"Output file does not exist: {output_path}")
        return rep

    # Load valid evidence IDs if manifest available
    manifest_ids: set[str] = set()
    man_file = manifest_path or (REPO_ROOT / "dataset" / "evidence_files.csv")
    if man_file.exists():
        with open(man_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                fid = r.get("file_id", "").strip()
                if fid:
                    manifest_ids.add(fid)

    # Load expected case IDs from input requests
    req_file = input_path or (REPO_ROOT / "dataset" / "deletion_requests.csv")
    expected_case_ids: list[str] = []
    if req_file.exists():
        with open(req_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cid = r.get("case_id", "").strip()
                if cid:
                    expected_case_ids.append(cid)
    sorted_expected_case_ids = sorted(expected_case_ids)

    # 1. Inspect CSV Structure
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            rep.is_valid = False
            rep.errors.append("Output file is empty.")
            return rep

        expected_header = ["case_id", "deletion_status", "steps_json"]
        if header != expected_header:
            rep.is_valid = False
            rep.errors.append(f"Header mismatch. Expected {expected_header}, got {header}")

        observed_case_ids: list[str] = []
        rows: list[list[str]] = []
        for line_no, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != 3:
                rep.is_valid = False
                rep.errors.append(f"Line {line_no}: Invalid column count {len(row)} (expected 3).")
                continue
            rows.append(row)
            observed_case_ids.append(row[0])

    rep.total_rows = len(rows)

    # Verify row count and case IDs
    if expected_case_ids:
        if len(rows) != len(expected_case_ids):
            rep.is_valid = False
            rep.errors.append(f"Row count mismatch: expected {len(expected_case_ids)}, got {len(rows)}.")

        if observed_case_ids != sorted_expected_case_ids:
            # Check sorting
            if observed_case_ids != sorted(observed_case_ids):
                rep.is_valid = False
                rep.errors.append("Output rows are not sorted by case_id.")
            
            missing = set(expected_case_ids) - set(observed_case_ids)
            if missing:
                rep.is_valid = False
                rep.errors.append(f"Missing {len(missing)} case IDs, e.g., {sorted(list(missing))[:5]}")

            extra = set(observed_case_ids) - set(expected_case_ids)
            if extra:
                rep.is_valid = False
                rep.errors.append(f"Extra {len(extra)} unexpected case IDs, e.g., {sorted(list(extra))[:5]}")

            duplicates = [cid for cid in observed_case_ids if observed_case_ids.count(cid) > 1]
            if duplicates:
                rep.is_valid = False
                rep.errors.append(f"Duplicate case IDs found: {set(duplicates)}")

    # 2. Inspect Each Case and Steps
    for row_idx, (case_id, status, steps_raw) in enumerate(rows, start=1):
        if status not in ALLOWED_STATUSES:
            rep.is_valid = False
            rep.errors.append(f"Case {case_id}: Invalid status '{status}'. Must be in {ALLOWED_STATUSES}")
            continue

        rep.status_counts[status] = rep.status_counts.get(status, 0) + 1

        # Parse JSON
        try:
            steps_data = json.loads(steps_raw)
        except Exception as e:
            rep.is_valid = False
            rep.errors.append(f"Case {case_id}: JSON parse error: {e}")
            continue

        if not isinstance(steps_data, list):
            rep.is_valid = False
            rep.errors.append(f"Case {case_id}: steps_json is not a JSON array (got {type(steps_data).__name__})")
            continue

        # Status invariant: NOT_APPLICABLE
        if status == "NOT_APPLICABLE":
            if steps_data:
                rep.is_valid = False
                rep.errors.append(f"Case {case_id}: NOT_APPLICABLE must have 0 steps, got {len(steps_data)}")
            continue

        # Status invariant: COMPLETE
        if status == "COMPLETE":
            if not steps_data:
                rep.is_valid = False
                rep.errors.append(f"Case {case_id}: COMPLETE case cannot have empty steps.")
            for s in steps_data:
                if s.get("phase") != "VERIFICATION":
                    rep.is_valid = False
                    rep.errors.append(f"Case {case_id}: COMPLETE step has phase '{s.get('phase')}' (must be VERIFICATION)")
                ev = s.get("evidence_id", "")
                if not ev:
                    rep.is_valid = False
                    rep.invalid_evidence_citations_count += 1
                    rep.errors.append(f"Case {case_id}: COMPLETE verification step {s.get('step_no')} has empty evidence_id.")
                elif manifest_ids and not any(ev.startswith(p) for p in VALID_EVIDENCE_PREFIXES):
                    rep.is_valid = False
                    rep.invalid_evidence_citations_count += 1
                    rep.errors.append(f"Case {case_id}: Invalid evidence format '{ev}'")

        # Status invariant: INCOMPLETE
        if status == "INCOMPLETE":
            if not steps_data:
                rep.is_valid = False
                rep.lifecycle_violations_count += 1
                rep.errors.append(f"Case {case_id}: INCOMPLETE case has 0 steps (expected 3-phase lifecycle)")
                continue

            phases = [s.get("phase") for s in steps_data]
            has_finding = "FINDING" in phases
            has_remediation = "REMEDIATION" in phases
            has_verification = "VERIFICATION" in phases

            if not (has_finding and has_remediation and has_verification):
                rep.is_valid = False
                rep.lifecycle_violations_count += 1
                rep.errors.append(
                    f"Case {case_id}: INCOMPLETE lifecycle incomplete. Phases present: {set(phases)}"
                )

        # Inspect Step Schema & Numbering
        step_objs: list[Step] = []
        for s_idx, s in enumerate(steps_data, start=1):
            rep.total_steps += 1
            if not isinstance(s, dict):
                rep.is_valid = False
                rep.errors.append(f"Case {case_id} step {s_idx} is not an object.")
                continue

            # Check required 7 fields
            missing_fields = set(REQUIRED_STEP_FIELDS) - set(s.keys())
            if missing_fields:
                rep.is_valid = False
                rep.errors.append(f"Case {case_id} step {s_idx} missing required fields: {missing_fields}")

            extra_fields = set(s.keys()) - set(REQUIRED_STEP_FIELDS)
            if extra_fields:
                rep.is_valid = False
                rep.errors.append(f"Case {case_id} step {s_idx} has extra unexpected fields: {extra_fields}")

            s_no = s.get("step_no")
            s_phase = s.get("phase")
            s_sys = s.get("system_id")
            s_res = s.get("resource_id")
            s_op = s.get("operation")
            s_state = s.get("state")
            s_ev = s.get("evidence_id")

            # Consecutive 1-based numbering
            if s_no != s_idx:
                rep.is_valid = False
                rep.numbering_violations_count += 1
                rep.errors.append(f"Case {case_id}: Step numbering error. Expected {s_idx}, got {s_no}")

            # Phase count
            if s_phase in rep.phase_counts:
                rep.phase_counts[s_phase] += 1

            # Allowed combination check
            combo = (s_phase, s_op, s_state)
            if combo not in PERMITTED_COMBINATIONS:
                rep.is_valid = False
                rep.invalid_combinations_count += 1
                rep.errors.append(f"Case {case_id} step {s_no}: Invalid combo {combo}")

            # Evidence ID rules for INCOMPLETE
            if status == "INCOMPLETE":
                if s_phase == "FINDING" and not s_ev:
                    rep.is_valid = False
                    rep.invalid_evidence_citations_count += 1
                    rep.errors.append(f"Case {case_id} finding step {s_no} has empty evidence_id")
                elif s_phase in ("REMEDIATION", "VERIFICATION") and s_ev != "":
                    rep.is_valid = False
                    rep.invalid_evidence_citations_count += 1
                    rep.errors.append(f"Case {case_id} {s_phase} step {s_no} must have empty evidence_id, got '{s_ev}'")

            try:
                step_objs.append(Step(
                    step_no=s_no,
                    phase=s_phase,
                    system_id=s_sys,
                    resource_id=s_res,
                    operation=s_op,
                    state=s_state,
                    evidence_id=s_ev,
                ))
            except Exception:
                pass

        # Check Step Ordering within case
        for i in range(len(step_objs) - 1):
            k1 = get_step_sort_key(step_objs[i])
            k2 = get_step_sort_key(step_objs[i + 1])
            if k1 > k2:
                rep.is_valid = False
                rep.ordering_violations_count += 1
                rep.errors.append(
                    f"Case {case_id}: Step ordering violation between step {step_objs[i].step_no} and {step_objs[i+1].step_no}"
                )

    if rep.errors:
        rep.is_valid = False

    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate output.csv against challenge contract.")
    parser.add_argument("output_path", nargs="?", default=REPO_ROOT / "output.csv", type=Path)
    parser.add_argument("--input", "-i", default=REPO_ROOT / "dataset" / "deletion_requests.csv", type=Path)
    parser.add_argument("--manifest", "-m", default=REPO_ROOT / "dataset" / "evidence_files.csv", type=Path)
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    rep = validate_output_file(
        output_path=args.output_path,
        input_path=args.input,
        manifest_path=args.manifest,
    )

    if args.json:
        payload = {
            "output_file": rep.output_file,
            "total_rows": rep.total_rows,
            "is_valid": rep.is_valid,
            "status_counts": rep.status_counts,
            "phase_counts": rep.phase_counts,
            "total_steps": rep.total_steps,
            "lifecycle_violations": rep.lifecycle_violations_count,
            "numbering_violations": rep.numbering_violations_count,
            "ordering_violations": rep.ordering_violations_count,
            "invalid_combinations": rep.invalid_combinations_count,
            "invalid_evidence_citations": rep.invalid_evidence_citations_count,
            "error_count": len(rep.errors),
            "errors_sample": rep.errors[:10],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("=" * 70)
        print(f"OUTPUT VALIDATION REPORT: {rep.output_file}")
        print("=" * 70)
        print(f"Overall Valid:          {rep.is_valid}")
        print(f"Total Rows:             {rep.total_rows}")
        print(f"Status Distribution:    {rep.status_counts}")
        print(f"Total Steps Generated:  {rep.total_steps}")
        print(f"Steps by Phase:         {rep.phase_counts}")
        print(f"Lifecycle Violations:   {rep.lifecycle_violations_count}")
        print(f"Numbering Violations:   {rep.numbering_violations_count}")
        print(f"Ordering Violations:    {rep.ordering_violations_count}")
        print(f"Invalid Combinations:   {rep.invalid_combinations_count}")
        print(f"Invalid Evidence Cit:   {rep.invalid_evidence_citations_count}")
        print(f"Total Error Count:      {len(rep.errors)}")
        if rep.errors:
            print("\nErrors Sample (first 10):")
            for e in rep.errors[:10]:
                print(f"  [ERROR] {e}")
        print("=" * 70)

    return 0 if rep.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())

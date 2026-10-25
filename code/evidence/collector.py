"""Safe evidence manifest inventory and path validation."""

import csv
from datetime import datetime
from pathlib import Path


REQUIRED_COLUMNS = {"file_id", "file_path", "origin", "captured_at"}


def parse_timestamp(value):
    """Parse an ISO 8601 timestamp, including UTC Z suffix."""
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def build_inventory(manifest_path, evidence_root):
    """
    Read the evidence manifest and validate each path.

    Returns:
        A dictionary containing inventory entries and validation errors.
    """
    manifest_path = Path(manifest_path).resolve()
    evidence_root = Path(evidence_root).resolve()

    result = {
        "entries": [],
        "errors": [],
        "manifest_rows": 0,
    }

    try:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)

            if not reader.fieldnames:
                result["errors"].append("Manifest is empty or has no header.")
                return result

            missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
            if missing_columns:
                result["errors"].append(
                    "Missing required columns: "
                    + ", ".join(sorted(missing_columns))
                )
                return result

            seen_ids = set()

            for line_number, row in enumerate(reader, start=2):
                result["manifest_rows"] += 1
                errors = []

                file_id = (row.get("file_id") or "").strip()
                relative_path = (row.get("file_path") or "").strip()
                origin = (row.get("origin") or "").strip()
                captured_at_raw = (row.get("captured_at") or "").strip()
                captured_at = parse_timestamp(captured_at_raw)

                if not file_id:
                    errors.append("Missing file_id")
                elif file_id in seen_ids:
                    errors.append("Duplicate file_id")
                else:
                    seen_ids.add(file_id)

                if not relative_path:
                    errors.append("Missing file_path")
                    resolved_path = None
                else:
                    candidate = Path(relative_path)

                    if candidate.is_absolute():
                        errors.append("Absolute paths are not allowed")
                        resolved_path = None
                    else:
                        resolved_path = (manifest_path.parent / candidate).resolve()

                        try:
                            resolved_path.relative_to(evidence_root)
                        except ValueError:
                            errors.append("Path escapes evidence directory")
                            resolved_path = None

                if not origin:
                    errors.append("Missing origin")

                if not captured_at_raw:
                    errors.append("Missing captured_at")
                elif captured_at is None:
                    errors.append("Invalid captured_at timestamp")

                if resolved_path is not None:
                    if not resolved_path.is_file():
                        errors.append("Evidence file does not exist")
                    elif not resolved_path.exists():
                        errors.append("Evidence path does not exist")

                result["entries"].append(
                    {
                        "line_number": line_number,
                        "file_id": file_id,
                        "file_path": relative_path,
                        "origin": origin,
                        "captured_at": captured_at,
                        "resolved_path": (
                            str(resolved_path)
                            if resolved_path is not None
                            else None
                        ),
                        "valid": not errors,
                        "errors": errors,
                    }
                )

    except OSError as exc:
        result["errors"].append(
            f"Unable to read manifest: {exc}"
        )

    return result


def print_inventory_summary(result):
    """Print a concise inventory audit summary."""
    entries = result["entries"]
    valid_count = sum(entry["valid"] for entry in entries)
    invalid_count = len(entries) - valid_count

    print(f"Manifest rows: {result['manifest_rows']}")
    print(f"Valid entries: {valid_count}")
    print(f"Invalid entries: {invalid_count}")
    print(f"Manifest-level errors: {len(result['errors'])}")

    for error in result["errors"]:
        print(f"MANIFEST ERROR: {error}")

    for entry in entries:
        if entry["errors"]:
            print(
                f"Line {entry['line_number']} "
                f"[{entry['file_id'] or 'NO_ID'}]: "
                + "; ".join(entry["errors"])
            )


if __name__ == "__main__":
    repository_root = Path(__file__).resolve().parents[2]
    manifest = repository_root / "dataset" / "evidence_files.csv"
    evidence_directory = repository_root / "dataset" / "evidence"

    inventory = build_inventory(manifest, evidence_directory)
    print_inventory_summary(inventory)

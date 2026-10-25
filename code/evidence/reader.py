
import json
import re
import sqlite3
from pathlib import Path

from pypdf import PdfReader
from PIL import Image
import pytesseract
from sql_parser import extract_schemas, parse_insert_statement

TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b"
)

KV_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*)=(?:"([^"]*)"|(\S+))'
)

IDENTIFIER_KEYS = {
    "email",
    "owner_email",
    "phone",
    "email_hash",
    "user_id",
    "customer_reference",
    "subject_reference",
    "match_key",
    "subject_key",
    "matched_value",
}


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def flatten_json(value, prefix=""):
    """Return searchable scalar fields while preserving their JSON paths."""
    fields = []

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else key
            fields.extend(flatten_json(child, child_path))

    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.extend(flatten_json(child, f"{prefix}[{index}]"))

    elif value is not None:
        fields.append({
            "field": prefix,
            "value": str(value),
        })

    return fields



def parse_log_line(line):
    """Parse key-value logs and bracketed application trace logs."""
    timestamp_match = TIMESTAMP_RE.search(line)
    fields = {}

    # Check for embedded JSON payload (e.g. structured JSON service events)
    json_start = line.find("{")
    if json_start != -1 and line.rfind("}") > json_start:
        try:
            json_payload = json.loads(line[json_start : line.rfind("}") + 1])
            if isinstance(json_payload, dict):
                fields.update(json_payload)
        except Exception:
            pass

    for match in KV_RE.finditer(line):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        fields.setdefault(key, value)

    # Parse bracketed format:
    # timestamp [LEVEL] [service] [trace_id] event_name: key="value"
    bracketed = re.match(
        r'^\s*(?P<timestamp>\S+)'
        r'\s+\[(?P<level>[A-Z]+)\]'
        r'\s+\[(?P<service>[^\]]+)\]'
        r'\s+\[(?P<trace_id>[^\]]+)\]'
        r'\s+(?P<event>[A-Za-z0-9_.-]+):',
        line,
    )

    if bracketed:
        fields.setdefault("level", bracketed.group("level"))
        fields.setdefault("service", bracketed.group("service"))

        bracket_id = bracketed.group("trace_id")
        if bracket_id.startswith("tr-"):
            fields.setdefault("trace_id", bracket_id)
        else:
            fields.setdefault("bracket_id", bracket_id)

        fields.setdefault("event", bracketed.group("event"))

    return {
        "event_timestamp": timestamp_match.group(0) if timestamp_match else None,
        "fields": fields,
        "resource_id": fields.get("resource_id"),
        "raw_text": line.rstrip("\n"),
    }




def read_sql_static(path):
    """
    Read SQL evidence without executing it.

    Extract schemas and parse supported INSERT statements while
    preserving original statement text and reporting parse failures.
    """
    text = read_text(path)
    statements = []

    statement_pattern = re.compile(
        r"(?im)^\s*(CREATE TABLE|INSERT INTO|UPDATE|DELETE FROM|"
        r"DROP TABLE|CREATE INDEX|COMMIT|ROLLBACK|BEGIN TRANSACTION)\b"
    )

    matches = list(statement_pattern.finditer(text))

    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        statement = text[match.start():end].strip()

        statements.append({
            "statement_type": match.group(1).upper(),
            "raw_statement": statement,
        })

    # Parse table schemas from the complete SQL text. No SQL is executed.
    schemas, schema_errors = extract_schemas(text)

    for error in schema_errors:
        statements.append({
            "statement_type": "SCHEMA_PARSE_ERROR",
            "raw_statement": "",
            "parse_error": error.get("error", "Unknown schema error"),
            "table": error.get("table"),
        })

    parsed_statements = []

    for statement in statements:
        statement_type = statement["statement_type"]

        if statement_type != "INSERT INTO":
            parsed_statements.append(statement)
            continue

        parsed = parse_insert_statement(
            statement["raw_statement"],
            schemas,
        )

        # Always retain source statement context, even on parse failure.
        parsed["statement_type"] = statement_type
        parsed["raw_statement"] = statement["raw_statement"]
        parsed["source_path"] = str(path)

        if not parsed.get("ok"):
            parsed_statements.append({
                **statement,
                "parse_ok": False,
                "parse_error": parsed.get(
                    "error",
                    "Unknown INSERT parsing error",
                ),
                "table": parsed.get("table"),
            })
            continue

        parsed["parse_ok"] = True
        parsed_statements.append(parsed)

    return text, parsed_statements



def read_evidence_file(path):
    """
    Extract content from one supported evidence file.
    Returns structured records with source-local context.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    result = {
        "path": str(path),
        "format": suffix.lstrip("."),
        "extraction_method": None,
        "records": [],
        "errors": [],
    }

    try:
        if suffix == ".json":
            result["extraction_method"] = "json"
            data = json.loads(read_text(path))

            if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
                for snapshot_index, snapshot in enumerate(data["snapshots"]):
                    records = snapshot.get("records", [])

                    for record_index, record in enumerate(records):
                        result["records"].append({
                            "record_type": "json_record",
                            "snapshot_index": snapshot_index,
                            "record_index": record_index,
                            "snapshot_captured_at": snapshot.get("captured_at"),
                            "data_store": snapshot.get("data_store"),
                            "collection": snapshot.get("collection"),
                            "resource_id": record.get("resource_id"),
                            "fields": flatten_json(record),
                            "raw_record": record,
                        })
            else:
                result["records"].append({
                    "record_type": "json_document",
                    "fields": flatten_json(data),
                    "raw_record": data,
                })

        elif suffix == ".log":
            result["extraction_method"] = "log_key_value"
            for line_number, line in enumerate(read_text(path).splitlines(), start=1):
                if line.strip():
                    result["records"].append({
                        "record_type": "log_line",
                        "line_number": line_number,
                        **parse_log_line(line),
                    })

        
        elif suffix == ".sql":
            result["extraction_method"] = "sql_static"
            text, statements = read_sql_static(path)
            result["records"] = statements

            for statement in statements:
                statement_type = statement.get("statement_type")

                if statement_type == "SCHEMA_PARSE_ERROR":
                    result["errors"].append(
                        "SQL schema parse error: "
                        + statement.get("parse_error", "Unknown error")
                    )

                elif (
                    statement_type == "INSERT INTO"
                    and not statement.get("parse_ok", False)
                ):
                    result["errors"].append(
                        "SQL INSERT parse error: "
                        + statement.get("parse_error", "Unknown error")
                    )

            if not statements and text.strip():
                result["errors"].append(
                    "No recognized SQL statements found"
                )

        elif suffix == ".txt":
            result["extraction_method"] = "text_lines"
            for line_number, line in enumerate(read_text(path).splitlines(), start=1):
                if line.strip():
                    result["records"].append({
                        "record_type": "text_line",
                        "line_number": line_number,
                        "raw_text": line,
                        "timestamp_candidates": TIMESTAMP_RE.findall(line),
                    })

        elif suffix == ".pdf":
            result["extraction_method"] = "pdf_text"
            pdf = PdfReader(str(path))

            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                result["records"].append({
                    "record_type": "pdf_page",
                    "page_number": page_number,
                    "raw_text": text,
                    "timestamp_candidates": TIMESTAMP_RE.findall(text),
                })

                if not text.strip():
                    result["errors"].append(
                        f"Page {page_number} has no extractable text; OCR may be required"
                    )

        elif suffix == ".png":
            result["extraction_method"] = "image_ocr"
            with Image.open(path) as image:
                data = pytesseract.image_to_data(
                    image,
                    config="--psm 6",
                    output_type=pytesseract.Output.DICT,
                )

            words = []
            for index, word in enumerate(data["text"]):
                word = word.strip()

                try:
                    confidence = float(data["conf"][index])
                except (TypeError, ValueError):
                    continue

                if word and confidence >= 0:
                    words.append({
                        "text": word,
                        "confidence": confidence,
                    })

            raw_text = pytesseract.image_to_string(
                Image.open(path),
                config="--psm 6",
            )

            result["records"].append({
                "record_type": "image_ocr",
                "raw_text": raw_text,
                "words": words,
                "average_confidence": (
                    round(sum(word["confidence"] for word in words) / len(words), 2)
                    if words else None
                ),
                "timestamp_candidates": TIMESTAMP_RE.findall(raw_text),
            })

        else:
            result["errors"].append(f"Unsupported file extension: {suffix}")

    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")

    except Exception as exc:
        result["errors"].append(f"Extraction error: {type(exc).__name__}: {exc}")

    return result


def extract_identifiers(record):
    """Return identifier-like fields without asserting identity."""
    identifiers = []
    fields = record.get("fields", [])

    # JSON records store fields as a list of dictionaries.
    if isinstance(fields, list):
        for item in fields:
            if not isinstance(item, dict):
                continue

            field_name = str(item.get("field", ""))
            value = item.get("value")
            key = field_name.split(".")[-1].lower()

            if key in IDENTIFIER_KEYS and value is not None:
                identifiers.append({
                    "field": field_name,
                    "value": str(value),
                })

    # Log records store fields as a dictionary.
    elif isinstance(fields, dict):
        for field_name, value in fields.items():
            key = str(field_name).split(".")[-1].lower()

            if key in IDENTIFIER_KEYS and value is not None:
                identifiers.append({
                    "field": str(field_name),
                    "value": str(value),
                })

    return identifiers

def main():
    """Run evidence extraction against every file in the manifest."""
    import csv
    from pathlib import Path

    repository_root = Path(__file__).resolve().parents[2]
    manifest_path = repository_root / "dataset" / "evidence_files.csv"
    evidence_root = repository_root / "dataset" / "evidence"

    total_files = 0
    total_records = 0
    files_with_errors = 0
    identifier_records = 0
    format_counts = {}

    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        manifest = csv.DictReader(handle)

        for entry in manifest:
            file_path = (manifest_path.parent / entry["file_path"]).resolve()
            total_files += 1

            result = read_evidence_file(file_path)
            total_records += len(result["records"])

            file_format = result["format"]
            format_counts[file_format] = format_counts.get(file_format, 0) + 1

            if result["errors"]:
                files_with_errors += 1
                for error in result["errors"]:
                    print(f"ERROR [{entry['file_id']}]: {error}")

            for record in result["records"]:
                if extract_identifiers(record):
                    identifier_records += 1

    print(f"Total files processed: {total_files}")
    print(f"Files by format: {format_counts}")
    print(f"Total extracted records: {total_records}")
    print(f"Records with identifier-like fields: {identifier_records}")
    print(f"Files with extraction errors: {files_with_errors}")

    if total_files != 94:
        print("RESULT: REVIEW - expected 94 evidence files")
    elif files_with_errors:
        print("RESULT: REVIEW - extraction errors need investigation")
    else:
        print("RESULT: PASS - all manifest files processed without extraction errors")


if __name__ == "__main__":
    main()



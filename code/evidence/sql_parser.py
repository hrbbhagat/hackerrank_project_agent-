
"""Safely parse supported SQL INSERT statements without executing SQL."""

import json
import re


CREATE_TABLE_RE = re.compile(
    r'\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'(?P<table>"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w.]*)\s*\(',
    re.IGNORECASE,
)

INSERT_RE = re.compile(
    r'^\s*INSERT\s+INTO\s+'
    r'(?P<table>"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w.]*)'
    r'\s+VALUES\s*\(',
    re.IGNORECASE | re.DOTALL,
)

IDENTIFIER_KEYS = {
    "email",
    "owner_email",
    "customer_email",
    "requester_email",
    "phone",
    "requester_phone",
    "owner_phone",
    "customer_phone",
    "email_hash",
    "user_id",
    "customer_reference",
    "subject_reference",
    "match_key",
    "subject_key",
    "matched_value",
    "source_resource_id",
}


def _unquote_identifier(value):
    """Remove supported SQL identifier quoting."""
    value = value.strip()

    if len(value) >= 2:
        if (value[0], value[-1]) in {
            ('"', '"'),
            ("`", "`"),
            ("[", "]"),
        }:
            value = value[1:-1]

    return value


def _extract_parenthesized(text, opening_index):
    """Extract balanced parenthesized content, respecting SQL strings."""
    if opening_index >= len(text) or text[opening_index] != "(":
        raise ValueError("Expected opening parenthesis")

    depth = 0
    in_string = False
    i = opening_index

    while i < len(text):
        char = text[i]

        if char == "'":
            if in_string and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue

            in_string = not in_string

        elif not in_string:
            if char == "(":
                depth += 1

            elif char == ")":
                depth -= 1

                if depth == 0:
                    return text[opening_index + 1:i], i + 1

        i += 1

    raise ValueError("Unterminated parenthesized SQL expression")


def split_sql_definition_list(text):
    """Split SQL definitions on top-level commas."""
    result = []
    start = 0
    depth = 0
    in_string = False
    i = 0

    while i < len(text):
        char = text[i]

        if char == "'":
            if in_string and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue

            in_string = not in_string

        elif not in_string:
            if char == "(":
                depth += 1

            elif char == ")":
                depth -= 1

            elif char == "," and depth == 0:
                result.append(text[start:i].strip())
                start = i + 1

        i += 1

    result.append(text[start:].strip())
    return result


def split_sql_values(value_text):
    """Split VALUES at commas outside strings and nested parentheses."""
    values = []
    start = 0
    depth = 0
    in_string = False
    i = 0

    while i < len(value_text):
        char = value_text[i]

        if char == "'":
            if in_string and i + 1 < len(value_text) and value_text[i + 1] == "'":
                i += 2
                continue

            in_string = not in_string

        elif not in_string:
            if char == "(":
                depth += 1

            elif char == ")":
                if depth == 0:
                    values.append(value_text[start:i].strip())
                    return values, i + 1

                depth -= 1

            elif char == "," and depth == 0:
                values.append(value_text[start:i].strip())
                start = i + 1

        i += 1

    raise ValueError("Unterminated SQL VALUES list")


def decode_sql_value(token):
    """Decode basic SQL literals without evaluating SQL."""
    token = token.strip()

    if token.upper() == "NULL":
        return None

    if len(token) >= 2 and token[0] == "'" and token[-1] == "'":
        return token[1:-1].replace("''", "'")

    if token.upper() == "TRUE":
        return True

    if token.upper() == "FALSE":
        return False

    return token


def parse_create_table(statement):
    """Extract the table name and declared column names."""
    match = CREATE_TABLE_RE.search(statement)

    if not match:
        return None

    table = _unquote_identifier(match.group("table"))

    try:
        body, _ = _extract_parenthesized(statement, match.end() - 1)
    except ValueError as exc:
        return {
            "ok": False,
            "table": table,
            "error": str(exc),
        }

    columns = []

    for definition in split_sql_definition_list(body):
        item = definition.strip()

        if not item:
            continue

        # Ignore table-level constraints.
        if re.match(
            r"^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT|KEY)\b",
            item,
            re.IGNORECASE,
        ):
            continue

        column_match = re.match(
            r'^(?:"([^"]+)"|`([^`]+)`|\[([^\]]+)\]|([A-Za-z_]\w*))\s+',
            item,
        )

        if column_match:
            column_name = next(
                group
                for group in column_match.groups()
                if group is not None
            )
            columns.append(column_name)

    if not columns:
        return {
            "ok": False,
            "table": table,
            "error": "No supported columns found",
        }

    return {
        "ok": True,
        "table": table,
        "columns": columns,
    }


def extract_schemas(sql_text):
    """Extract table schemas from all CREATE TABLE statements in a file."""
    schemas = {}
    errors = []

    for match in CREATE_TABLE_RE.finditer(sql_text):
        result = parse_create_table(sql_text[match.start():])

        if result is None:
            continue

        if not result.get("ok"):
            errors.append(result)
            continue

        table = result["table"]

        if table in schemas and schemas[table] != result["columns"]:
            errors.append({
                "table": table,
                "error": "Conflicting table definitions",
            })
            continue

        schemas[table] = result["columns"]

    return schemas, errors


def flatten_json(value, prefix=""):
    """Flatten nested JSON into field/value pairs."""
    flattened = []

    if isinstance(value, dict):
        for key, item in value.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            flattened.extend(flatten_json(item, field))

    elif isinstance(value, list):
        for index, item in enumerate(value):
            field = f"{prefix}[{index}]"
            flattened.extend(flatten_json(item, field))

    elif value is not None:
        flattened.append({
            "field": prefix,
            "value": str(value),
        })

    return flattened


def extract_identifiers(fields):
    """Extract explicit identifier fields without inferring identity."""
    identifiers = []

    for item in fields:
        key = item["field"].split(".")[-1].split("[")[0].lower()

        if key in IDENTIFIER_KEYS:
            identifiers.append({
                "field": item["field"],
                "value": item["value"],
            })

    return identifiers


def parse_insert_statement(statement, schemas=None):
    """
    Parse an INSERT using its declared table column order.

    If schemas are not supplied, the legacy five-column JSON format
    is supported as a backward-compatible fallback.

    SQL statements are parsed as text and are never executed.
    """
    match = INSERT_RE.match(statement)

    if not match:
        return {
            "ok": False,
            "error": "Unsupported INSERT statement format",
            "raw_statement": statement,
        }

    table = _unquote_identifier(match.group("table"))
    values_text = statement[match.end():]

    try:
        tokens, consumed = split_sql_values(values_text)
        values = [decode_sql_value(token) for token in tokens]

    except ValueError as exc:
        return {
            "ok": False,
            "table": table,
            "error": str(exc),
            "raw_statement": statement,
        }

    columns = None

    if schemas is not None:
        columns = schemas.get(table)

        # A supplied schema collection is authoritative.
        if columns is None:
            return {
                "ok": False,
                "table": table,
                "error": "No CREATE TABLE schema found for this table",
                "raw_statement": statement,
            }

    if columns is not None and len(values) != len(columns):
        return {
            "ok": False,
            "table": table,
            "error": (
                f"Schema has {len(columns)} columns but INSERT has "
                f"{len(values)} values"
            ),
            "raw_statement": statement,
        }

    if columns is None:
        if len(values) != 5:
            return {
                "ok": False,
                "table": table,
                "error": (
                    "No schema supplied and legacy format expects 5 "
                    f"values, found {len(values)}"
                ),
                "raw_statement": statement,
            }

        columns = [
            "resource_id",
            "origin_system",
            "collection_name",
            "record_json",
            "updated_at",
        ]

    row = dict(zip(columns, values))
    fields = []
    parsed_json = None
    warnings = []

    for column, value in row.items():
        if value is None:
            continue

        if column.lower() in {
            "record_json",
            "data_json",
            "payload_json",
        }:
            if not isinstance(value, str):
                warnings.append(f"JSON column {column} is not a string")
                fields.append({
                    "field": column,
                    "value": str(value),
                })
                continue

            try:
                parsed_json = json.loads(value)
                fields.extend(flatten_json(parsed_json))

            except json.JSONDecodeError as exc:
                warnings.append(
                    f"Invalid JSON in column {column}: {exc.msg}"
                )
                fields.append({
                    "field": column,
                    "value": value,
                })

        else:
            fields.append({
                "field": column,
                "value": str(value),
            })

    return {
        "ok": True,
        "record_type": "sql_insert_record",
        "table": table,
        "columns": columns,
        "values": row,
        "resource_id": row.get("resource_id"),
        "updated_at": row.get(
            "updated_at",
            row.get("indexed_at", row.get("captured_at")),
        ),
        "record_json": parsed_json,
        "fields": fields,
        "identifiers": extract_identifiers(fields),
        "raw_statement": statement,
        "consumed_characters": consumed,
        "warnings": warnings,
    }


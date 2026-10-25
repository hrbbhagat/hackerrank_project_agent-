"""Phase 6.2: Policy Rule Loader, Schema Validation, and Deterministic Lookup.

Parses dataset/deletion_rules.csv, enforces schema constraints, validates
treatment actions, surfaces conflicting or duplicate rules, and indexes
rules deterministically by category and rule_id.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union
import io

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
DEFAULT_RULES_PATH = ROOT_DIR / "dataset" / "deletion_rules.csv"

REQUIRED_COLUMNS = ["rule_id", "data_category", "condition", "required_action"]

SUPPORTED_ACTIONS = {
    "DELETE",
    "REDACT",
    "ANONYMIZE",
    "RETAIN",
}

KNOWN_CATEGORIES = {
    "USER_PROFILE",
    "SECONDARY_IDENTIFIER",
    "SEARCH_INDEX_ENTRY",
    "CACHE_ENTRY",
    "SUPPORT_MESSAGE",
    "SUPPORT_ATTACHMENT",
    "ANALYTICS_PROFILE",
    "PRODUCT_TELEMETRY",
    "USER_EXPORT",
    "MARKETING_PROFILE",
    "EMAIL_DELIVERY_LOG",
    "SECURITY_AUDIT_LOG",
    "LEGAL_HOLD_RECORD",
    "BACKUP_ARCHIVE",
    "ACCOUNT_TOMBSTONE",
}


@dataclass(frozen=True)
class PolicyRule:
    """Immutable representation of an ingested deletion rule."""
    rule_id: str
    data_category: str
    condition: str
    required_action: str
    source_row: int


@dataclass
class PolicyValidationResult:
    """Detailed result of policy schema validation and loading."""
    is_valid: bool
    rules: list[PolicyRule] = field(default_factory=list)
    rules_by_category: dict[str, list[PolicyRule]] = field(default_factory=dict)
    rules_by_id: dict[str, PolicyRule] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


class PolicyLoader:
    """
    Robust loader and validator for dataset/deletion_rules.csv.
    
    Provides deterministic indexing, error isolation, and contextual lookup.
    """

    def __init__(self, rules_source: Optional[Union[Path, str, io.StringIO]] = None):
        if rules_source is None:
            self.rules_path = DEFAULT_RULES_PATH
            self._raw_source = None
        elif isinstance(rules_source, io.StringIO):
            self.rules_path = None
            self._raw_source = rules_source
        elif isinstance(rules_source, (str, Path)):
            # If string contains newlines, treat it as in-memory CSV content
            if isinstance(rules_source, str) and ("\n" in rules_source or "\r" in rules_source):
                self.rules_path = None
                self._raw_source = io.StringIO(rules_source)
            else:
                self.rules_path = Path(rules_source).resolve()
                self._raw_source = None
        else:
            self.rules_path = None
            self._raw_source = rules_source

        self._cached_result: Optional[PolicyValidationResult] = None

    def load(self, force_reload: bool = False) -> PolicyValidationResult:
        """Load and validate the policy rules, returning PolicyValidationResult."""
        if self._cached_result is not None and not force_reload:
            return self._cached_result

        errors: list[dict] = []
        warnings: list[dict] = []
        rules: list[PolicyRule] = []
        rules_by_category: dict[str, list[PolicyRule]] = {}
        rules_by_id: dict[str, PolicyRule] = {}

        # 1. Source existence and readability
        if self.rules_path is not None:
            if not self.rules_path.is_file():
                errors.append({
                    "error_type": "FILE_NOT_FOUND",
                    "path": str(self.rules_path),
                    "message": f"Policy rules file not found: {self.rules_path}",
                })
                result = PolicyValidationResult(is_valid=False, errors=errors)
                self._cached_result = result
                return result
            try:
                handle = open(self.rules_path, "r", encoding="utf-8-sig", newline="")
                close_handle = True
            except Exception as exc:
                errors.append({
                    "error_type": "FILE_READ_ERROR",
                    "path": str(self.rules_path),
                    "message": f"Failed to open policy rules file: {exc}",
                })
                result = PolicyValidationResult(is_valid=False, errors=errors)
                self._cached_result = result
                return result
        else:
            handle = self._raw_source
            close_handle = False

        try:
            content = handle.read()
            if close_handle:
                handle.close()
        except Exception as exc:
            errors.append({
                "error_type": "FILE_READ_ERROR",
                "message": f"Error reading content: {exc}",
            })
            result = PolicyValidationResult(is_valid=False, errors=errors)
            self._cached_result = result
            return result

        if not content.strip():
            errors.append({
                "error_type": "EMPTY_FILE",
                "message": "Policy rules file is empty.",
            })
            result = PolicyValidationResult(is_valid=False, errors=errors)
            self._cached_result = result
            return result

        # 2. Header and column validation
        lines = content.splitlines()
        first_line = lines[0] if lines else ""
        raw_header = [col.strip() for col in first_line.split(",")]

        # Check duplicate column names in header
        seen_cols = set()
        for col in raw_header:
            if col in seen_cols:
                errors.append({
                    "error_type": "DUPLICATE_COLUMN",
                    "column": col,
                    "message": f"Duplicate column '{col}' in policy header.",
                })
            seen_cols.add(col)

        # Check required columns
        missing_cols = [c for c in REQUIRED_COLUMNS if c not in seen_cols]
        if missing_cols:
            errors.append({
                "error_type": "MISSING_COLUMN",
                "missing_columns": missing_cols,
                "message": f"Missing required columns in policy header: {missing_cols}",
            })
            result = PolicyValidationResult(is_valid=False, errors=errors)
            self._cached_result = result
            return result

        # 3. Parse data rows
        reader = csv.DictReader(io.StringIO(content))
        seen_rule_ids = set()
        seen_rule_tuples = set()  # (category, condition, action)
        category_condition_action_map = {}  # (category, condition) -> (action, rule_id)

        for row_idx, row in enumerate(reader, start=2):
            rule_id = (row.get("rule_id") or "").strip()
            category = (row.get("data_category") or "").strip()
            condition = (row.get("condition") or "").strip()
            action = (row.get("required_action") or "").strip().upper()

            # Check missing mandatory fields
            missing_fields = []
            if not rule_id:
                missing_fields.append("rule_id")
            if not category:
                missing_fields.append("data_category")
            if not condition:
                missing_fields.append("condition")
            if not action:
                missing_fields.append("required_action")

            if missing_fields:
                errors.append({
                    "error_type": "MISSING_FIELD",
                    "row": row_idx,
                    "rule_id": rule_id or f"row_{row_idx}",
                    "missing_fields": missing_fields,
                    "message": f"Row {row_idx} is missing mandatory fields: {missing_fields}",
                })
                continue

            # Check supported required_action
            if action not in SUPPORTED_ACTIONS:
                errors.append({
                    "error_type": "INVALID_TREATMENT",
                    "row": row_idx,
                    "rule_id": rule_id,
                    "required_action": action,
                    "message": (
                        f"Row {row_idx} ({rule_id}) has invalid required_action '{action}'. "
                        f"Expected one of {sorted(SUPPORTED_ACTIONS)}."
                    ),
                })

            # Check category recognition
            if category not in KNOWN_CATEGORIES:
                warnings.append({
                    "warning_type": "UNKNOWN_CATEGORY",
                    "row": row_idx,
                    "rule_id": rule_id,
                    "data_category": category,
                    "message": f"Row {row_idx} ({rule_id}) has unrecognized category '{category}'.",
                })

            # Check duplicate rule_id
            if rule_id in seen_rule_ids:
                errors.append({
                    "error_type": "DUPLICATE_RULE_ID",
                    "row": row_idx,
                    "rule_id": rule_id,
                    "message": f"Duplicate rule_id '{rule_id}' at row {row_idx}.",
                })
            seen_rule_ids.add(rule_id)

            # Check exact duplicate rule content
            rule_tuple = (category, condition, action)
            if rule_tuple in seen_rule_tuples:
                warnings.append({
                    "warning_type": "DUPLICATE_RULE_CONTENT",
                    "row": row_idx,
                    "rule_id": rule_id,
                    "category": category,
                    "message": f"Row {row_idx} ({rule_id}) has identical category, condition, and action to an earlier rule.",
                })
            seen_rule_tuples.add(rule_tuple)

            # Check contradictory rules: same category & condition, but conflicting action
            cat_cond_key = (category, condition)
            if cat_cond_key in category_condition_action_map:
                prev_action, prev_rule_id = category_condition_action_map[cat_cond_key]
                if prev_action != action:
                    errors.append({
                        "error_type": "CONFLICTING_RULE",
                        "row": row_idx,
                        "rule_id": rule_id,
                        "conflicting_with": prev_rule_id,
                        "category": category,
                        "condition": condition,
                        "message": (
                            f"Rule '{rule_id}' at row {row_idx} specifies '{action}' for "
                            f"({category}, {condition}), conflicting with rule '{prev_rule_id}' "
                            f"which specifies '{prev_action}'."
                        ),
                    })
            else:
                category_condition_action_map[cat_cond_key] = (action, rule_id)

            rule = PolicyRule(
                rule_id=rule_id,
                data_category=category,
                condition=condition,
                required_action=action,
                source_row=row_idx,
            )
            rules.append(rule)
            rules_by_category.setdefault(category, []).append(rule)
            rules_by_id[rule_id] = rule

        # Deterministic sorting
        rules.sort(key=lambda r: (r.data_category, r.rule_id))
        for cat in rules_by_category:
            rules_by_category[cat].sort(key=lambda r: r.rule_id)

        is_valid = len(errors) == 0
        self._cached_result = PolicyValidationResult(
            is_valid=is_valid,
            rules=rules,
            rules_by_category=rules_by_category,
            rules_by_id=rules_by_id,
            errors=errors,
            warnings=warnings,
        )
        return self._cached_result

    def get_rules_for_category(self, category: str) -> list[PolicyRule]:
        """Return all matching rules for a data category, preserving deterministic order."""
        res = self.load()
        return res.rules_by_category.get(category.strip().upper(), [])

    def get_rule_by_id(self, rule_id: str) -> Optional[PolicyRule]:
        """Return a single rule by its unique rule_id."""
        res = self.load()
        return res.rules_by_id.get(rule_id.strip())

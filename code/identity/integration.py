"""Phase 3B: Identity Resolution and Evidence Integration.

Connects the Phase 3A IdentityResolver with the Phase 4 Evidence Collector
to perform grounded, temporally-admissible evidence correlation.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
EVIDENCE_DIR = CURRENT_DIR.parent / "evidence"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(EVIDENCE_DIR) not in sys.path:
    sys.path.insert(0, str(EVIDENCE_DIR))

from resolver import IdentityResolver, parse_timestamp, normalize
from collector import build_inventory
from reader import read_evidence_file, extract_identifiers


def make_word_boundary_regex(token: str) -> re.Pattern:
    """Create a regex pattern matching token on word/boundary limits."""
    escaped = re.escape(token.strip())
    return re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)


class EvidenceIntegrator:
    """
    Integrates identity resolution with evidence collection.
    
    Loads and caches parsed evidence files, searches for verified subject
    identifiers, enforces temporal admissibility (<= audit_at), and prevents
    cross-talk or decoy attribution.
    """

    def __init__(self, manifest_path=None, evidence_root=None):
        if manifest_path is None:
            manifest_path = ROOT_DIR / "dataset" / "evidence_files.csv"
        if evidence_root is None:
            evidence_root = ROOT_DIR / "dataset" / "evidence"

        self.manifest_path = Path(manifest_path).resolve()
        self.evidence_root = Path(evidence_root).resolve()
        
        inventory_result = build_inventory(self.manifest_path, self.evidence_root)
        self.inventory_entries = inventory_result.get("entries", [])
        self.inventory_errors = inventory_result.get("errors", [])
        
        # Cache for parsed evidence files: file_id -> parsed dict
        self._parsed_cache = {}

    def get_parsed_file(self, file_id: str, resolved_path: str) -> dict:
        """Retrieve or parse an evidence file from cache."""
        if file_id not in self._parsed_cache:
            parsed = read_evidence_file(resolved_path)
            self._parsed_cache[file_id] = parsed
        return self._parsed_cache[file_id]

    def preload_all(self):
        """Preload all valid manifest files into memory for high performance."""
        for entry in self.inventory_entries:
            if entry["valid"] and entry["resolved_path"]:
                self.get_parsed_file(entry["file_id"], entry["resolved_path"])

    def correlate_for_request(
        self,
        request: dict,
        resolver: IdentityResolver,
    ) -> dict:
        """
        Execute full Phase 3B integration for a single deletion request.

        Args:
            request: Dict containing case_id, email, audit_at, etc.
            resolver: Instantiated IdentityResolver.

        Returns:
            Structured dictionary with resolution, admissible matches,
            excluded matches (post-cutoff), and provenance explanations.
        """
        case_id = str(request.get("case_id", "")).strip()
        email = str(request.get("email", "")).strip()
        audit_at_raw = str(request.get("audit_at", "")).strip()
        
        if not audit_at_raw:
            return {
                "case_id": case_id,
                "email": email,
                "audit_at": None,
                "resolution": {"status": "UNRESOLVED", "user_id": None},
                "admissible_matches": [],
                "excluded_matches": [],
                "unattributed_candidates": [],
                "errors": ["Missing audit_at timestamp in request"],
                "summary": {"total_matches": 0, "admissible": 0, "excluded": 0},
            }

        try:
            audit_cutoff = parse_timestamp(audit_at_raw)
        except (ValueError, TypeError) as exc:
            return {
                "case_id": case_id,
                "email": email,
                "audit_at": audit_at_raw,
                "resolution": {"status": "UNRESOLVED", "user_id": None},
                "admissible_matches": [],
                "excluded_matches": [],
                "unattributed_candidates": [],
                "errors": [f"Invalid audit_at timestamp: {exc}"],
                "summary": {"total_matches": 0, "admissible": 0, "excluded": 0},
            }

        # Step 1: Resolve identity at the audit cutoff
        res_info = resolver.resolve_email(email, audit_at_raw)
        resolution_status = res_info.get("status", "UNRESOLVED")
        user_id = res_info.get("user_id")

        if resolution_status != "RESOLVED" or not user_id:
            return {
                "case_id": case_id,
                "email": email,
                "audit_at": audit_at_raw,
                "resolution": res_info,
                "admissible_matches": [],
                "excluded_matches": [],
                "unattributed_candidates": [],
                "errors": [f"Identity is {resolution_status} for {email}"],
                "summary": {"total_matches": 0, "admissible": 0, "excluded": 0},
            }

        # Step 2: Obtain verified identifiers as of the cutoff
        cutoff_idents = resolver.identifiers_for_user(user_id, audit_at_raw)
        idents = cutoff_idents.get("identifiers", {})
        
        target_emails = set(idents.get("email", []))
        target_hashes = set(idents.get("email_hash", []))
        target_phones = set(idents.get("phone", []))

        # Check current snapshot email to distinguish current vs historical
        snapshot = resolver.identities.get(user_id, {})
        current_email = snapshot.get("email", "")

        identifier_provenance = {
            "user_id": user_id,
            "current_email": current_email,
            "all_emails": sorted(list(target_emails)),
            "historical_emails": sorted([e for e in target_emails if normalize(e) != normalize(current_email)]),
            "email_hashes": sorted(list(target_hashes)),
            "phones": sorted(list(target_phones)),
        }

        # Step 3: Search evidence corpus using verified identifiers
        admissible_matches = []
        excluded_matches = []
        unattributed_candidates = []

        normalized_target_emails = {normalize(e) for e in target_emails if e}
        normalized_target_hashes = {normalize(h) for h in target_hashes if h}
        normalized_target_phones = {p.strip() for p in target_phones if p}

        user_id_regex = make_word_boundary_regex(user_id)
        email_regexes = {e: make_word_boundary_regex(e) for e in target_emails if e}

        evidence_errors = list(self.inventory_errors)
        for entry in self.inventory_entries:
            if not entry["valid"]:
                for err in entry.get("errors", []):
                    evidence_errors.append(f"[{entry.get('file_id') or 'NO_ID'}] {err}")
                continue
            if not entry["resolved_path"]:
                continue

            file_id = entry["file_id"]
            file_path = entry["file_path"]
            origin = entry["origin"]
            captured_at = entry["captured_at"]
            captured_at_str = captured_at.isoformat().replace("+00:00", "Z") if captured_at else None

            # Capture cutoff rule: if evidence was captured after audit cutoff, it cannot prove state at cutoff
            capture_exceeds_cutoff = captured_at is not None and captured_at > audit_cutoff

            parsed = self.get_parsed_file(file_id, entry["resolved_path"])
            for err in parsed.get("errors", []):
                evidence_errors.append(f"[{file_id}] {err}")

            records = parsed.get("records", [])

            # Pre-index trace IDs for log records to associate request traces with resources
            trace_to_res: dict[str, str] = {}
            trace_to_result: dict[str, str] = {}
            trace_to_sys: dict[str, str] = {}
            for rec in records:
                if rec.get("record_type") == "log_line":
                    raw_t = rec.get("raw_text", "")
                    fields = rec.get("fields", {})
                    tid = fields.get("trace_id") or fields.get("requestId") or fields.get("bracket_id")
                    if not tid:
                        m_tr = re.search(r"\btr-[0-9a-zA-Z_-]+\b", raw_t)
                        if m_tr:
                            tid = m_tr.group(0)
                    if tid:
                        clean_tid = str(tid).strip(' "\'\\')
                        raw_rid = rec.get("resource_id") or fields.get("resource_id")
                        if not raw_rid:
                            m_rid = re.search(r"resource_id=[\"\x27]?([a-zA-Z0-9_]+)[\"\x27]?", raw_t)
                            if m_rid:
                                raw_rid = m_rid.group(1)
                        if raw_rid:
                            clean_rid = str(raw_rid).strip(' "\'\\')
                            trace_to_res[clean_tid] = clean_rid
                            raw_tl = raw_t.lower()
                            if 'rows="0"' in raw_tl or 'status="404"' in raw_tl or 'http_status="404"' in raw_tl:
                                trace_to_result[clean_tid] = "NOT_FOUND"
                            elif 'rows="1"' in raw_tl or 'status="200"' in raw_tl or 'http_status="200"' in raw_tl:
                                trace_to_result[clean_tid] = "FOUND"
                            elif 'enabled="true"' in raw_tl:
                                trace_to_result[clean_tid] = "ACTIVE"
                            elif 'enabled="false"' in raw_tl:
                                trace_to_result[clean_tid] = "DISABLED"
                        for s_cand in ("account_service", "search_service", "integration_service", "security_service", "backup_service", "support_platform"):
                            if s_cand in raw_t:
                                trace_to_sys[clean_tid] = s_cand
                                break

            # Search structured records
            for rec_idx, rec in enumerate(records):
                matches_found = self._match_record(
                    rec=rec,
                    user_id=user_id,
                    user_id_regex=user_id_regex,
                    normalized_target_emails=normalized_target_emails,
                    email_regexes=email_regexes,
                    normalized_target_hashes=normalized_target_hashes,
                    normalized_target_phones=normalized_target_phones,
                    current_email=current_email,
                )

                for match in matches_found:
                    raw_t = rec.get("raw_text", "")
                    if not match.get("resource_id"):
                        fields = match.get("record_summary", {})
                        tid = fields.get("trace_id") or fields.get("requestId") or fields.get("bracket_id") if isinstance(fields, dict) else None
                        if not tid:
                            m_tr = re.search(r"\btr-[0-9a-zA-Z_-]+\b", raw_t)
                            if m_tr:
                                tid = m_tr.group(0)
                        if tid:
                            clean_tid = str(tid).strip(' "\'\\')
                            if clean_tid in trace_to_res:
                                match["resource_id"] = trace_to_res[clean_tid]
                                if clean_tid in trace_to_result and isinstance(fields, dict):
                                    fields["result"] = trace_to_result[clean_tid]
                            if clean_tid in trace_to_sys and match.get("system_id") in ("log_service", None, "unknown_system"):
                                match["system_id"] = trace_to_sys[clean_tid]

                    event_time_raw = match.get("event_time")
                    event_time = None
                    event_exceeds_cutoff = False
                    
                    if event_time_raw:
                        try:
                            event_time = parse_timestamp(event_time_raw)
                            if event_time > audit_cutoff:
                                event_exceeds_cutoff = True
                        except (ValueError, TypeError):
                            event_time = None

                    # Check temporal contradiction: event_time > captured_at
                    temporal_contradiction = False
                    if event_time and captured_at and event_time > captured_at:
                        temporal_contradiction = True

                    # Determine admissibility
                    if capture_exceeds_cutoff:
                        is_admissible = False
                        exclusion_reason = "EXCLUDED_CAPTURE_POST_CUTOFF"
                    elif event_exceeds_cutoff:
                        is_admissible = False
                        exclusion_reason = "EXCLUDED_EVENT_POST_CUTOFF"
                    elif temporal_contradiction:
                        is_admissible = False
                        exclusion_reason = "EXCLUDED_TEMPORAL_CONTRADICTION"
                    else:
                        is_admissible = True
                        exclusion_reason = None

                    match_obj = {
                        "evidence_id": file_id,
                        "source_path": file_path,
                        "origin": origin,
                        "record_index": rec_idx,
                        "system_id": match.get("system_id"),
                        "resource_id": match.get("resource_id"),
                        "event_type": match.get("event_type"),
                        "matched_identifier": match.get("matched_identifier"),
                        "identifier_type": match.get("identifier_type"),
                        "match_field": match.get("match_field"),
                        "match_basis": match.get("match_basis"),
                        "event_time": event_time_raw,
                        "captured_at": captured_at_str,
                        "is_admissible": is_admissible,
                        "exclusion_reason": exclusion_reason,
                        "explanation": (
                            f"Matched {match.get('identifier_type')} '{match.get('matched_identifier')}' "
                            f"in {file_id} ({origin}) via {match.get('match_field')} for {match.get('resource_id')}"
                        ),
                        "record_summary": match.get("record_summary"),
                    }

                    if is_admissible:
                        admissible_matches.append(match_obj)
                    else:
                        excluded_matches.append(match_obj)

        return {
            "case_id": case_id,
            "email": email,
            "audit_at": audit_at_raw,
            "resolution": {
                "status": resolution_status,
                "user_id": user_id,
                "identifiers": identifier_provenance,
            },
            "admissible_matches": admissible_matches,
            "excluded_matches": excluded_matches,
            "unattributed_candidates": unattributed_candidates,
            "errors": evidence_errors,
            "summary": {
                "total_matches": len(admissible_matches) + len(excluded_matches),
                "admissible": len(admissible_matches),
                "excluded": len(excluded_matches),
                "unique_systems": sorted(list({m["system_id"] for m in admissible_matches if m.get("system_id")})),
                "unique_resources": sorted(list({m["resource_id"] for m in admissible_matches if m.get("resource_id")})),
            },
        }

    def _match_record(
        self,
        rec: dict,
        user_id: str,
        user_id_regex: re.Pattern,
        normalized_target_emails: set,
        email_regexes: dict,
        normalized_target_hashes: set,
        normalized_target_phones: set,
        current_email: str,
    ) -> list[dict]:
        """Match an individual extracted evidence record against target identifiers."""
        matches = []
        rec_type = rec.get("record_type")
        stmt_type = rec.get("statement_type")

        # 1. SQL INSERT statement
        if stmt_type == "INSERT INTO":
            values = rec.get("values", {})
            table = rec.get("table", "database")
            res_id = values.get("resource_id") or values.get("id")
            sys_id = values.get("origin_system") or ("account_service" if "account" in table or "profile" in table else table)

            # Check user_id
            for id_field in ("user_id", "subject_reference", "customer_reference", "correlation_key"):
                rec_user_id = str(values.get(id_field) or "")
                if rec_user_id == user_id:
                    matches.append({
                        "system_id": sys_id,
                        "resource_id": res_id,
                        "event_type": "DATABASE_RECORD",
                        "event_time": values.get("updated_at") or values.get("created_at"),
                        "matched_identifier": user_id,
                        "identifier_type": "user_id",
                        "match_field": f"{table}.{id_field}",
                        "match_basis": f"Exact user_id match in table {table}",
                        "record_summary": {k: v for k, v in values.items() if k not in ("password", "salt")},
                    })
                    break

            # Check email
            for em_field in ("email", "owner_email", "customer_email", "requester_email", "subject_reference", "customer_reference"):
                rec_email = str(values.get(em_field) or "")
                if normalize(rec_email) in normalized_target_emails:
                    id_type = "current_email" if normalize(rec_email) == normalize(current_email) else "historical_email"
                    matches.append({
                        "system_id": sys_id,
                        "resource_id": res_id,
                        "event_type": "DATABASE_RECORD",
                        "event_time": values.get("updated_at") or values.get("created_at"),
                        "matched_identifier": rec_email,
                        "identifier_type": id_type,
                        "match_field": f"{table}.{em_field}",
                        "match_basis": f"Exact email match in table {table}",
                        "record_summary": {k: v for k, v in values.items() if k not in ("password", "salt")},
                    })
                    break

            # Check phone
            rec_phone = str(values.get("phone") or "")
            if rec_phone.strip() in normalized_target_phones:
                matches.append({
                    "system_id": sys_id,
                    "resource_id": res_id,
                    "event_type": "DATABASE_RECORD",
                    "event_time": values.get("updated_at") or values.get("created_at"),
                    "matched_identifier": rec_phone,
                    "identifier_type": "phone",
                    "match_field": f"{table}.phone",
                    "match_basis": f"Exact phone match in table {table}",
                    "record_summary": {k: v for k, v in values.items() if k not in ("password", "salt")},
                })

            # Inspect structured record_json if present in values or rec
            rec_json = rec.get("record_json")
            if not rec_json and "record_json" in values:
                raw_rj = values.get("record_json")
                if isinstance(raw_rj, str):
                    try:
                        rec_json = json.loads(raw_rj)
                    except Exception:
                        rec_json = None
                elif isinstance(raw_rj, dict):
                    rec_json = raw_rj

            if isinstance(rec_json, dict):
                sub = self._match_dict_item(
                    item=rec_json,
                    system_id=sys_id,
                    user_id=user_id,
                    normalized_target_emails=normalized_target_emails,
                    normalized_target_hashes=normalized_target_hashes,
                    normalized_target_phones=normalized_target_phones,
                    current_email=current_email,
                    fallback_time=values.get("updated_at") or values.get("created_at"),
                )
                matches.extend(sub)
                if "document" in rec_json and isinstance(rec_json["document"], dict):
                    sub_doc = self._match_dict_item(
                        item=rec_json["document"],
                        system_id=sys_id,
                        user_id=user_id,
                        normalized_target_emails=normalized_target_emails,
                        normalized_target_hashes=normalized_target_hashes,
                        normalized_target_phones=normalized_target_phones,
                        current_email=current_email,
                        fallback_time=values.get("updated_at") or values.get("created_at"),
                    )
                    matches.extend(sub_doc)

            return matches

        # 2. JSON document with service_exports (e.g. evidence_92)
        raw_doc = rec.get("raw_record", {})
        if isinstance(raw_doc, dict) and "service_exports" in raw_doc:
            exports = raw_doc.get("service_exports", {})
            for sys_name, sys_content in exports.items():
                if not isinstance(sys_content, dict):
                    continue
                for list_name, item_list in sys_content.items():
                    if not isinstance(item_list, list):
                        continue
                    for item in item_list:
                        if not isinstance(item, dict):
                            continue
                        sub_matches = self._match_dict_item(
                            item=item,
                            system_id=sys_name,
                            user_id=user_id,
                            normalized_target_emails=normalized_target_emails,
                            normalized_target_hashes=normalized_target_hashes,
                            normalized_target_phones=normalized_target_phones,
                            current_email=current_email,
                        )
                        matches.extend(sub_matches)
            return matches

        # 3. JSON document with snapshots (e.g. evidence_51)
        if isinstance(raw_doc, dict) and "snapshots" in raw_doc:
            snapshots = raw_doc.get("snapshots", [])
            for snap in snapshots:
                if not isinstance(snap, dict):
                    continue
                data_store = snap.get("data_store", "data_store")
                snap_time = snap.get("captured_at")
                for item in snap.get("records", []):
                    if not isinstance(item, dict):
                        continue
                    sub_matches = self._match_dict_item(
                        item=item,
                        system_id=data_store,
                        user_id=user_id,
                        normalized_target_emails=normalized_target_emails,
                        normalized_target_hashes=normalized_target_hashes,
                        normalized_target_phones=normalized_target_phones,
                        current_email=current_email,
                        fallback_time=snap_time,
                    )
                    matches.extend(sub_matches)
            return matches

        # 3b. JSON document with top-level records array (e.g. manifest, ledger, reports)
        if isinstance(raw_doc, dict) and "records" in raw_doc and isinstance(raw_doc["records"], list):
            doc_source = raw_doc.get("source") or raw_doc.get("origin") or "record_service"
            doc_time = raw_doc.get("exported_at") or raw_doc.get("captured_at")
            for item in raw_doc["records"]:
                if not isinstance(item, dict):
                    continue
                sys_id = item.get("system") or doc_source
                sub_matches = self._match_dict_item(
                    item=item,
                    system_id=sys_id,
                    user_id=user_id,
                    normalized_target_emails=normalized_target_emails,
                    normalized_target_hashes=normalized_target_hashes,
                    normalized_target_phones=normalized_target_phones,
                    current_email=current_email,
                    fallback_time=item.get("recorded_at") or item.get("created_at") or doc_time,
                )
                matches.extend(sub_matches)
            return matches

        # 4. JSON record
        if rec_type == "json_record":
            item = rec.get("raw_record", {})
            if isinstance(item, dict):
                sub_matches = self._match_dict_item(
                    item=item,
                    system_id=rec.get("data_store") or "json_store",
                    user_id=user_id,
                    normalized_target_emails=normalized_target_emails,
                    normalized_target_hashes=normalized_target_hashes,
                    normalized_target_phones=normalized_target_phones,
                    current_email=current_email,
                    fallback_time=rec.get("snapshot_captured_at"),
                )
                matches.extend(sub_matches)
            return matches

        # 5. Log line (e.g. evidence_94)
        if rec_type == "log_line":
            fields = rec.get("fields", {})
            event_ts = rec.get("event_timestamp")
            raw_res = rec.get("resource_id") or fields.get("resource_id")
            res_id = str(raw_res).strip(' "\'\\') if raw_res else None
            sys_id = fields.get("service") or fields.get("function") or "log_service"
            if isinstance(sys_id, str):
                sys_id = sys_id.strip(' "\'\\')

            # Check user_id fields
            for id_field in ("subject_reference", "customer_reference", "correlation_key", "user_id"):
                raw_ref = str(fields.get(id_field) or "").strip(' "\'\\')
                if raw_ref == user_id:
                    matches.append({
                        "system_id": sys_id,
                        "resource_id": res_id,
                        "event_type": str(fields.get("event", "LOG_EVENT")).strip(' "\'\\'),
                        "event_time": event_ts,
                        "matched_identifier": user_id,
                        "identifier_type": "user_id",
                        "match_field": f"log.{id_field}",
                        "match_basis": f"Exact user_id match in log line {rec.get('line_number')}",
                        "record_summary": fields,
                    })
                    break

            # Check email fields
            for em_field in (
                "lookup_key",
                "match_key",
                "matched_value",
                "email",
                "owner_email",
                "customer_email",
                "requester_email",
                "subject_key",
                "subject_reference",
            ):
                raw_em = str(fields.get(em_field) or "").strip(' "\'\\')
                if normalize(raw_em) in normalized_target_emails:
                    id_type = "current_email" if normalize(raw_em) == normalize(current_email) else "historical_email"
                    matches.append({
                        "system_id": sys_id,
                        "resource_id": res_id,
                        "event_type": str(fields.get("event", "LOG_EVENT")).strip(' "\'\\'),
                        "event_time": event_ts,
                        "matched_identifier": raw_em,
                        "identifier_type": id_type,
                        "match_field": f"log.{em_field}",
                        "match_basis": f"Exact email match in log line {rec.get('line_number')}",
                        "record_summary": fields,
                    })
                    break

            # Fallback to regex on raw text if no match found yet
            if not matches:
                raw_text = rec.get("raw_text", "")
                if user_id_regex.search(raw_text):
                    matches.append({
                        "system_id": sys_id,
                        "resource_id": res_id,
                        "event_type": str(fields.get("event", "LOG_EVENT")).strip(' "\'\\'),
                        "event_time": event_ts,
                        "matched_identifier": user_id,
                        "identifier_type": "user_id",
                        "match_field": "log.raw_text",
                        "match_basis": f"Regex user_id match in log line {rec.get('line_number')}",
                        "record_summary": fields,
                    })
                else:
                    for email_val, regex in email_regexes.items():
                        if regex.search(raw_text):
                            id_type = "current_email" if normalize(email_val) == normalize(current_email) else "historical_email"
                            matches.append({
                                "system_id": sys_id,
                                "resource_id": res_id,
                                "event_type": str(fields.get("event", "LOG_EVENT")).strip(' "\'\\'),
                                "event_time": event_ts,
                                "matched_identifier": email_val,
                                "identifier_type": id_type,
                                "match_field": "log.raw_text",
                                "match_basis": f"Regex email match in log line {rec.get('line_number')}",
                                "record_summary": fields,
                            })
                            break

            return matches

        # 6. Text line (e.g. evidence_03)
        if rec_type == "text_line":
            raw_text = rec.get("raw_text", "")
            # Check pipe-separated format: timestamp | system_id | resource_id | category | status | match_key
            parts = [p.strip() for p in raw_text.split("|")]
            if len(parts) >= 6:
                ts, sys_id, res_id, cat, status, match_key = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
                if match_key == user_id:
                    matches.append({
                        "system_id": sys_id,
                        "resource_id": res_id,
                        "event_type": f"{cat}_{status}",
                        "event_time": ts,
                        "matched_identifier": user_id,
                        "identifier_type": "user_id",
                        "match_field": "text.match_key",
                        "match_basis": "Exact user_id match in shift handover entry",
                        "record_summary": {"status": status, "category": cat, "line": raw_text},
                    })
                elif normalize(match_key) in normalized_target_emails:
                    id_type = "current_email" if normalize(match_key) == normalize(current_email) else "historical_email"
                    matches.append({
                        "system_id": sys_id,
                        "resource_id": res_id,
                        "event_type": f"{cat}_{status}",
                        "event_time": ts,
                        "matched_identifier": match_key,
                        "identifier_type": id_type,
                        "match_field": "text.match_key",
                        "match_basis": "Exact email match in shift handover entry",
                        "record_summary": {"status": status, "category": cat, "line": raw_text},
                    })
            else:
                # Text word-boundary checks
                for email_val, regex in email_regexes.items():
                    if regex.search(raw_text):
                        id_type = "current_email" if normalize(email_val) == normalize(current_email) else "historical_email"
                        matches.append({
                            "system_id": "document_service",
                            "resource_id": None,
                            "event_type": "TEXT_ENTRY",
                            "event_time": None,
                            "matched_identifier": email_val,
                            "identifier_type": id_type,
                            "match_field": "text.raw_text",
                            "match_basis": "Word-bounded email match in text line",
                            "record_summary": {"line": raw_text},
                        })
            return matches

        # 7. PDF or PNG image
        if rec_type in ("pdf_page", "image_ocr"):
            raw_text = rec.get("raw_text", "")
            if user_id_regex.search(raw_text):
                matches.append({
                    "system_id": "document_service" if rec_type == "pdf_page" else "image_service",
                    "resource_id": None,
                    "event_type": "DOCUMENT_ENTRY" if rec_type == "pdf_page" else "IMAGE_OCR_ENTRY",
                    "event_time": None,
                    "matched_identifier": user_id,
                    "identifier_type": "user_id",
                    "match_field": f"{rec_type}.raw_text",
                    "match_basis": f"Word-bounded user_id match in {rec_type}",
                    "record_summary": {"snippet": raw_text[:200]},
                })
            for email_val, regex in email_regexes.items():
                if regex.search(raw_text):
                    id_type = "current_email" if normalize(email_val) == normalize(current_email) else "historical_email"
                    matches.append({
                        "system_id": "document_service" if rec_type == "pdf_page" else "image_service",
                        "resource_id": None,
                        "event_type": "DOCUMENT_ENTRY" if rec_type == "pdf_page" else "IMAGE_OCR_ENTRY",
                        "event_time": None,
                        "matched_identifier": email_val,
                        "identifier_type": id_type,
                        "match_field": f"{rec_type}.raw_text",
                        "match_basis": f"Word-bounded email match in {rec_type}",
                        "record_summary": {"snippet": raw_text[:200]},
                    })
            return matches

        return matches

    def _match_dict_item(
        self,
        item: dict,
        system_id: str,
        user_id: str,
        normalized_target_emails: set,
        normalized_target_hashes: set,
        normalized_target_phones: set,
        current_email: str,
        fallback_time: str = None,
    ) -> list[dict]:
        """Helper to match structured dictionary objects from JSON."""
        matches = []
        res_id = item.get("resource_id") or item.get("id")
        obs_time = item.get("recorded_at") or item.get("observed_at") or item.get("updated_at") or item.get("created_at") or fallback_time

        # Match user_id
        for id_field in ("customer_reference", "subject_reference", "user_id", "correlation_key", "subject_key"):
            val = str(item.get(id_field) or "")
            if val == user_id:
                matches.append({
                    "system_id": system_id,
                    "resource_id": res_id,
                    "event_type": "STRUCTURED_RECORD",
                    "event_time": obs_time,
                    "matched_identifier": user_id,
                    "identifier_type": "user_id",
                    "match_field": f"{system_id}.{id_field}",
                    "match_basis": f"Exact user_id match in field {id_field}",
                    "record_summary": item,
                })
                break

        # Match email
        for email_field in (
            "email",
            "owner_email",
            "customer_email",
            "requester_email",
            "query",
            "lookup_key",
            "match_key",
            "subject_key",
            "subject_reference",
            "customer_reference",
        ):
            val = str(item.get(email_field) or "")
            if normalize(val) in normalized_target_emails:
                id_type = "current_email" if normalize(val) == normalize(current_email) else "historical_email"
                matches.append({
                    "system_id": system_id,
                    "resource_id": res_id,
                    "event_type": "STRUCTURED_RECORD",
                    "event_time": obs_time,
                    "matched_identifier": val,
                    "identifier_type": id_type,
                    "match_field": f"{system_id}.{email_field}",
                    "match_basis": f"Exact email match in field {email_field}",
                    "record_summary": item,
                })
                break

        # Match hits documents inside search queries
        if "hits" in item and isinstance(item["hits"], dict):
            for doc in item["hits"].get("documents", []):
                if isinstance(doc, dict):
                    doc_email = str(doc.get("email") or "")
                    if normalize(doc_email) in normalized_target_emails:
                        id_type = "current_email" if normalize(doc_email) == normalize(current_email) else "historical_email"
                        matches.append({
                            "system_id": system_id,
                            "resource_id": doc.get("resource_id") or res_id,
                            "event_type": "SEARCH_HIT",
                            "event_time": obs_time,
                            "matched_identifier": doc_email,
                            "identifier_type": id_type,
                            "match_field": f"{system_id}.hits.documents.email",
                            "match_basis": "Matching document in search index query hits",
                            "record_summary": doc,
                        })

        # Match phone
        for phone_field in ("phone", "owner_phone", "requester_phone"):
            val = str(item.get(phone_field) or "")
            if val.strip() in normalized_target_phones:
                matches.append({
                    "system_id": system_id,
                    "resource_id": res_id,
                    "event_type": "STRUCTURED_RECORD",
                    "event_time": obs_time,
                    "matched_identifier": val,
                    "identifier_type": "phone",
                    "match_field": f"{system_id}.{phone_field}",
                    "match_basis": f"Exact phone match in field {phone_field}",
                    "record_summary": item,
                })
                break

        # Match email hash
        for hash_field in ("email_hash",):
            val = str(item.get(hash_field) or "")
            if normalize(val) in normalized_target_hashes:
                matches.append({
                    "system_id": system_id,
                    "resource_id": res_id,
                    "event_type": "STRUCTURED_RECORD",
                    "event_time": obs_time,
                    "matched_identifier": val,
                    "identifier_type": "email_hash",
                    "match_field": f"{system_id}.{hash_field}",
                    "match_basis": f"Exact email_hash match in field {hash_field}",
                    "record_summary": item,
                })
        # Match nested dicts like profile, record, user, data
        for nested_key in ("profile", "record", "user", "data", "attributes", "payload"):
            if nested_key in item and isinstance(item[nested_key], dict):
                sub = self._match_dict_item(
                    item=item[nested_key],
                    system_id=system_id,
                    user_id=user_id,
                    normalized_target_emails=normalized_target_emails,
                    normalized_target_hashes=normalized_target_hashes,
                    normalized_target_phones=normalized_target_phones,
                    current_email=current_email,
                    fallback_time=obs_time,
                )
                for s in sub:
                    if not s.get("resource_id") and res_id:
                        s["resource_id"] = res_id
                matches.extend(sub)

        return matches

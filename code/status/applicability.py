"""Phase 7: Request Applicability and Deletion Intent Evaluator.

Analyzes the authoritative request_text to determine whether personal data deletion
was genuinely requested and authorized, independently of operational workflow statuses.
"""

import re
from typing import Optional, Any

try:
    from .models import (
        DeletionStatus,
        RequestIntentCategory,
        RequestApplicabilityResult,
    )
except ImportError:
    from models import (
        DeletionStatus,
        RequestIntentCategory,
        RequestApplicabilityResult,
    )


# ---------------------------------------------------------------------------
# Non-deletion regex patterns grouped by granular category
# ---------------------------------------------------------------------------

PATTERNS_PORTABILITY = [
    (re.compile(r"portable format", re.IGNORECASE), "portable format"),
    (re.compile(r"data portability", re.IGNORECASE), "data portability"),
    (re.compile(r"download (?:my )?account information", re.IGNORECASE), "download account information"),
    (re.compile(r"export (?:my )?(?:personal )?data", re.IGNORECASE), "export data"),
]

PATTERNS_OPT_OUT = [
    (re.compile(r"opt[- ]?out of (?:marketing|promotional)", re.IGNORECASE), "opt-out of marketing"),
    (re.compile(r"marketing lists? only", re.IGNORECASE), "marketing lists only"),
    (re.compile(r"stop (?:the )?promotional emails", re.IGNORECASE), "stop promotional emails"),
    (re.compile(r"unsubscribe (?:me )?from", re.IGNORECASE), "unsubscribe from marketing"),
    (re.compile(r"\bunsubscribe\b", re.IGNORECASE), "unsubscribe"),
]

PATTERNS_RECTIFICATION = [
    (re.compile(r"\brectification\b", re.IGNORECASE), "rectification"),
    (re.compile(r"\brectify\b", re.IGNORECASE), "rectify"),
    (re.compile(r"misspelled", re.IGNORECASE), "misspelled"),
    (re.compile(r"correct it without removing", re.IGNORECASE), "correct without removing"),
    (re.compile(r"change the email address", re.IGNORECASE), "change email address"),
    (re.compile(r"out of date.*replace it", re.IGNORECASE), "replace outdated data"),
]

PATTERNS_ACCESS_REQUEST = [
    (re.compile(r"subject access request", re.IGNORECASE), "subject access request"),
    (re.compile(r"information request", re.IGNORECASE), "information request"),
    (re.compile(r"not a request to erase", re.IGNORECASE), "not a request to erase"),
    (re.compile(r"what personal information you hold", re.IGNORECASE), "what personal info held"),
    (re.compile(r"copy of (?:last year['’]s )?invoices", re.IGNORECASE), "copy of invoices"),
    (re.compile(r"copy of the information held", re.IGNORECASE), "copy of information held"),
]

PATTERNS_SUPPORT_HELP = [
    (re.compile(r"can['’]t access my profile", re.IGNORECASE), "cannot access profile"),
    (re.compile(r"resetting the login", re.IGNORECASE), "resetting login"),
    (re.compile(r"help resetting", re.IGNORECASE), "help resetting"),
    (re.compile(r"password reset", re.IGNORECASE), "password reset"),
]

PATTERNS_ACCOUNT_RETENTION = [
    (re.compile(r"leave (?:the )?account active", re.IGNORECASE), "leave account active"),
    (re.compile(r"keep (?:my |the )?account (?:active|open|as it is)", re.IGNORECASE), "keep account open/active"),
    (re.compile(r"do not (?:close|delete)", re.IGNORECASE), "do not close/delete"),
    (re.compile(r"don['’]t (?:close|delete)", re.IGNORECASE), "don't close/delete"),
    (re.compile(r"not asking for deletion", re.IGNORECASE), "not asking for deletion"),
    (re.compile(r"without removing", re.IGNORECASE), "without removing"),
    (re.compile(r"leave (?:.*)?in place", re.IGNORECASE), "leave in place"),
    (re.compile(r"continue using the service", re.IGNORECASE), "continue using service"),
    (re.compile(r"don['’]t delete or change", re.IGNORECASE), "don't delete or change"),
    (re.compile(r"no (?:quiero|deseo) eliminar", re.IGNORECASE), "no quiero eliminar (es)"),
    (re.compile(r"ne pas supprimer", re.IGNORECASE), "ne pas supprimer (fr)"),
    (re.compile(r"nicht löschen", re.IGNORECASE), "nicht löschen (de)"),
]

# ---------------------------------------------------------------------------
# Positive deletion authorization patterns
# ---------------------------------------------------------------------------

PATTERNS_DELETION_AUTHORIZATION = [
    (re.compile(r"\bdelet\w*", re.IGNORECASE), "deletion"),
    (re.compile(r"\beras\w*", re.IGNORECASE), "erasure"),
    (re.compile(r"\bremov\w*", re.IGNORECASE), "remove"),
    (re.compile(r"close (?:my |the |this )?account", re.IGNORECASE), "close account"),
    (re.compile(r"personal-data deletion", re.IGNORECASE), "personal-data deletion"),
    (re.compile(r"account-deletion", re.IGNORECASE), "account-deletion"),
    (re.compile(r"elimina[cr]", re.IGNORECASE), "eliminar (es)"),
    (re.compile(r"eliminaci[oó]n", re.IGNORECASE), "eliminación (es)"),
    (re.compile(r"suppri\w*", re.IGNORECASE), "supprimer (fr)"),
    (re.compile(r"suppress\w*", re.IGNORECASE), "suppression (fr)"),
    (re.compile(r"\bpurge\b", re.IGNORECASE), "purge"),
    (re.compile(r"exclus[ãa]o", re.IGNORECASE), "exclusão (pt)"),
    (re.compile(r"excluir", re.IGNORECASE), "excluir (pt)"),
    (re.compile(r"l[öo]sch\w*", re.IGNORECASE), "löschen (de)"),
    (re.compile(r"cancell\w*", re.IGNORECASE), "cancellare (it)"),
    (re.compile(r"削除"), "削除 (ja)"),
    (re.compile(r"삭제"), "삭제 (ko)"),
    (re.compile(r"profile is gone", re.IGNORECASE), "verify profile gone"),
    (re.compile(r"account (?:was|is) (?:deleted|closed|gone)", re.IGNORECASE), "verify account deleted"),
]


class RequestApplicabilityEvaluator:
    """
    Deterministic evaluator for request applicability and deletion authorization.
    
    Evaluates requests according to AGENTS.md §6.5:
    'First determine whether request_text authorizes deletion. A request for access,
    correction, export, marketing opt-out, or another non-deletion action is NOT_APPLICABLE,
    even if other fields resemble a deletion case.'
    """

    def evaluate_request(self, request: dict[str, Any]) -> RequestApplicabilityResult:
        """
        Evaluate a single deletion request dictionary from deletion_requests.csv.
        
        Args:
            request: Dict with keys: case_id, email, requested_at, reported_status,
                     reported_at, audit_at, request_text
                     
        Returns:
            RequestApplicabilityResult specifying applicability, intent category, and reason.
        """
        case_id = str(request.get("case_id", "")).strip()
        email = str(request.get("email", "")).strip()
        audit_at = str(request.get("audit_at", "")).strip() or None
        reported_status = str(request.get("reported_status", "")).strip()
        raw_text = str(request.get("request_text", "") or "").strip()

        diagnostics = []

        # 1. Check for missing or malformed request text
        if not raw_text:
            diagnostics.append("Missing or empty request_text; cannot establish deletion authorization.")
            if reported_status:
                diagnostics.append(
                    f"Operational reported_status '{reported_status}' ignored; missing request text."
                )
            return RequestApplicabilityResult(
                case_id=case_id,
                is_applicable=False,
                deletion_status=DeletionStatus.NOT_APPLICABLE.value,
                intent_category=RequestIntentCategory.MALFORMED_EMPTY_TEXT,
                reason="Request text is missing, empty, or malformed; deletion is not authorized.",
                detected_patterns=[],
                raw_text=raw_text,
                email=email,
                audit_at=audit_at,
                reported_status=reported_status,
                diagnostics=diagnostics,
            )

        # 2. Scan for non-deletion intent categories
        non_del_matches = []
        matched_categories = []

        # Check Portability
        for regex, name in PATTERNS_PORTABILITY:
            if regex.search(raw_text):
                non_del_matches.append(name)
                matched_categories.append(RequestIntentCategory.NON_DELETION_PORTABILITY)

        # Check Opt-out
        for regex, name in PATTERNS_OPT_OUT:
            if regex.search(raw_text):
                non_del_matches.append(name)
                matched_categories.append(RequestIntentCategory.NON_DELETION_OPT_OUT)

        # Check Rectification
        for regex, name in PATTERNS_RECTIFICATION:
            if regex.search(raw_text):
                non_del_matches.append(name)
                matched_categories.append(RequestIntentCategory.NON_DELETION_RECTIFICATION)

        # Check Access request
        for regex, name in PATTERNS_ACCESS_REQUEST:
            if regex.search(raw_text):
                non_del_matches.append(name)
                matched_categories.append(RequestIntentCategory.NON_DELETION_ACCESS_REQUEST)

        # Check Support help
        for regex, name in PATTERNS_SUPPORT_HELP:
            if regex.search(raw_text):
                non_del_matches.append(name)
                matched_categories.append(RequestIntentCategory.NON_DELETION_SUPPORT_HELP)

        # Check Account retention / "do not delete"
        for regex, name in PATTERNS_ACCOUNT_RETENTION:
            if regex.search(raw_text):
                non_del_matches.append(name)
                matched_categories.append(RequestIntentCategory.NON_DELETION_ACCOUNT_RETENTION)

        # 3. Scan for positive deletion authorization
        deletion_matches = []
        deletion_spans = []
        for regex, name in PATTERNS_DELETION_AUTHORIZATION:
            for m in regex.finditer(raw_text):
                if name not in deletion_matches:
                    deletion_matches.append(name)
                deletion_spans.append((m.start(), m.end(), m.group(0)))

        # 4. Check for contradictory intent signals (both strong deletion AND strong retention)
        if non_del_matches and deletion_matches:
            # Check if deletion match was just part of a non-deletion negation (e.g. "not asking for deletion", "don't delete")
            # If the only deletion match is negated by non-deletion phrases, it's non-deletion, not a contradiction.
            pure_negation_phrases = ["not asking for deletion", "do not close/delete", "don't close/delete", "not a request to erase", "don't delete or change"]
            has_pure_negation = any(p in non_del_matches for p in pure_negation_phrases)
            
            # Check if there is independent deletion intent
            # e.g. "Please delete all records. Also do not delete my account." -> Contradiction
            # vs "I am not asking for deletion." -> Pure negation of deletion word
            has_independent_deletion = False
            for start_idx, end_idx, matched_text in deletion_spans:
                # Look at surrounding characters
                start = max(0, start_idx - 20)
                end = min(len(raw_text), end_idx + 20)
                snippet = raw_text[start:end].lower()
                if not any(neg in snippet for neg in ["not", "don't", "don’t", "do not", "without"]):
                    has_independent_deletion = True
                    break

            if has_independent_deletion and RequestIntentCategory.NON_DELETION_ACCOUNT_RETENTION in matched_categories:
                diagnostics.append("Contradictory intent detected: request contains both deletion instructions and account retention demands.")
                return RequestApplicabilityResult(
                    case_id=case_id,
                    is_applicable=False,
                    deletion_status=DeletionStatus.NOT_APPLICABLE.value,
                    intent_category=RequestIntentCategory.AMBIGUOUS_CONTRADICTORY,
                    reason="Contradictory user intent: request contains conflicting deletion and retention instructions; deletion is not authorized.",
                    detected_patterns=sorted(list(set(non_del_matches + deletion_matches))),
                    raw_text=raw_text,
                    email=email,
                    audit_at=audit_at,
                    reported_status=reported_status,
                    diagnostics=diagnostics,
                )

        # 5. Handle Non-Deletion Request
        if non_del_matches:
            primary_category = matched_categories[0]
            if reported_status in ("COMPLETE", "PARTIALLY_COMPLETE"):
                diagnostics.append(
                    f"Operational reported_status '{reported_status}' disregarded; request text demonstrates non-deletion intent ({primary_category.value})."
                )

            category_labels = {
                RequestIntentCategory.NON_DELETION_PORTABILITY: "data portability / export",
                RequestIntentCategory.NON_DELETION_OPT_OUT: "marketing opt-out",
                RequestIntentCategory.NON_DELETION_RECTIFICATION: "account data rectification",
                RequestIntentCategory.NON_DELETION_ACCESS_REQUEST: "subject access / copy request",
                RequestIntentCategory.NON_DELETION_SUPPORT_HELP: "support / account recovery",
                RequestIntentCategory.NON_DELETION_ACCOUNT_RETENTION: "explicit account retention",
            }
            label = category_labels.get(primary_category, "non-deletion request")

            return RequestApplicabilityResult(
                case_id=case_id,
                is_applicable=False,
                deletion_status=DeletionStatus.NOT_APPLICABLE.value,
                intent_category=primary_category,
                reason=f"Request text authorizes a {label}, not personal data deletion.",
                detected_patterns=sorted(list(set(non_del_matches))),
                raw_text=raw_text,
                email=email,
                audit_at=audit_at,
                reported_status=reported_status,
                diagnostics=diagnostics,
            )

        # 6. Handle Valid Deletion Authorization
        if deletion_matches:
            return RequestApplicabilityResult(
                case_id=case_id,
                is_applicable=True,
                deletion_status=None,  # Defer case status resolution to downstream policy evaluation
                intent_category=RequestIntentCategory.DELETION_AUTHORIZED,
                reason="Request text authorizes personal data deletion.",
                detected_patterns=sorted(list(set(deletion_matches))),
                raw_text=raw_text,
                email=email,
                audit_at=audit_at,
                reported_status=reported_status,
                diagnostics=diagnostics,
            )

        # 7. Unmatched / Ambiguous Intent (neither deletion nor known non-deletion pattern matched)
        diagnostics.append("Request text does not match standard deletion authorization or recognized non-deletion patterns.")
        return RequestApplicabilityResult(
            case_id=case_id,
            is_applicable=False,
            deletion_status=DeletionStatus.NOT_APPLICABLE.value,
            intent_category=RequestIntentCategory.AMBIGUOUS_CONTRADICTORY,
            reason="Request text does not contain recognized authorization for personal data deletion.",
            detected_patterns=[],
            raw_text=raw_text,
            email=email,
            audit_at=audit_at,
            reported_status=reported_status,
            diagnostics=diagnostics,
        )

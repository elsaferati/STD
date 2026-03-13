from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

from db import execute, fetch_all, fetch_one, get_connection
from extraction_branches import BRANCHES
from gemini_validation import (
    VALIDATION_PROVIDER_GEMINI,
    VALIDATION_REVIEW_STATUSES,
    VALIDATION_STATUS_NOT_RUN,
    VALIDATION_STATUS_RESOLVED,
    VALID_VALIDATION_STATUSES,
    normalize_validation_status,
)

STATUS_OK = "ok"
STATUS_HUMAN = "human_in_the_loop"
STATUS_POST = "post"
STATUS_FAILED = "failed"
STATUS_PARTIAL = "partial"
STATUS_UNKNOWN = "unknown"
STATUS_WAITING_REPLY = "waiting_for_reply"
STATUS_CLIENT_REPLIED = "client_replied"
STATUS_UPDATED_AFTER_REPLY = "updated_after_reply"

VALID_STATUSES = {
    STATUS_OK,
    STATUS_HUMAN,
    STATUS_POST,
    STATUS_FAILED,
    STATUS_UNKNOWN,
    STATUS_WAITING_REPLY,
    STATUS_CLIENT_REPLIED,
    STATUS_UPDATED_AFTER_REPLY,
}
REVIEWABLE_STATUSES = {STATUS_WAITING_REPLY, STATUS_HUMAN, STATUS_POST}
TASK_DONE_STATES = {"resolved", "cancelled"}
UNKNOWN_EXTRACTION_BRANCH = "unknown"
KNOWN_EXTRACTION_BRANCHES = frozenset(BRANCHES.keys())
ALLOWED_EXTRACTION_BRANCHES = KNOWN_EXTRACTION_BRANCHES | {UNKNOWN_EXTRACTION_BRANCH}
_KNOWN_BRANCHES_SQL = ", ".join(f"'{branch}'" for branch in sorted(ALLOWED_EXTRACTION_BRANCHES))
_STATUS_SQL = """
CASE
    WHEN LOWER(BTRIM(COALESCE(o.status, ''))) = 'partial' THEN 'waiting_for_reply'
    WHEN LOWER(BTRIM(COALESCE(o.status, ''))) = 'reply'   THEN 'waiting_for_reply'
    WHEN LOWER(BTRIM(COALESCE(o.status, ''))) IN (
        'ok', 'human_in_the_loop', 'post', 'failed',
        'waiting_for_reply', 'client_replied', 'updated_after_reply', 'unknown'
    )
        THEN LOWER(BTRIM(COALESCE(o.status, '')))
    ELSE 'ok'
END
"""
_EXTRACTION_BRANCH_SQL = f"""
CASE
    WHEN LOWER(BTRIM(COALESCE(o.extraction_branch, ''))) IN ({_KNOWN_BRANCHES_SQL})
        THEN LOWER(BTRIM(COALESCE(o.extraction_branch, '')))
    ELSE '{UNKNOWN_EXTRACTION_BRANCH}'
END
"""
_EFFECTIVE_RECEIVED_SQL = "COALESCE(o.received_at, o.updated_at)"


class OrderStoreError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonb(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _entry_value(entry: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _entry_text(entry: Any) -> str:
    value = _entry_value(entry)
    return "" if value is None else str(value).strip()


def _entry_bool(entry: Any) -> bool:
    value = _entry_value(entry)
    if value is True:
        return True
    return str(value).strip().lower() == "true"


def _normalize_extraction_branch(value: Any) -> str:
    branch_id = str(value or "").strip().lower()
    if branch_id in ALLOWED_EXTRACTION_BRANCHES:
        return branch_id
    return UNKNOWN_EXTRACTION_BRANCH


def _normalize_validation_issues(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    issues: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        issues.append(
            {
                "severity": str(raw.get("severity") or "warning").strip().lower() or "warning",
                "scope": str(raw.get("scope") or "general").strip() or "general",
                "field_path": str(raw.get("field_path") or "").strip(),
                "source_evidence": str(raw.get("source_evidence") or "").strip(),
                "expected_value": str(raw.get("expected_value") or "").strip(),
                "xml_value": str(raw.get("xml_value") or "").strip(),
                "reason": str(raw.get("reason") or "").strip(),
            }
        )
    return issues


_ACTIONABLE_SIGNAL_PATTERNS = (
    re.compile(r"\bmissing (critical )?header fields?\b", re.IGNORECASE),
    re.compile(r"\bmissing (critical )?item fields?\b", re.IGNORECASE),
    re.compile(r"\bmissing line(?:-level)? data\b", re.IGNORECASE),
    re.compile(r"\bmissing ticket\b", re.IGNORECASE),
    re.compile(r"\bmissing items?\b", re.IGNORECASE),
    re.compile(r"\bno items?\b", re.IGNORECASE),
    re.compile(r"\breply needed:\s*missing\b", re.IGNORECASE),
)
_FOLLOW_UP_SIGNAL_PATTERNS = (
    re.compile(r"\bauto-?reply\b", re.IGNORECASE),
    re.compile(r"\breply email\b", re.IGNORECASE),
    re.compile(r"\bfollow-?up email\b", re.IGNORECASE),
    re.compile(r"\bmail (?:sent|queued|triggered)\b", re.IGNORECASE),
    re.compile(r"\bemail (?:sent|queued|triggered)\b", re.IGNORECASE),
)
_MAPPING_SIGNAL_PATTERNS = (
    re.compile(r"\blookup\b", re.IGNORECASE),
    re.compile(r"\bmapp(?:ing|ed|er)?\b", re.IGNORECASE),
    re.compile(r"\bmatch(?:ed|ing)?\b", re.IGNORECASE),
    re.compile(r"\bunmatched\b", re.IGNORECASE),
)
_INTERNAL_REVIEW_SIGNAL_PATTERNS = (
    re.compile(r"\brouting\b", re.IGNORECASE),
    re.compile(r"\bdebug\b", re.IGNORECASE),
    re.compile(r"\binternal (?:trigger|review|check)\b", re.IGNORECASE),
    re.compile(r"\breview check\b", re.IGNORECASE),
)
_HIDDEN_WARNING_PATTERNS = _FOLLOW_UP_SIGNAL_PATTERNS + _MAPPING_SIGNAL_PATTERNS + _INTERNAL_REVIEW_SIGNAL_PATTERNS + (
    re.compile(r"^Porta ambiguous-code human-review trigger activated from warning:", re.IGNORECASE),
    re.compile(r"^Porta explicit-pair review retained\b", re.IGNORECASE),
    re.compile(r"^Porta code consistency correction\b", re.IGNORECASE),
    re.compile(r"^Porta code-shape validation\b", re.IGNORECASE),
    re.compile(r"^Porta reconciliation\b", re.IGNORECASE),
    re.compile(r"^Porta component occurrence reconciliation\b", re.IGNORECASE),
    re.compile(r"^Porta inline pair reconciliation\b", re.IGNORECASE),
    re.compile(r"^Porta article-only reconciliation\b", re.IGNORECASE),
    re.compile(r"^Porta model-only reconciliation\b", re.IGNORECASE),
    re.compile(
        r"^zubeh(?:o|ö)rzeilen\b.*\bohne\s+explizite\s+mengenangabe\b.*\bmenge\s*=\s*1\s+default\b",
        re.IGNORECASE,
    ),
    re.compile(r"^kommission\s+im\s+pdf\s+als\s+.+?\/0\s+angegeben;\s*['\"]?\/0['\"]?\s+gem(?:aess|äß)\s+regel\s+entfernt\.?$", re.IGNORECASE),
    re.compile(
        r"^position\s+'.+?'\s+enth(?:aelt|ält)\s+keine\s+eindeutige\s+artikelnummer;\s+nur\s+modellnummer\s+extrahiert\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^artikel-nr\.\s*'.+?'\s*ist als porta-interne artikelnummer gekennzeichnet und wurde .+?artikelnummer\/modellnummer .+$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^artikel-nr\.\s*'.+?'\s*ist eine tabellen-spalte und wurde .+? ignoriert;\s*keine gueltige 5-stellige artikelnummer\/modellnummer im liefermodelltext gefunden\.?$",
        re.IGNORECASE,
    ),
)
# Warnings that should only be visible to superadmin
_SUPERADMIN_ONLY_WARNING_PATTERNS = (
    re.compile(
        r"^Position\s+'.+?'\s+und\s+'.+?'\s+sind\s+als\s+Artikel-Nr\.\s+im\s+PDF\s+ausgewiesen,\s+dürfen\s+laut\s+Regelwerk\s+nicht\s+als\s+artikelnummer[\/\\]modellnummer\s+übernommen\s+werden;\s+daher\s+leer\s+gelassen\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Für\s+Einlegeboden\s+ist\s+nur\s+'.+?'\s+sichtbar;\s+keine\s+eindeutige\s+artikelnummer\s+vorhanden\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Erste\s+Position\s+enthält\s+nur\s+porta-interne\s+Artikel-Nr\.\s+'.+?'\s+und\s+wurde\s+gemäß\s+Regel\s+nicht\s+als\s+artikelnummer[\/\\]modellnummer\s+übernommen\.?$",
        re.IGNORECASE,
    ),
    # Generic patterns for system action warnings (wurde/wurden + action verb + gemäß Regel)
    re.compile(
        r".*wurde\s+(?:entfernt|gelöscht|ignoriert|extrahiert|gesetzt|korrigiert|übernommen).*gemäß\s+Regel.*",
        re.IGNORECASE,
    ),
    re.compile(
        r".*wurden\s+(?:ignoriert|extrahiert|übernommen|entfernt|gelöscht|gesetzt|korrigiert).*gemäß\s+Regel.*",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemäß\s+Regel\s+(?:entfernt|ignoriert|extrahiert|gesetzt|korrigiert|übernommen|gelöscht).*",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemaess\s+Regel\s+(?:entfernt|ignoriert|extrahiert|gesetzt|korrigiert|übernommen|gelöscht).*",
        re.IGNORECASE,
    ),
    re.compile(
        r".*laut\s+Regelwerk\s+(?:entfernt|ignoriert|extrahiert|gesetzt|korrigiert|übernommen|gelöscht).*",
        re.IGNORECASE,
    ),
    # Patterns for rule-based corrections without explicit "gemäß Regel" but describing system actions
    re.compile(
        r".*wurde\s+(?:entfernt|gelöscht|ignoriert|extrahiert|gesetzt|korrigiert).*regel.*",
        re.IGNORECASE,
    ),
    re.compile(
        r".*wurden\s+(?:ignoriert|extrahiert|entfernt|gelöscht|gesetzt|korrigiert).*regel.*",
        re.IGNORECASE,
    ),
    # Specific patterns for known warning formats
    re.compile(
        r"^Artikelcodes\s+in\s+der\s+Tabelle\s+sind.*store-intern\s+und\s+wurden\s+ignoriert.*extrahiert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Mengen\s+für\s+die\s+Zusatzpositionen.*gemäß\s+Regel\s+auf\s+\d+\s+gesetzt\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Mengen\s+für\s+die\s+Zusatzpositionen.*gemaess\s+Regel\s+auf\s+\d+\s+gesetzt\.?$",
        re.IGNORECASE,
    ),
    # Patterns for "auf X gesetzt" (set to X) corrections
    re.compile(
        r".*gemäß\s+Regel\s+auf\s+\d+\s+gesetzt\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemaess\s+Regel\s+auf\s+\d+\s+gesetzt\.?$",
        re.IGNORECASE,
    ),
    # Patterns for extraction actions
    re.compile(
        r".*wurden\s+aus\s+.*\s+extrahiert\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*wurde\s+aus\s+.*\s+extrahiert\.?$",
        re.IGNORECASE,
    ),
    # Patterns for ignored actions
    re.compile(
        r".*wurden\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*wurde\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    # Patterns for PDF extraction method warnings
    re.compile(
        r"^No\s+digital\s+PDF\s+text\s+extracted.*using\s+images\s+only\.?$",
        re.IGNORECASE,
    ),
    # Patterns for image reading warnings
    re.compile(
        r".*wurden\s+aus\s+dem\s+Bild\s+gelesen.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*wurde\s+aus\s+dem\s+Bild\s+gelesen.*$",
        re.IGNORECASE,
    ),
    # Patterns for image merging warnings
    re.compile(
        r".*aus\s+dem\s+Bild\s+zusammengeführt.*$",
        re.IGNORECASE,
    ),
    # Patterns for rule-based splitting
    re.compile(
        r".*gemäß\s+MULTI-ID\s+SPLIT.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemaess\s+MULTI-ID\s+SPLIT.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*wurde.*gemäß.*aufgeteilt.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*wurde.*gemaess.*aufgeteilt.*$",
        re.IGNORECASE,
    ),
    # Patterns for specific rule name patterns
    re.compile(
        r".*gemäß\s+Regel\s+['\"].*?['\"]\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemaess\s+Regel\s+['\"].*?['\"]\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemäß\s+Regel\s+\d+\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemaess\s+Regel\s+\d+\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    # Patterns for found and removed
    re.compile(
        r".*gefunden.*entfernt\.?$",
        re.IGNORECASE,
    ),
    # Pattern for "der Hauptposition...gemäß Regel ignoriert"
    re.compile(
        r".*der\s+Hauptposition.*gemäß\s+Regel.*ignoriert.*daher\s+leer\s+gelassen\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*der\s+Hauptposition.*gemaess\s+Regel.*ignoriert.*daher\s+leer\s+gelassen\.?$",
        re.IGNORECASE,
    ),
    # Pattern for "Artikelcodes stammen aus...Split nach Regel"
    re.compile(
        r"^Artikelcodes\s+stammen\s+aus.*Split\s+nach\s+Regel.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Artikelcodes\s+stammen\s+aus.*Split\s+nach\s+regel.*$",
        re.IGNORECASE,
    ),
    # Pattern for store_name Filialzusatz warning
    re.compile(
        r"^store_name\s+enthält\s+keinen\s+Filialzusatz.*in\s+derselben\s+Zeile.*Filialname\s+separat\s+im\s+PDF\s+vorhanden\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^store_name\s+enthaelt\s+keinen\s+Filialzusatz.*in\s+derselben\s+Zeile.*Filialname\s+separat\s+im\s+PDF\s+vorhanden\.?$",
        re.IGNORECASE,
    ),
    # Patterns for Komponentenblock warnings (component block recognized, main line ignored)
    re.compile(
        r"^Komponentenblock\s+'.+?'\s+erkannt;.*Hauptzeile\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Komponentenblock.*erkannt;.*Hauptzeile\s+ignoriert.*$",
        re.IGNORECASE,
    ),
    # Pattern for "ist eine interne Nummer und wurde nicht als artikelnummer verwendet"
    re.compile(
        r".*ist\s+eine\s+interne\s+Nummer\s+und\s+wurde\s+nicht\s+als\s+artikelnummer\s+verwendet.*$",
        re.IGNORECASE,
    ),
    # Patterns for invalid codes and positions taken without codes
    re.compile(
        r".*enthält\s+keine\s+gültigen\s+Porta.*Position\s+als\s+Menge.*ohne\s+Codes\s+übernommen\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*enthaelt\s+keine\s+gueltigen\s+Porta.*Position\s+als\s+Menge.*ohne\s+Codes\s+uebernommen\.?$",
        re.IGNORECASE,
    ),
    # Patterns for heuristic compaction/compression
    re.compile(
        r".*heuristisch\s+kompaktisiert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*heuristisch\s+komprimiert.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*nicht\s+explizit\s+gelabelt\.?$",
        re.IGNORECASE,
    ),
    # Patterns for furncloud_id not found (variations)
    re.compile(
        r"^Kein\s+furncloud_id\s+im\s+Dokument\s+gefunden\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Keine\s+furncloud_id\s+im\s+Dokument\s+gefunden\.?$",
        re.IGNORECASE,
    ),
    # Patterns for positions without clear table structure and derived quantities
    re.compile(
        r".*Positionen.*erscheinen\s+ohne\s+klare\s+Tabellenstruktur.*Mengen\s+teils\s+abgeleitet\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*Positionen.*erscheinen\s+ohne\s+klare\s+Tabellenstruktur.*quantities\s+partly\s+derived\.?$",
        re.IGNORECASE,
    ),
    # Patterns for extraction from blocks and rule-based field adoption
    re.compile(
        r".*aus\s+.*Block\s+extrahiert.*nicht.*übernommen.*Regel.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*aus\s+.*Block\s+extrahiert.*nicht.*uebernommen.*Regel.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*aus\s+.*Block\s+extrahiert.*nicht.*übernommen.*\(Regel\)\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*aus\s+.*Block\s+extrahiert.*nicht.*uebernommen.*\(Regel\)\.?$",
        re.IGNORECASE,
    ),
    # Pattern for "kundennummer/adressnummer/tour nicht im PDF gefunden" (moved from _HIDDEN_WARNING_PATTERNS)
    re.compile(
        r"\bkundennummer\/adressnummer\/tour\s+nicht\s+im\s+pdf\s+gefunden\b",
        re.IGNORECASE,
    ),
    # Pattern for "kundennummer nicht im PDF gefunden"
    re.compile(
        r"^kundennummer\s+nicht\s+im\s+PDF\s+gefunden\.?$",
        re.IGNORECASE,
    ),
    # Pattern for "No unambiguous article/model number could be identified in the PDF"
    re.compile(
        r"^No\s+unambiguous\s+article[\/\\]model\s+number\s+could\s+be\s+identified\s+in\s+the\s+PDF\.?$",
        re.IGNORECASE,
    ),
    # Pattern for "Positionen enthalten mehrere Code-Zeilen...Menge je Zeile auf X gesetzt"
    re.compile(
        r".*Positionen\s+enthalten\s+mehrere\s+Code-Zeilen.*Menge\s+je\s+Zeile\s+auf\s+\d+\s+gesetzt\.?$",
        re.IGNORECASE,
    ),
    # Pattern for "lieferanschrift ohne Empfängername (nur Adresszeilen) extrahiert"
    re.compile(
        r"^lieferanschrift\s+ohne\s+Empfängername\s+\(nur\s+Adresszeilen\)\s+extrahiert\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^lieferanschrift\s+ohne\s+Empfaengername\s+\(nur\s+Adresszeilen\)\s+extrahiert\.?$",
        re.IGNORECASE,
    ),
    # Patterns for fallback filling
    re.compile(
        r"^Porta:.*filled\s+from.*fallback\.?$",
        re.IGNORECASE,
    ),
    # Patterns for rule-based derivation
    re.compile(
        r".*per\s+Regel\s+\w+\s+abgeleitet.*$",
        re.IGNORECASE,
    ),
    re.compile(
        r".*gemaess\s+Regel\s+\w+\s+abgeleitet.*$",
        re.IGNORECASE,
    ),
    # Patterns for quantity setting for accessory positions
    re.compile(
        r"^Menge\s+für\s+Zubehör.*nicht\s+explizit\s+angegeben.*auf.*gesetzt\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Menge\s+fuer\s+Zubehoer.*nicht\s+explizit\s+angegeben.*auf.*gesetzt\.?$",
        re.IGNORECASE,
    ),
    # Patterns for multiple positions with internal article numbers
    re.compile(
        r"^Mehrere\s+Hauptpositionen.*interne\s+Artikel-Nr\..*laut\s+Regel.*ignorieren.*artikelnummer[\/\\]modellnummer.*leer\s+gelassen\.?$",
        re.IGNORECASE,
    ),
    # Extended "nicht im PDF gefunden" patterns
    re.compile(
        r"^kundennummer\/adressnummer\/kom_name\/tour\/mail_to\s+nicht\s+im\s+PDF\s+gefunden\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^kundennummer.*nicht\s+im\s+PDF\/Email\s+gefunden\.?$",
        re.IGNORECASE,
    ),
    # Patterns for Firmenzeile not adopted per rule
    re.compile(
        r"^Lieferanschrift:\s+Firmenzeile.*gemäß\s+Regel\s+nicht\s+in\s+lieferanschrift\s+übernommen\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Lieferanschrift:\s+Firmenzeile.*gemaess\s+Regel\s+nicht\s+in\s+lieferanschrift\s+uebernommen\.?$",
        re.IGNORECASE,
    ),
    # Patterns for unambiguous candidate not found
    re.compile(
        r"^Kein\s+eindeutiger.*Kandidat.*gefunden\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Keine\s+eindeutige.*Kandidat.*gefunden\.?$",
        re.IGNORECASE,
    ),
)
_PROCESSING_FAILURE_PATTERNS = (
    re.compile(r"\btraceback\b", re.IGNORECASE),
    re.compile(r"\bexception\b", re.IGNORECASE),
    re.compile(r"\b(?:database|db|sql|psycopg|postgres)\b", re.IGNORECASE),
    re.compile(r"\b(?:extract(?:ion)?|convert(?:ed|ing|ion)?|parse|decode|serialize)\b", re.IGNORECASE),
    re.compile(r"\b(?:failed|failure|crash(?:ed)?|timeout)\b", re.IGNORECASE),
    re.compile(r"\b(?:valueerror|typeerror|keyerror|attributeerror|indexerror|syntaxerror)\b", re.IGNORECASE),
)
_TECHNICAL_SIGNAL_PATTERNS = _PROCESSING_FAILURE_PATTERNS + (
    re.compile(r'file "[^"]+"', re.IGNORECASE),
    re.compile(r"\bline \d+\b", re.IGNORECASE),
    re.compile(r"\b(?:table|column|relation|constraint|endpoint|router|service|provider)\b", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\", re.IGNORECASE),
    re.compile(r"/[\w./-]+\.(?:py|js|ts|json|xml|sql)", re.IGNORECASE),
)
_INTERNAL_HEADER_FIELDS = frozenset(
    {
        "human_review_needed",
        "iln",
        "iln_anl",
        "iln_fil",
        "post_case",
        "reply_needed",
        "seller",
    }
)
_FRIENDLY_WARNING_FALLBACK = "Some order information needs review."
_FRIENDLY_ERROR_FALLBACK = "We could not fully process part of this order automatically. Please review it manually."
_FRIENDLY_PORTA_INTERNAL_REFERENCE = (
    "The PDF code '{value}' is an internal store reference and cannot be used as the product article/model number."
)
_FRIENDLY_PORTA_AMBIGUOUS_CODES = "The PDF contains ambiguous item codes. Please confirm the correct item codes."


def _normalize_detail_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role in {"user", "admin", "superadmin"}:
        return role
    return "user"


def _coerce_signal_messages(messages: Any) -> list[str]:
    if not isinstance(messages, list):
        return []
    return [str(item) for item in messages]


def _is_actionable_operational_signal(message: str) -> bool:
    normalized = message.strip()
    if not normalized:
        return False
    if any(pattern.search(normalized) for pattern in _ACTIONABLE_SIGNAL_PATTERNS):
        return True
    lowered = normalized.lower()
    if "line " in lowered and any(token in lowered for token in ("missing", "empty", "incomplete", "not provided")):
        return True
    return False


def _looks_technical_operational_signal(message: str) -> bool:
    normalized = message.strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _TECHNICAL_SIGNAL_PATTERNS)


def _friendly_operational_signal(level: str) -> str:
    if str(level or "").strip().lower() == "error":
        return _FRIENDLY_ERROR_FALLBACK
    return _FRIENDLY_WARNING_FALLBACK


def _sanitize_missing_header_signal(message: str) -> str | None:
    patterns = (
        re.compile(r"^(Missing header fields:\s*)(.+)$", re.IGNORECASE),
        re.compile(r"^(Missing critical header fields:\s*)(.+)$", re.IGNORECASE),
        re.compile(r"^(Reply needed:\s*Missing critical header fields:\s*)(.+)$", re.IGNORECASE),
    )
    for pattern in patterns:
        match = pattern.match(message.strip())
        if not match:
            continue
        prefix, raw_fields = match.groups()
        visible_fields = [
            token.strip()
            for token in raw_fields.split(",")
            if token.strip() and token.strip().lower() not in _INTERNAL_HEADER_FIELDS
        ]
        if not visible_fields:
            return None
        return f"{prefix}{', '.join(visible_fields)}"
    return message


def _rewrite_client_warning(message: str) -> str | None:
    lowered = message.lower()
    if lowered.startswith("artikel-nr."):
        if "porta-interne artikelnummer" in lowered and "artikelnummer/modellnummer" in lowered:
            return None
        if "tabellen-spalte" in lowered and "ignoriert" in lowered and "liefermodelltext" in lowered:
            return None
    if lowered.startswith("article no.") and "porta internal article number" in lowered:
        return None

    internal_article_patterns = (
        re.compile(
            r"^Artikel-Nr\.\s*'(.+?)'\s*ist als porta-interne Artikelnummer gekennzeichnet und wurde "
            r"(?:gemaess|gemäß) Regel nicht als artikelnummer\/modellnummer (?:uebernommen|übernommen)\.?$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^Article no\.\s*'(.+?)'\s*is marked as a Porta internal article number and was not copied "
            r"into the article\/model number fields per rule\.?$",
            re.IGNORECASE,
        ),
    )
    for pattern in internal_article_patterns:
        match = pattern.match(message)
        if match:
            return _FRIENDLY_PORTA_INTERNAL_REFERENCE.format(value=match.group(1))

    flagged_match = re.match(
        r"^Human review needed:\s*Porta ambiguous standalone code token\(s\) retained "
        r"for human confirmation;\s*please confirm valid item codes\.\s*Flagged:\s*(.+)$",
        message,
        re.IGNORECASE,
    )
    if flagged_match:
        flagged = str(flagged_match.group(1) or "").strip().rstrip(".")
        return f"{_FRIENDLY_PORTA_AMBIGUOUS_CODES} Flagged: {flagged}"

    ignored_match = re.match(
        r"^Human review needed:\s*Porta ambiguous standalone code token\(s\) were ignored;\s*please confirm valid item codes\.?$",
        message,
        re.IGNORECASE,
    )
    if ignored_match:
        return _FRIENDLY_PORTA_AMBIGUOUS_CODES

    return None


def _sanitize_operational_signal(message: str, *, level: str, role: str | None = None) -> str | None:
    normalized = message.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if "header fields:" in lowered:
        normalized = _sanitize_missing_header_signal(normalized)
        if normalized is None:
            return None
        lowered = normalized.lower()
    if str(level or "").strip().lower() == "warning":
        rewritten = _rewrite_client_warning(normalized)
        if rewritten is not None:
            return rewritten
    if _is_actionable_operational_signal(normalized):
        return normalized
    if str(level or "").strip().lower() == "warning":
        # Hide superadmin-only warnings for non-superadmin users
        normalized_role = _normalize_detail_role(role)
        if normalized_role != "superadmin":
            if any(pattern.search(normalized) for pattern in _SUPERADMIN_ONLY_WARNING_PATTERNS):
                return None
        if any(pattern.search(normalized) for pattern in _HIDDEN_WARNING_PATTERNS):
            return None
        if _looks_technical_operational_signal(normalized):
            return None
    if any(pattern.search(normalized) for pattern in _PROCESSING_FAILURE_PATTERNS):
        return _FRIENDLY_ERROR_FALLBACK
    if _looks_technical_operational_signal(normalized):
        return _friendly_operational_signal(level)
    return normalized


def sanitize_operational_signal_messages(messages: Any, *, level: str, role: str | None) -> list[str]:
    raw_messages = _coerce_signal_messages(messages)
    normalized_role = _normalize_detail_role(role)
    if normalized_role == "superadmin":
        return raw_messages
    sanitized: list[str] = []
    seen: set[str] = set()
    for message in raw_messages:
        safe_message = _sanitize_operational_signal(message, level=level, role=role)
        if safe_message is not None and safe_message not in seen:
            sanitized.append(safe_message)
            seen.add(safe_message)
    # Additional deduplication: remove duplicate furncloud ID warnings
    # Check for both "Furncloud ID is missing" and "furncloud_id is missing" variations
    furncloud_patterns = [
        "furncloud id is missing for one or more items",
        "furncloud_id is missing for one or more items",
    ]
    furncloud_found = False
    result: list[str] = []
    for msg in sanitized:
        msg_lower = msg.lower().strip()
        is_furncloud_warning = any(pattern in msg_lower for pattern in furncloud_patterns)
        if is_furncloud_warning:
            if not furncloud_found:
                result.append(msg)
                furncloud_found = True
        else:
            result.append(msg)
    return result


def _default_validation_projection() -> dict[str, Any]:
    return {
        "validation_status": VALIDATION_STATUS_NOT_RUN,
        "validation_summary": "",
        "validation_checked_at": None,
        "validation_provider": "",
        "validation_model": "",
        "validation_stale_reason": "",
    }


def _existing_validation_projection(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return _default_validation_projection()
    return {
        "validation_status": normalize_validation_status(row.get("validation_status")),
        "validation_summary": str(row.get("validation_summary") or ""),
        "validation_checked_at": row.get("validation_checked_at"),
        "validation_provider": str(row.get("validation_provider") or ""),
        "validation_model": str(row.get("validation_model") or ""),
        "validation_stale_reason": str(row.get("validation_stale_reason") or ""),
    }


def _normalize_validation_result_payload(validation_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(validation_result, dict):
        projection = _default_validation_projection()
        projection["validation_issues"] = []
        projection["validation_raw_result"] = {}
        return projection

    raw_result = validation_result.get("validation_raw_result")
    projection = {
        "validation_status": normalize_validation_status(validation_result.get("validation_status")),
        "validation_summary": str(validation_result.get("validation_summary") or "").strip(),
        "validation_checked_at": _parse_iso(validation_result.get("validation_checked_at")),
        "validation_provider": str(validation_result.get("validation_provider") or ""),
        "validation_model": str(validation_result.get("validation_model") or ""),
        "validation_stale_reason": str(validation_result.get("validation_stale_reason") or ""),
        "validation_issues": _normalize_validation_issues(validation_result.get("validation_issues")),
        "validation_raw_result": raw_result if isinstance(raw_result, dict) else {},
    }
    if projection["validation_status"] not in VALID_VALIDATION_STATUSES:
        projection["validation_status"] = VALIDATION_STATUS_NOT_RUN
    return projection


def validation_status_needs_review(value: Any) -> bool:
    return normalize_validation_status(value) in VALIDATION_REVIEW_STATUSES


def _normalize_branch_set(branches: set[str] | None) -> list[str] | None:
    if branches is None:
        return None
    normalized = sorted({_normalize_extraction_branch(branch) for branch in branches})
    return normalized


def _scope_where_fragments(
    *,
    assigned_user_id: str | None,
    allowed_client_branches: set[str] | None,
) -> tuple[list[str], list[Any]]:
    scope_clauses: list[str] = []
    scope_params: list[Any] = []

    if assigned_user_id:
        scope_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM order_review_tasks t_scope
                WHERE t_scope.order_id = o.id
                  AND t_scope.state NOT IN ('resolved', 'cancelled')
                  AND t_scope.assigned_user_id = %s
            )
            """
        )
        scope_params.append(assigned_user_id)

    normalized_allowed = _normalize_branch_set(allowed_client_branches)
    if normalized_allowed is not None:
        if not normalized_allowed:
            scope_clauses.append("1 = 0")
        else:
            scope_clauses.append(f"{_EXTRACTION_BRANCH_SQL} = ANY(%s)")
            scope_params.append(normalized_allowed)

    return scope_clauses, scope_params


def normalize_status(value: Any) -> str:
    status = str(value or STATUS_OK).strip().lower()
    if status == STATUS_PARTIAL or status == "reply":
        return STATUS_WAITING_REPLY
    if status not in VALID_STATUSES:
        return STATUS_OK
    return status


def derive_status(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return STATUS_FAILED
    header = payload.get("header")
    items = payload.get("items")
    if not isinstance(header, dict) or not isinstance(items, list):
        return STATUS_FAILED
    if _entry_bool(header.get("post_case")):
        return STATUS_POST
    if _entry_bool(header.get("reply_needed")):
        return STATUS_WAITING_REPLY
    if _entry_bool(header.get("human_review_needed")):
        return STATUS_HUMAN
    legacy = normalize_status(payload.get("status"))
    if legacy in {STATUS_WAITING_REPLY, STATUS_HUMAN, STATUS_POST}:
        return legacy
    return STATUS_OK


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = dict(payload or {})
    if not isinstance(normalized.get("header"), dict):
        normalized["header"] = {}
    if not isinstance(normalized.get("items"), list):
        normalized["items"] = []
    if not isinstance(normalized.get("warnings"), list):
        normalized["warnings"] = [] if normalized.get("warnings") in (None, "") else [str(normalized["warnings"])]
    if not isinstance(normalized.get("errors"), list):
        normalized["errors"] = [] if normalized.get("errors") in (None, "") else [str(normalized["errors"])]
    normalized["warnings"] = [str(item) for item in normalized.get("warnings", [])]
    normalized["errors"] = [str(item) for item in normalized.get("errors", [])]
    normalized["extraction_branch"] = _normalize_extraction_branch(normalized.get("extraction_branch"))
    normalized["status"] = derive_status(normalized)
    return normalized


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")


def _dedupe_key(message_id: str) -> str:
    token = str(message_id or "").strip().lower()
    if token.startswith("<") and token.endswith(">"):
        token = token[1:-1]
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _projection(payload: dict[str, Any], parse_error: str | None) -> dict[str, Any]:
    header = payload.get("header", {})
    warnings = payload.get("warnings", [])
    errors = payload.get("errors", [])
    items = payload.get("items", [])
    return {
        "received_at": _parse_iso(payload.get("received_at")),
        "status": derive_status(payload),
        "reply_needed": _entry_bool(header.get("reply_needed")),
        "human_review_needed": _entry_bool(header.get("human_review_needed")),
        "post_case": _entry_bool(header.get("post_case")),
        "ticket_number": _entry_text(header.get("ticket_number")),
        "kundennummer": _entry_text(header.get("kundennummer")),
        "kom_nr": _entry_text(header.get("kom_nr")),
        "kom_name": _entry_text(header.get("kom_name")),
        "liefertermin": _entry_text(header.get("liefertermin")),
        "wunschtermin": _entry_text(header.get("wunschtermin")),
        "delivery_week": _entry_text(header.get("delivery_week")),
        "store_name": _entry_text(header.get("store_name")),
        "store_address": _entry_text(header.get("store_address")),
        "iln": _entry_text(header.get("iln")),
        "mail_to": _entry_text(header.get("mail_to")),
        "extraction_branch": _normalize_extraction_branch(payload.get("extraction_branch")),
        "item_count": len(items),
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "parse_error": str(parse_error or "").strip() or None,
    }


def _ensure_task(conn, *, order_id: str, status: str, actor_user_id: str | None) -> None:
    now = _now()
    with conn.cursor() as cursor:
        if status not in REVIEWABLE_STATUSES:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET state = 'resolved',
                    resolved_at = COALESCE(resolved_at, %s),
                    resolution_outcome = COALESCE(resolution_outcome, 'auto_ok'),
                    resolution_note = COALESCE(resolution_note, 'Auto-resolved after status transition'),
                    claim_expires_at = NULL,
                    updated_at = %s
                WHERE order_id = %s
                  AND state NOT IN ('resolved', 'cancelled')
                """,
                (now, now, order_id),
            )
            return

        cursor.execute(
            """
            SELECT id, assigned_user_id, claim_expires_at
            FROM order_review_tasks
            WHERE order_id = %s
              AND state NOT IN ('resolved', 'cancelled')
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (order_id,),
        )
        current = cursor.fetchone()
        if current:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET task_type = %s,
                    state = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN 'queued'
                        WHEN assigned_user_id IS NULL THEN 'queued'
                        ELSE state
                    END,
                    assigned_user_id = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN NULL
                        ELSE assigned_user_id
                    END,
                    claimed_at = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN NULL
                        ELSE claimed_at
                    END,
                    claim_expires_at = CASE
                        WHEN claim_expires_at IS NOT NULL AND claim_expires_at <= %s THEN NULL
                        ELSE claim_expires_at
                    END,
                    due_at = COALESCE(due_at, %s),
                    updated_at = %s
                WHERE id = %s
                """,
                (status, now, now, now, now, now + timedelta(hours=24), now, current["id"]),
            )
            return

        cursor.execute(
            """
            INSERT INTO order_review_tasks (
                id, order_id, task_type, state, priority, due_at, created_at, updated_at
            )
            VALUES (%s, %s, %s, 'queued', 5, %s, %s, %s)
            """,
            (str(uuid.uuid4()), order_id, status, now + timedelta(hours=24), now, now),
        )
        cursor.execute(
            """
            INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
            VALUES (%s, NULL, 'review_task_created', %s, %s, %s::jsonb, %s)
            """,
            (order_id, "user" if actor_user_id else "system", actor_user_id, _jsonb({"task_type": status}), now),
        )


def _replace_messages(conn, *, order_id: str, revision_id: str, warnings: list[str], errors: list[str]) -> None:
    now = _now()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE order_messages SET is_active = FALSE WHERE order_id = %s AND is_active = TRUE", (order_id,))
        for message in warnings:
            cursor.execute(
                """
                INSERT INTO order_messages (id, order_id, revision_id, level, message, is_active, created_at)
                VALUES (%s, %s, %s, 'warning', %s, TRUE, %s)
                """,
                (str(uuid.uuid4()), order_id, revision_id, str(message), now),
            )
        for message in errors:
            cursor.execute(
                """
                INSERT INTO order_messages (id, order_id, revision_id, level, message, is_active, created_at)
                VALUES (%s, %s, %s, 'error', %s, TRUE, %s)
                """,
                (str(uuid.uuid4()), order_id, revision_id, str(message), now),
            )


def _replace_items(conn, *, order_id: str, items: list[Any]) -> None:
    now = _now()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM order_items_current WHERE order_id = %s", (order_id,))
        for idx, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                continue
            line_no = raw.get("line_no")
            try:
                line_no = int(line_no)
            except (TypeError, ValueError):
                line_no = idx
            menge_raw = _entry_value(raw.get("menge"))
            menge_value = None
            if menge_raw not in (None, ""):
                try:
                    menge_value = float(str(menge_raw).replace(",", "."))
                except ValueError:
                    menge_value = None
            field_meta = {
                key: raw.get(key)
                for key in ("artikelnummer", "modellnummer", "menge", "furncloud_id")
                if isinstance(raw.get(key), dict)
            }
            cursor.execute(
                """
                INSERT INTO order_items_current (
                    id, order_id, line_no, artikelnummer, modellnummer, menge, furncloud_id, field_meta, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    str(uuid.uuid4()),
                    order_id,
                    line_no,
                    _entry_text(raw.get("artikelnummer")),
                    _entry_text(raw.get("modellnummer")),
                    menge_value,
                    _entry_text(raw.get("furncloud_id")),
                    _jsonb(field_meta),
                    now,
                ),
            )


def _upsert_revision(
    conn,
    *,
    payload: dict[str, Any],
    external_message_id: str,
    change_type: str,
    changed_by_user_id: str | None,
    parse_error: str | None,
    diff_json: dict[str, Any] | None,
    validation_result: dict[str, Any] | None,
) -> dict[str, Any]:
    now = _now()
    projection = _projection(payload, parse_error)
    dedupe_key = _dedupe_key(external_message_id)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id,
                   current_revision_no,
                   validation_status,
                   validation_summary,
                   validation_checked_at,
                   validation_provider,
                   validation_model,
                   validation_stale_reason
            FROM orders
            WHERE dedupe_key = %s
            FOR UPDATE
            """,
            (dedupe_key,),
        )
        existing = cursor.fetchone()
        if existing:
            order_id = str(existing["id"])
            revision_no = int(existing.get("current_revision_no") or 0) + 1
        else:
            order_id = str(uuid.uuid4())
            revision_no = 1
            cursor.execute(
                """
                INSERT INTO orders (id, external_message_id, dedupe_key, current_revision_no, created_at, updated_at)
                VALUES (%s, %s, %s, 0, %s, %s)
                """,
                (order_id, external_message_id, dedupe_key, now, now),
            )
            cursor.execute(
                "INSERT INTO order_px_controls (order_id) VALUES (%s) ON CONFLICT (order_id) DO NOTHING",
                (order_id,),
            )

        validation_projection = (
            _normalize_validation_result_payload(validation_result)
            if validation_result is not None
            else _existing_validation_projection(existing)
        )
        revision_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO order_revisions (
                id, order_id, revision_no, change_type, changed_by_user_id, payload_json, diff_json, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            """,
            (
                revision_id,
                order_id,
                revision_no,
                change_type,
                changed_by_user_id,
                _jsonb(payload),
                _jsonb(diff_json),
                now,
            ),
        )
        cursor.execute(
            """
            UPDATE orders
            SET external_message_id = %s,
                received_at = %s,
                status = %s,
                reply_needed = %s,
                human_review_needed = %s,
                post_case = %s,
                ticket_number = %s,
                kundennummer = %s,
                kom_nr = %s,
                kom_name = %s,
                liefertermin = %s,
                wunschtermin = %s,
                delivery_week = %s,
                store_name = %s,
                store_address = %s,
                iln = %s,
                mail_to = %s,
                extraction_branch = %s,
                item_count = %s,
                warnings_count = %s,
                errors_count = %s,
                validation_status = %s,
                validation_summary = %s,
                validation_checked_at = %s,
                validation_provider = %s,
                validation_model = %s,
                validation_stale_reason = %s,
                parse_error = %s,
                current_revision_id = %s,
                current_revision_no = %s,
                updated_at = %s
            WHERE id = %s
              AND deleted_at IS NULL
            """,
            (
                external_message_id,
                projection["received_at"],
                projection["status"],
                projection["reply_needed"],
                projection["human_review_needed"],
                projection["post_case"],
                projection["ticket_number"],
                projection["kundennummer"],
                projection["kom_nr"],
                projection["kom_name"],
                projection["liefertermin"],
                projection["wunschtermin"],
                projection["delivery_week"],
                projection["store_name"],
                projection["store_address"],
                projection["iln"],
                projection["mail_to"],
                projection["extraction_branch"],
                projection["item_count"],
                projection["warnings_count"],
                projection["errors_count"],
                validation_projection["validation_status"],
                validation_projection["validation_summary"],
                validation_projection["validation_checked_at"],
                validation_projection["validation_provider"],
                validation_projection["validation_model"],
                validation_projection["validation_stale_reason"],
                projection["parse_error"],
                revision_id,
                revision_no,
                now,
                order_id,
            ),
        )
        cursor.execute(
            """
            INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                order_id,
                revision_id,
                f"order_{change_type}",
                "user" if changed_by_user_id else "system",
                changed_by_user_id,
                _jsonb({"status": projection["status"]}),
                now,
            ),
        )
    _replace_messages(
        conn,
        order_id=order_id,
        revision_id=revision_id,
        warnings=payload.get("warnings", []),
        errors=payload.get("errors", []),
    )
    _replace_items(conn, order_id=order_id, items=payload.get("items", []))
    _ensure_task(conn, order_id=order_id, status=projection["status"], actor_user_id=changed_by_user_id)
    return {
        "order_id": order_id,
        "revision_id": revision_id,
        "revision_no": revision_no,
        "status": projection["status"],
    }


def upsert_order_payload(
    payload: dict[str, Any],
    *,
    external_message_id: str | None = None,
    change_type: str = "ingested",
    changed_by_user_id: str | None = None,
    parse_error: str | None = None,
    diff_json: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_payload(payload)
    message_id = str(external_message_id or normalized.get("message_id") or uuid.uuid4())
    with get_connection() as conn:
        result = _upsert_revision(
            conn,
            payload=normalized,
            external_message_id=message_id,
            change_type=change_type,
            changed_by_user_id=changed_by_user_id,
            parse_error=parse_error,
            diff_json=diff_json,
            validation_result=validation_result,
        )
        conn.commit()
    return result


def mark_reply_email_sent(order_id: str, missing_fields: list[str]) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET reply_email_sent_at = %s,
                    waiting_for_client_reply = TRUE,
                    missing_fields_snapshot = %s,
                    status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (now, missing_fields, STATUS_WAITING_REPLY, now, order_id),
            )
        conn.commit()


def find_reply_needed_order_by_kom(kom_number: str) -> dict[str, Any] | None:
    """Find an order that is awaiting or recently received a client reply, by KOM/ticket number.

    Looks back up to 14 days to also catch orders where the first reply was already
    processed (client_replied / updated_after_reply) so that follow-up emails can still
    be merged into the original order instead of creating a new one.
    """
    row = fetch_one(
        """
        SELECT id, status, missing_fields_snapshot, external_message_id
        FROM orders
        WHERE (
            waiting_for_client_reply = TRUE
            OR reply_needed = TRUE
            OR status IN ('waiting_for_reply', 'client_replied', 'updated_after_reply')
        )
          AND (kom_nr = %s OR ticket_number = %s)
          AND deleted_at IS NULL
          AND updated_at >= NOW() - INTERVAL '30 days'
        ORDER BY received_at DESC
        LIMIT 1
        """,
        (kom_number, kom_number),
    )
    return dict(row) if row else None


def find_order_awaiting_reply_by_kom(kom_number: str) -> dict[str, Any] | None:
    """Find an order awaiting or recently received a client reply, by KOM/ticket number.

    Like find_reply_needed_order_by_kom but used specifically for the Re: email path.
    Also covers recently-processed orders within 14 days so repeated replies work.
    """
    row = fetch_one(
        """
        SELECT id, status, missing_fields_snapshot, external_message_id
        FROM orders
        WHERE (
            waiting_for_client_reply = TRUE
            OR status IN ('waiting_for_reply', 'client_replied', 'updated_after_reply')
        )
          AND (kom_nr = %s OR ticket_number = %s)
          AND deleted_at IS NULL
          AND updated_at >= NOW() - INTERVAL '30 days'
        ORDER BY received_at DESC
        LIMIT 1
        """,
        (kom_number, kom_number),
    )
    return dict(row) if row else None


def reopen_waiting_for_reply(order_id: str, missing_fields: list[str]) -> None:
    """Re-mark an order as waiting for client reply after a partial follow-up.

    Called when a follow-up email was processed but some fields are still missing.
    Updates the missing_fields_snapshot without touching reply_email_sent_at.
    """
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET waiting_for_client_reply = TRUE,
                    missing_fields_snapshot = %s,
                    status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (missing_fields, STATUS_WAITING_REPLY, now, order_id),
            )
        conn.commit()


def get_order_current_payload(order_id: str) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT r.payload_json
        FROM order_revisions r
        WHERE r.order_id = %s
        ORDER BY r.revision_no DESC
        LIMIT 1
        """,
        (order_id,),
    )
    if not row:
        return None
    payload = row.get("payload_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return payload if isinstance(payload, dict) else {}


def mark_client_replied(order_id: str, reply_message_id: str) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET waiting_for_client_reply = FALSE,
                    client_replied_at = %s,
                    client_reply_message_id = %s,
                    status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (now, reply_message_id, STATUS_CLIENT_REPLIED, now, order_id),
            )
        conn.commit()


def mark_order_updated_after_reply(order_id: str) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (STATUS_UPDATED_AFTER_REPLY, now, order_id),
            )
        conn.commit()


def get_stale_waiting_orders(cutoff_dt: datetime) -> list[dict[str, Any]]:
    """Return orders waiting_for_client_reply where reply_email_sent_at < cutoff_dt."""
    rows = fetch_all(
        """
        SELECT id, kom_nr, reply_email_sent_at
        FROM orders
        WHERE status = %s
          AND waiting_for_client_reply = TRUE
          AND reply_email_sent_at IS NOT NULL
          AND reply_email_sent_at < %s
          AND deleted_at IS NULL
        ORDER BY reply_email_sent_at ASC
        """,
        (STATUS_WAITING_REPLY, cutoff_dt),
    )
    return [dict(row) for row in rows]


def mark_order_escalated(order_id: str) -> None:
    """Set status=human_in_the_loop, clear waiting_for_client_reply."""
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET status = %s,
                    waiting_for_client_reply = FALSE,
                    updated_at = %s
                WHERE id = %s
                """,
                (STATUS_HUMAN, now, order_id),
            )
        conn.commit()


def list_order_summaries() -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT o.id,
               o.external_message_id,
               o.received_at,
               o.status,
               o.item_count,
               o.warnings_count,
               o.errors_count,
               o.ticket_number,
               o.kundennummer,
               o.kom_nr,
               o.kom_name,
               o.liefertermin,
               o.wunschtermin,
               o.delivery_week,
               o.store_name,
               o.store_address,
               o.iln,
               o.mail_to,
               o.extraction_branch,
               o.reply_needed,
               o.human_review_needed,
               o.post_case,
               o.validation_status,
               o.validation_summary,
               o.validation_checked_at,
               o.validation_provider,
               o.validation_model,
               o.validation_stale_reason,
               o.parse_error,
               o.updated_at AS mtime
        FROM orders o
        WHERE o.deleted_at IS NULL
        ORDER BY COALESCE(o.received_at, o.updated_at) DESC
        """
    )
    return [_summary_row_to_order(row, status_field="status", branch_field="extraction_branch") for row in rows]


def _summary_row_to_order(
    row: dict[str, Any],
    *,
    status_field: str = "status",
    branch_field: str = "extraction_branch",
) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "file_name": str(row["id"]),
        "message_id": row.get("external_message_id") or str(row["id"]),
        "received_at": _to_iso(row.get("received_at")),
        "status": normalize_status(row.get(status_field)),
        "item_count": int(row.get("item_count") or 0),
        "warnings_count": int(row.get("warnings_count") or 0),
        "errors_count": int(row.get("errors_count") or 0),
        "warnings": [],
        "errors": [],
        "ticket_number": row.get("ticket_number") or "",
        "kundennummer": row.get("kundennummer") or "",
        "kom_nr": row.get("kom_nr") or "",
        "kom_name": row.get("kom_name") or "",
        "liefertermin": row.get("liefertermin") or "",
        "wunschtermin": row.get("wunschtermin") or "",
        "delivery_week": row.get("delivery_week") or "",
        "store_name": row.get("store_name") or "",
        "store_address": row.get("store_address") or "",
        "iln": row.get("iln") or "",
        "mail_to": row.get("mail_to") or "",
        "extraction_branch": _normalize_extraction_branch(row.get(branch_field)),
        "human_review_needed": bool(row.get("human_review_needed")),
        "reply_needed": bool(row.get("reply_needed")),
        "post_case": bool(row.get("post_case")),
        "validation_status": normalize_validation_status(row.get("validation_status")),
        "validation_summary": row.get("validation_summary") or "",
        "validation_checked_at": _to_iso(row.get("validation_checked_at")) if row.get("validation_checked_at") else "",
        "validation_provider": row.get("validation_provider") or "",
        "validation_model": row.get("validation_model") or "",
        "validation_stale_reason": row.get("validation_stale_reason") or "",
        "reply_mailto": "",
        "parse_error": row.get("parse_error"),
        "mtime": row.get("mtime"),
    }


def _build_orders_where_clause(
    *,
    q: str,
    received_from: datetime | None,
    received_to: datetime | None,
    statuses: set[str] | None,
    reply_needed: bool | None,
    human_review_needed: bool | None,
    post_case: bool | None,
    validation_statuses: set[str] | None,
    client_branches: set[str] | None,
    delivery_week: str | None,
    assigned_user_id: str | None,
    allowed_client_branches: set[str] | None,
) -> tuple[str, list[Any]]:
    clauses = ["o.deleted_at IS NULL"]
    params: list[Any] = []

    query = str(q or "").strip()
    if query:
        like = f"%{query}%"
        clauses.append(
            """
            (
                o.ticket_number ILIKE %s
                OR o.kom_nr ILIKE %s
                OR o.kom_name ILIKE %s
                OR o.external_message_id ILIKE %s
                OR CAST(o.id AS TEXT) ILIKE %s
            )
            """
        )
        params.extend([like, like, like, like, like])

    if received_from is not None:
        clauses.append(f"{_EFFECTIVE_RECEIVED_SQL} >= %s")
        params.append(received_from)

    if received_to is not None:
        clauses.append(f"{_EFFECTIVE_RECEIVED_SQL} < %s")
        params.append(received_to)

    if statuses:
        normalized_statuses = sorted({normalize_status(status) for status in statuses})
        clauses.append(f"{_STATUS_SQL} = ANY(%s)")
        params.append(normalized_statuses)

    if reply_needed is not None:
        clauses.append("o.reply_needed = %s")
        params.append(bool(reply_needed))

    if human_review_needed is not None:
        clauses.append("o.human_review_needed = %s")
        params.append(bool(human_review_needed))

    if post_case is not None:
        clauses.append("o.post_case = %s")
        params.append(bool(post_case))

    if validation_statuses:
        normalized_validation_statuses = sorted(
            {normalize_validation_status(status) for status in validation_statuses}
        )
        clauses.append("o.validation_status = ANY(%s)")
        params.append(normalized_validation_statuses)

    normalized_branches = _normalize_branch_set(client_branches)
    if normalized_branches:
        clauses.append(f"{_EXTRACTION_BRANCH_SQL} = ANY(%s)")
        params.append(normalized_branches)

    normalized_delivery_week = str(delivery_week or "").strip()
    if normalized_delivery_week:
        clauses.append("o.delivery_week = %s")
        params.append(normalized_delivery_week)

    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    clauses.extend(scope_clauses)
    params.extend(scope_params)

    return " AND ".join(clauses), params


def query_order_summaries(
    *,
    q: str,
    received_from: datetime | None,
    received_to: datetime | None,
    counts_received_from: datetime | None,
    counts_received_to: datetime | None,
    statuses: set[str] | None,
    reply_needed: bool | None,
    human_review_needed: bool | None,
    post_case: bool | None,
    validation_statuses: set[str] | None,
    client_branches: set[str] | None,
    delivery_week: str | None,
    assigned_user_id: str | None,
    allowed_client_branches: set[str] | None,
    sort_key: str,
    page: int,
    page_size: int,
    paginate: bool,
    today_start: datetime,
    today_end: datetime,
    counts_override: dict[str, int] | None = None,
) -> dict[str, Any]:
    where_sql, where_params = _build_orders_where_clause(
        q=q,
        received_from=received_from,
        received_to=received_to,
        statuses=statuses,
        reply_needed=reply_needed,
        human_review_needed=human_review_needed,
        post_case=post_case,
        validation_statuses=validation_statuses,
        client_branches=client_branches,
        delivery_week=delivery_week,
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    counts_where_sql, counts_where_params = _build_orders_where_clause(
        q=q,
        received_from=counts_received_from,
        received_to=counts_received_to,
        statuses=None,
        reply_needed=reply_needed,
        human_review_needed=human_review_needed,
        post_case=post_case,
        validation_statuses=None,
        client_branches=client_branches,
        delivery_week=delivery_week,
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    order_direction = "ASC" if sort_key == "received_at_asc" else "DESC"

    counts_payload: dict[str, int]
    if counts_override is not None:
        counts_payload = {
            "total": int(counts_override.get("total") or 0),
            "today": int(counts_override.get("today") or 0),
            "waiting_for_reply": int(counts_override.get("waiting_for_reply") or 0),
            "manual_review": int(counts_override.get("manual_review") or 0),
            "gemini_review": int(counts_override.get("gemini_review") or 0),
            "status_ok": int(counts_override.get("status_ok") or 0),
            "status_waiting_for_reply": int(counts_override.get("status_waiting_for_reply") or 0),
            "status_human_in_the_loop": int(counts_override.get("status_human_in_the_loop") or 0),
            "status_post": int(counts_override.get("status_post") or 0),
            "status_failed": int(counts_override.get("status_failed") or 0),
            "status_unknown": int(counts_override.get("status_unknown") or 0),
            "status_updated_after_reply": int(counts_override.get("status_updated_after_reply") or 0),
        }
    else:
        counts_row = fetch_one(
            f"""
            SELECT COUNT(*)::bigint AS total,
                   SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s THEN 1 ELSE 0 END)::bigint AS today,
                   SUM(CASE WHEN {_STATUS_SQL} = 'waiting_for_reply' THEN 1 ELSE 0 END)::bigint AS waiting_for_reply,
                   SUM(CASE WHEN {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS manual_review,
                   SUM(CASE WHEN o.validation_status IN ('flagged', 'stale') THEN 1 ELSE 0 END)::bigint AS gemini_review,
                   SUM(CASE WHEN {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS status_ok,
                   SUM(CASE WHEN {_STATUS_SQL} = 'waiting_for_reply' THEN 1 ELSE 0 END)::bigint AS status_waiting_for_reply,
                   SUM(CASE WHEN {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS status_human_in_the_loop,
                   SUM(CASE WHEN {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS status_post,
                   SUM(CASE WHEN {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS status_failed,
                   SUM(CASE WHEN {_STATUS_SQL} = 'unknown' THEN 1 ELSE 0 END)::bigint AS status_unknown,
                   SUM(CASE WHEN {_STATUS_SQL} = 'updated_after_reply' THEN 1 ELSE 0 END)::bigint AS status_updated_after_reply
            FROM orders o
            WHERE {counts_where_sql}
            """,
            [today_start, today_end, *counts_where_params],
        ) or {}
        counts_payload = {
            "total": int(counts_row.get("total") or 0),
            "today": int(counts_row.get("today") or 0),
            "waiting_for_reply": int(counts_row.get("waiting_for_reply") or 0),
            "manual_review": int(counts_row.get("manual_review") or 0),
            "gemini_review": int(counts_row.get("gemini_review") or 0),
            "status_ok": int(counts_row.get("status_ok") or 0),
            "status_waiting_for_reply": int(counts_row.get("status_waiting_for_reply") or 0),
            "status_human_in_the_loop": int(counts_row.get("status_human_in_the_loop") or 0),
            "status_post": int(counts_row.get("status_post") or 0),
            "status_failed": int(counts_row.get("status_failed") or 0),
            "status_unknown": int(counts_row.get("status_unknown") or 0),
            "status_updated_after_reply": int(counts_row.get("status_updated_after_reply") or 0),
        }

    total = counts_payload["total"]
    if paginate:
        effective_page_size = max(1, page_size)
        total_pages = max(1, (total + effective_page_size - 1) // effective_page_size)
        effective_page = min(max(1, page), total_pages)
    else:
        effective_page_size = total if total > 0 else 1
        total_pages = 1
        effective_page = 1

    rows_query = f"""
        SELECT o.id,
               o.external_message_id,
               o.received_at,
               {_STATUS_SQL} AS normalized_status,
               o.item_count,
               o.warnings_count,
               o.errors_count,
               o.ticket_number,
               o.kundennummer,
               o.kom_nr,
               o.kom_name,
               o.liefertermin,
               o.wunschtermin,
               o.delivery_week,
               o.store_name,
               o.store_address,
               o.iln,
               o.mail_to,
               {_EXTRACTION_BRANCH_SQL} AS normalized_extraction_branch,
               o.reply_needed,
               o.human_review_needed,
               o.post_case,
               o.validation_status,
               o.validation_summary,
               o.validation_checked_at,
               o.validation_provider,
               o.validation_model,
               o.validation_stale_reason,
               o.parse_error,
               o.updated_at AS mtime
        FROM orders o
        WHERE {where_sql}
        ORDER BY {_EFFECTIVE_RECEIVED_SQL} {order_direction}, o.id {order_direction}
    """
    row_params: list[Any] = list(where_params)
    if paginate:
        offset = (effective_page - 1) * effective_page_size
        rows_query += " LIMIT %s OFFSET %s"
        row_params.extend([effective_page_size, offset])
    rows = fetch_all(rows_query, row_params)

    orders = [
        _summary_row_to_order(row, status_field="normalized_status", branch_field="normalized_extraction_branch")
        for row in rows
    ]

    return {
        "orders": orders,
        "pagination": {
            "page": effective_page,
            "page_size": effective_page_size,
            "total": total,
            "total_pages": total_pages,
        },
        "counts": {
            "all": total,
            "today": counts_payload["today"],
            "waiting_for_reply": counts_payload["waiting_for_reply"],
            "manual_review": counts_payload["manual_review"],
            "unknown": counts_payload["status_unknown"],
            "gemini_review": counts_payload["gemini_review"],
            "updated_after_reply": counts_payload["status_updated_after_reply"],
            "status": {
                "ok": counts_payload["status_ok"],
                "waiting_for_reply": counts_payload["status_waiting_for_reply"],
                "human_in_the_loop": counts_payload["status_human_in_the_loop"],
                "post": counts_payload["status_post"],
                "failed": counts_payload["status_failed"],
                "unknown": counts_payload["status_unknown"],
                "updated_after_reply": counts_payload["status_updated_after_reply"],
                "total": total,
            },
        },
        "count_snapshot": counts_payload,
    }


def list_client_branch_counts(
    *,
    assigned_user_id: str | None = None,
    allowed_client_branches: set[str] | None = None,
) -> dict[str, int]:
    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    where_sql = " AND ".join(["o.deleted_at IS NULL", *scope_clauses])
    rows = fetch_all(
        f"""
        SELECT {_EXTRACTION_BRANCH_SQL} AS branch_id,
               COUNT(*)::bigint AS total
        FROM orders o
        WHERE {where_sql}
        GROUP BY {_EXTRACTION_BRANCH_SQL}
        """,
        scope_params,
    )
    counts = {branch: 0 for branch in sorted(ALLOWED_EXTRACTION_BRANCHES)}
    for row in rows:
        branch_id = _normalize_extraction_branch(row.get("branch_id"))
        counts[branch_id] = int(row.get("total") or 0)
    return counts


def query_overview_snapshot(
    *,
    range_start: datetime,
    range_end: datetime,
    chart_start: datetime,
    chart_end: datetime,
    bucket_granularity: str = "day",
    local_timezone: str = "UTC",
    assigned_user_id: str | None = None,
    allowed_client_branches: set[str] | None = None,
) -> dict[str, Any]:
    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    where_sql = " AND ".join(["o.deleted_at IS NULL", *scope_clauses])
    join_scope_sql = ""
    if scope_clauses:
        join_scope_sql = " AND " + " AND ".join(scope_clauses)

    summary = fetch_one(
        f"""
        SELECT
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s THEN 1 ELSE 0 END)::bigint AS period_total,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS period_ok,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'waiting_for_reply' THEN 1 ELSE 0 END)::bigint AS period_waiting_for_reply,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS period_human_in_the_loop,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS period_post,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'unknown' THEN 1 ELSE 0 END)::bigint AS period_unknown,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS period_failed,
            SUM(CASE WHEN {_EFFECTIVE_RECEIVED_SQL} >= %s AND {_EFFECTIVE_RECEIVED_SQL} < %s AND {_STATUS_SQL} = 'updated_after_reply' THEN 1 ELSE 0 END)::bigint AS period_updated_after_reply
        FROM orders o
        WHERE {where_sql}
        """,
        [
            range_start,
            range_end,
            range_start,
            range_end,
            range_start,
            range_end,
            range_start,
            range_end,
            range_start,
            range_end,
            range_start,
            range_end,
            range_start,
            range_end,
            range_start,
            range_end,
            *scope_params,
        ],
    ) or {}

    if bucket_granularity == "month":
        bucket_rows = fetch_all(
            f"""
            WITH month_buckets AS (
                SELECT generate_series(%s::date, %s::date, interval '1 month')::date AS bucket_start
            )
            SELECT b.bucket_start,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS ok,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'waiting_for_reply' THEN 1 ELSE 0 END)::bigint AS waiting_for_reply,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS human_in_the_loop,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS post,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'unknown' THEN 1 ELSE 0 END)::bigint AS unknown,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS failed,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'updated_after_reply' THEN 1 ELSE 0 END)::bigint AS updated_after_reply,
                   COUNT(o.id)::bigint AS total
            FROM month_buckets b
            LEFT JOIN orders o
              ON o.deleted_at IS NULL
             AND ({_EFFECTIVE_RECEIVED_SQL} AT TIME ZONE %s) >= b.bucket_start::timestamp
             AND ({_EFFECTIVE_RECEIVED_SQL} AT TIME ZONE %s) < (b.bucket_start::timestamp + interval '1 month')
             {join_scope_sql}
            GROUP BY b.bucket_start
            ORDER BY b.bucket_start
            """,
            [chart_start.date(), chart_end.date(), local_timezone, local_timezone, *scope_params],
        )
        client_hour_rows = fetch_all(
            f"""
            SELECT DATE_TRUNC('day', {_EFFECTIVE_RECEIVED_SQL} AT TIME ZONE %s)::date AS bucket_day,
                   EXTRACT(HOUR FROM {_EFFECTIVE_RECEIVED_SQL} AT TIME ZONE %s)::int AS bucket_hour,
                   {_EXTRACTION_BRANCH_SQL} AS branch_id,
                   COUNT(*)::bigint AS total
            FROM orders o
            WHERE o.deleted_at IS NULL
              AND {_EFFECTIVE_RECEIVED_SQL} >= %s
              AND {_EFFECTIVE_RECEIVED_SQL} < %s
              {join_scope_sql}
            GROUP BY bucket_day, bucket_hour, {_EXTRACTION_BRANCH_SQL}
            ORDER BY bucket_day, bucket_hour, {_EXTRACTION_BRANCH_SQL}
            """,
            [local_timezone, local_timezone, chart_start, range_end, *scope_params],
        )
    else:
        bucket_rows = fetch_all(
            f"""
            WITH day_buckets AS (
                SELECT generate_series(%s::timestamptz, %s::timestamptz, interval '1 day') AS bucket_start
            )
            SELECT b.bucket_start,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'ok' THEN 1 ELSE 0 END)::bigint AS ok,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'waiting_for_reply' THEN 1 ELSE 0 END)::bigint AS waiting_for_reply,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'human_in_the_loop' THEN 1 ELSE 0 END)::bigint AS human_in_the_loop,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'post' THEN 1 ELSE 0 END)::bigint AS post,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'unknown' THEN 1 ELSE 0 END)::bigint AS unknown,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'failed' THEN 1 ELSE 0 END)::bigint AS failed,
                   SUM(CASE WHEN o.id IS NOT NULL AND {_STATUS_SQL} = 'updated_after_reply' THEN 1 ELSE 0 END)::bigint AS updated_after_reply,
                   COUNT(o.id)::bigint AS total
            FROM day_buckets b
            LEFT JOIN orders o
              ON o.deleted_at IS NULL
             AND {_EFFECTIVE_RECEIVED_SQL} >= b.bucket_start
             AND {_EFFECTIVE_RECEIVED_SQL} < b.bucket_start + interval '1 day'
             {join_scope_sql}
            GROUP BY b.bucket_start
            ORDER BY b.bucket_start
            """,
            [chart_start, chart_end, *scope_params],
        )
        client_hour_rows = fetch_all(
            f"""
            SELECT DATE_TRUNC('day', {_EFFECTIVE_RECEIVED_SQL} AT TIME ZONE %s)::date AS bucket_day,
                   EXTRACT(HOUR FROM {_EFFECTIVE_RECEIVED_SQL} AT TIME ZONE %s)::int AS bucket_hour,
                   {_EXTRACTION_BRANCH_SQL} AS branch_id,
                   COUNT(*)::bigint AS total
            FROM orders o
            WHERE o.deleted_at IS NULL
              AND {_EFFECTIVE_RECEIVED_SQL} >= %s
              AND {_EFFECTIVE_RECEIVED_SQL} < (%s + interval '1 day')
              {join_scope_sql}
            GROUP BY bucket_day, bucket_hour, {_EXTRACTION_BRANCH_SQL}
            ORDER BY bucket_day, bucket_hour, {_EXTRACTION_BRANCH_SQL}
            """,
            [local_timezone, local_timezone, chart_start, chart_end, *scope_params],
        )

    client_hour_map: dict[tuple[Any, int], dict[str, int]] = {}
    for row in client_hour_rows:
        bucket_day = row.get("bucket_day")
        bucket_hour = int(row.get("bucket_hour") or 0)
        branch_id = _normalize_extraction_branch(row.get("branch_id"))
        total = int(row.get("total") or 0)
        key = (bucket_day, bucket_hour)
        if key not in client_hour_map:
            client_hour_map[key] = {}
        client_hour_map[key][branch_id] = total

    client_hour_days: list[dict[str, Any]] = []
    if bucket_granularity == "day":
        client_chart_start = chart_start
        client_chart_end = chart_end
    else:
        client_chart_start = datetime.combine(range_start.date(), datetime.min.time(), tzinfo=range_start.tzinfo)
        client_chart_end = datetime.combine(
            max(range_start, range_end - timedelta(microseconds=1)).date(),
            datetime.min.time(),
            tzinfo=range_start.tzinfo,
        )
    current_day = client_chart_start.date()
    last_day = client_chart_end.date()
    known_client_ids = sorted(ALLOWED_EXTRACTION_BRANCHES)
    while current_day <= last_day:
        hours: list[dict[str, Any]] = []
        day_total = 0
        for hour in range(24):
            client_counts = client_hour_map.get((current_day, hour), {})
            total = sum(client_counts.values())
            day_total += total
            hours.append(
                {
                    "hour": hour,
                    "total": total,
                    "clients": [
                        {"id": client_id, "count": int(client_counts.get(client_id) or 0)}
                        for client_id in known_client_ids
                        if int(client_counts.get(client_id) or 0) > 0
                    ],
                }
            )
        client_hour_days.append(
            {
                "date": current_day.isoformat(),
                "total": day_total,
                "hours": hours,
            }
        )
        current_day += timedelta(days=1)

    return {
        "summary": {
            "period_total": int(summary.get("period_total") or 0),
            "period_ok": int(summary.get("period_ok") or 0),
            "period_waiting_for_reply": int(summary.get("period_waiting_for_reply") or 0),
            "period_human_in_the_loop": int(summary.get("period_human_in_the_loop") or 0),
            "period_post": int(summary.get("period_post") or 0),
            "period_unknown": int(summary.get("period_unknown") or 0),
            "period_failed": int(summary.get("period_failed") or 0),
            "period_updated_after_reply": int(summary.get("period_updated_after_reply") or 0),
        },
        "status_by_day": [
            {
                "bucket_start": row.get("bucket_start"),
                "ok": int(row.get("ok") or 0),
                "waiting_for_reply": int(row.get("waiting_for_reply") or 0),
                "human_in_the_loop": int(row.get("human_in_the_loop") or 0),
                "post": int(row.get("post") or 0),
                "unknown": int(row.get("unknown") or 0),
                "failed": int(row.get("failed") or 0),
                "updated_after_reply": int(row.get("updated_after_reply") or 0),
                "total": int(row.get("total") or 0),
            }
            for row in bucket_rows
        ],
        "orders_by_client_hour": {
            "clients": [
                {
                    "id": branch_id,
                    "label": BRANCHES[branch_id].label if branch_id in BRANCHES else "Unknown",
                }
                for branch_id in sorted(ALLOWED_EXTRACTION_BRANCHES)
            ],
            "days": client_hour_days,
        },
    }


def query_xml_activity(
    *,
    range_start: datetime,
    range_end: datetime,
    chart_start: datetime,
    chart_end: datetime,
    bucket_granularity: str = "day",
    local_timezone: str = "UTC",
) -> dict[str, Any]:
    summary = fetch_one(
        """
        SELECT
          COUNT(DISTINCT px.order_id)::bigint AS generated_orders,
          (SELECT COUNT(*) FROM order_events
           WHERE event_type = 'xml_regenerated'
             AND created_at >= %s AND created_at < %s)::bigint AS regenerated_events
        FROM order_px_controls px
        WHERE px.xml_sent_at >= %s AND px.xml_sent_at < %s
        """,
        [range_start, range_end, range_start, range_end],
    ) or {}

    if bucket_granularity == "month":
        bucket_rows = fetch_all(
            """
            WITH month_buckets AS (
                SELECT generate_series(%s::date, %s::date, interval '1 month')::date AS bucket_start
            )
            SELECT
              b.bucket_start,
              COUNT(DISTINCT px.order_id)::bigint AS generated_orders,
              COUNT(DISTINCT e.id)::bigint        AS regenerated_events
            FROM month_buckets b
            LEFT JOIN order_px_controls px
              ON (px.xml_sent_at AT TIME ZONE %s) >= b.bucket_start::timestamp
             AND (px.xml_sent_at AT TIME ZONE %s) < (b.bucket_start::timestamp + interval '1 month')
            LEFT JOIN order_events e
              ON e.event_type = 'xml_regenerated'
             AND (e.created_at AT TIME ZONE %s) >= b.bucket_start::timestamp
             AND (e.created_at AT TIME ZONE %s) < (b.bucket_start::timestamp + interval '1 month')
            GROUP BY b.bucket_start
            ORDER BY b.bucket_start
            """,
            [
                chart_start.date(),
                chart_end.date(),
                local_timezone,
                local_timezone,
                local_timezone,
                local_timezone,
            ],
        )
    else:
        bucket_rows = fetch_all(
            """
            WITH day_buckets AS (
                SELECT generate_series(%s::timestamptz, %s::timestamptz, interval '1 day') AS bucket_start
            )
            SELECT
              b.bucket_start,
              COUNT(DISTINCT px.order_id)::bigint AS generated_orders,
              COUNT(DISTINCT e.id)::bigint        AS regenerated_events
            FROM day_buckets b
            LEFT JOIN order_px_controls px
              ON px.xml_sent_at >= b.bucket_start
             AND px.xml_sent_at < b.bucket_start + interval '1 day'
            LEFT JOIN order_events e
              ON e.event_type = 'xml_regenerated'
             AND e.created_at >= b.bucket_start
             AND e.created_at < b.bucket_start + interval '1 day'
            GROUP BY b.bucket_start
            ORDER BY b.bucket_start
            """,
            [chart_start, chart_end],
        )

    generated_orders = int(summary.get("generated_orders") or 0)
    regenerated_events = int(summary.get("regenerated_events") or 0)

    return {
        "summary": {
            "generated_orders": generated_orders,
            "regenerated_events": regenerated_events,
            "generated_files": generated_orders * 2,
            "regenerated_files": regenerated_events * 2,
        },
        "by_day": [
            {
                "bucket_start": row.get("bucket_start"),
                "generated_orders": int(row.get("generated_orders") or 0),
                "regenerated_events": int(row.get("regenerated_events") or 0),
            }
            for row in bucket_rows
        ],
    }


def get_order_detail(
    order_id: str,
    *,
    assigned_user_id: str | None = None,
    allowed_client_branches: set[str] | None = None,
    role: str | None = None,
) -> dict[str, Any] | None:
    where_parts = [
        "o.id = %s",
        "o.deleted_at IS NULL",
    ]
    params: list[Any] = [order_id]
    scope_clauses, scope_params = _scope_where_fragments(
        assigned_user_id=assigned_user_id,
        allowed_client_branches=allowed_client_branches,
    )
    where_parts.extend(scope_clauses)
    params.extend(scope_params)
    where_sql = " AND ".join(where_parts)

    row = fetch_one(
        f"""
        SELECT o.*,
               r.payload_json,
               vr.status AS latest_validation_run_status,
               vr.summary AS latest_validation_run_summary,
               vr.issues_json AS latest_validation_run_issues,
               vr.result_json AS latest_validation_run_result,
               vr.created_at AS latest_validation_run_created_at,
               t.id AS review_task_id,
               t.state AS review_state,
               t.assigned_user_id,
               t.claim_expires_at,
               t.due_at AS sla_due_at,
               u.username AS assigned_username,
               e.last_event_at
        FROM orders o
        LEFT JOIN order_revisions r ON r.id = o.current_revision_id
        LEFT JOIN LATERAL (
            SELECT v1.status,
                   v1.summary,
                   v1.issues_json,
                   v1.result_json,
                   v1.created_at
            FROM order_validation_runs v1
            WHERE v1.order_id = o.id
            ORDER BY v1.created_at DESC
            LIMIT 1
        ) vr ON TRUE
        LEFT JOIN LATERAL (
            SELECT t1.*
            FROM order_review_tasks t1
            WHERE t1.order_id = o.id
              AND t1.state NOT IN ('resolved', 'cancelled')
            ORDER BY t1.created_at DESC
            LIMIT 1
        ) t ON TRUE
        LEFT JOIN users u ON u.id = t.assigned_user_id
        LEFT JOIN LATERAL (
            SELECT MAX(created_at) AS last_event_at
            FROM order_events e1
            WHERE e1.order_id = o.id
        ) e ON TRUE
        WHERE {where_sql}
        """,
        params,
    )
    if not row:
        return None

    payload = row.get("payload_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload = _normalize_payload(payload)

    raw_warnings = _coerce_signal_messages(payload.get("warnings", []))
    raw_errors = _coerce_signal_messages(payload.get("errors", []))
    warnings = sanitize_operational_signal_messages(raw_warnings, level="warning", role=role)
    errors = sanitize_operational_signal_messages(raw_errors, level="error", role=role)
    validation_issues = _normalize_validation_issues(row.get("latest_validation_run_issues"))
    validation_result_json = row.get("latest_validation_run_result")
    if isinstance(validation_result_json, str):
        try:
            validation_result_json = json.loads(validation_result_json)
        except json.JSONDecodeError:
            validation_result_json = {}
    if not isinstance(validation_result_json, dict):
        validation_result_json = {}
    return {
        "safe_id": str(row["id"]),
        "data": payload,
        "parse_error": row.get("parse_error"),
        "header": payload.get("header") if isinstance(payload.get("header"), dict) else {},
        "items": payload.get("items") if isinstance(payload.get("items"), list) else [],
        "raw_warnings": raw_warnings,
        "raw_errors": raw_errors,
        "warnings": warnings,
        "errors": errors,
        "status": normalize_status(row.get("status")),
        "human_review_needed": bool(row.get("human_review_needed")),
        "reply_needed": bool(row.get("reply_needed")),
        "post_case": bool(row.get("post_case")),
        "validation_status": normalize_validation_status(row.get("validation_status")),
        "validation_summary": str(row.get("validation_summary") or ""),
        "validation_checked_at": _to_iso(row.get("validation_checked_at")) if row.get("validation_checked_at") else "",
        "validation_provider": str(row.get("validation_provider") or ""),
        "validation_model": str(row.get("validation_model") or ""),
        "validation_stale_reason": str(row.get("validation_stale_reason") or ""),
        "validation_issues": validation_issues,
        "validation_result": validation_result_json,
        "validation_run_created_at": _to_iso(row.get("latest_validation_run_created_at"))
        if row.get("latest_validation_run_created_at")
        else "",
        "message_id": row.get("external_message_id") or str(row["id"]),
        "received_at": _to_iso(row.get("received_at")),
        "review_task_id": str(row["review_task_id"]) if row.get("review_task_id") else None,
        "review_state": row.get("review_state"),
        "assigned_user_id": str(row["assigned_user_id"]) if row.get("assigned_user_id") else None,
        "assigned_user": row.get("assigned_username"),
        "claim_expires_at": _to_iso(row.get("claim_expires_at")) if row.get("claim_expires_at") else None,
        "sla_due_at": _to_iso(row.get("sla_due_at")) if row.get("sla_due_at") else None,
        "last_event_at": _to_iso(row.get("last_event_at")) if row.get("last_event_at") else None,
    }


def get_order_payload_map(order_ids: list[str]) -> dict[str, dict[str, Any]]:
    cleaned_ids = [str(order_id).strip() for order_id in order_ids if str(order_id).strip()]
    if not cleaned_ids:
        return {}
    unique_ids = list(dict.fromkeys(cleaned_ids))
    rows = fetch_all(
        """
        SELECT o.id,
               o.parse_error,
               o.validation_status,
               o.validation_summary,
               o.validation_checked_at,
               o.validation_provider,
               o.validation_model,
               o.validation_stale_reason,
               vr.issues_json AS latest_validation_run_issues,
               r.payload_json
        FROM orders o
        LEFT JOIN order_revisions r ON r.id = o.current_revision_id
        LEFT JOIN LATERAL (
            SELECT v1.issues_json
            FROM order_validation_runs v1
            WHERE v1.order_id = o.id
            ORDER BY v1.created_at DESC
            LIMIT 1
        ) vr ON TRUE
        WHERE o.deleted_at IS NULL
          AND o.id = ANY(%s)
        """,
        (unique_ids,),
    )
    payload_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = row.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload_map[str(row["id"])] = {
            "data": _normalize_payload(payload),
            "parse_error": row.get("parse_error"),
            "validation_status": normalize_validation_status(row.get("validation_status")),
            "validation_summary": str(row.get("validation_summary") or ""),
            "validation_checked_at": _to_iso(row.get("validation_checked_at")) if row.get("validation_checked_at") else "",
            "validation_provider": str(row.get("validation_provider") or ""),
            "validation_model": str(row.get("validation_model") or ""),
            "validation_stale_reason": str(row.get("validation_stale_reason") or ""),
            "validation_issues": _normalize_validation_issues(row.get("latest_validation_run_issues")),
        }
    return payload_map


def is_order_editable_for_detail(
    *,
    order: dict[str, Any] | None,
    user_id: str,
    is_admin: bool,
) -> tuple[bool, str]:
    _ = user_id, is_admin
    if not order:
        return False, "Order not found"
    if order.get("parse_error"):
        return False, "Order payload could not be parsed"
    return True, ""


def is_order_editable_for_user(*, order_id: str, user_id: str, is_admin: bool) -> tuple[bool, str]:
    order = get_order_detail(order_id)
    return is_order_editable_for_detail(order=order, user_id=user_id, is_admin=is_admin)


def save_manual_revision(
    *,
    order_id: str,
    payload: dict[str, Any],
    actor_user_id: str,
    diff_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = get_order_detail(order_id)
    if not existing:
        raise OrderStoreError(404, "not_found", "Order not found")
    payload_with_branch = dict(payload or {})
    if "extraction_branch" not in payload_with_branch:
        existing_data = existing.get("data")
        existing_branch = ""
        if isinstance(existing_data, dict):
            existing_branch = str(existing_data.get("extraction_branch") or "")
        payload_with_branch["extraction_branch"] = _normalize_extraction_branch(existing_branch)
    with get_connection() as conn:
        result = _upsert_revision(
            conn,
            payload=_normalize_payload(payload_with_branch),
            external_message_id=str(existing.get("message_id") or order_id),
            change_type="manual_edit",
            changed_by_user_id=actor_user_id,
            parse_error=None,
            diff_json=diff_json,
            validation_result=None,
        )
        conn.commit()
    return result


def soft_delete_order(*, order_id: str, actor_user_id: str | None) -> bool:
    detail = get_order_detail(order_id)
    if not detail:
        return False
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
        conn.commit()
    return True


def record_order_event(
    *,
    order_id: str,
    event_type: str,
    actor_user_id: str | None = None,
    actor_type: str | None = None,
    revision_id: str | None = None,
    event_data: dict[str, Any] | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    order_id,
                    revision_id,
                    event_type,
                    actor_type or ("user" if actor_user_id else "system"),
                    actor_user_id,
                    _jsonb(event_data),
                    _now(),
                ),
            )
        conn.commit()


def record_validation_run(
    *,
    order_id: str,
    revision_id: str,
    validation_result: dict[str, Any],
) -> None:
    normalized = _normalize_validation_result_payload(validation_result)
    status = normalize_validation_status(normalized.get("validation_status"))
    if status in {VALIDATION_STATUS_NOT_RUN, "stale", VALIDATION_STATUS_RESOLVED}:
        return
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO order_validation_runs (
                    id,
                    order_id,
                    revision_id,
                    provider,
                    model,
                    status,
                    summary,
                    issues_json,
                    result_json,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (order_id, revision_id, provider)
                DO UPDATE SET
                    model = EXCLUDED.model,
                    status = EXCLUDED.status,
                    summary = EXCLUDED.summary,
                    issues_json = EXCLUDED.issues_json,
                    result_json = EXCLUDED.result_json,
                    created_at = EXCLUDED.created_at
                """,
                (
                    str(uuid.uuid4()),
                    order_id,
                    revision_id,
                    normalized["validation_provider"] or VALIDATION_PROVIDER_GEMINI,
                    normalized["validation_model"],
                    status,
                    normalized["validation_summary"],
                    _jsonb(normalized["validation_issues"]),
                    _jsonb(normalized["validation_raw_result"]),
                    _parse_iso(normalized.get("validation_checked_at")) or _now(),
                ),
            )
        conn.commit()


def mark_validation_stale(
    *,
    order_id: str,
    reason: str,
    actor_user_id: str | None = None,
) -> bool:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET validation_status = 'stale',
                    validation_summary = %s,
                    validation_checked_at = %s,
                    validation_stale_reason = %s,
                    updated_at = %s
                WHERE id = %s
                  AND deleted_at IS NULL
                  AND validation_status IN ('passed', 'flagged', 'resolved', 'skipped')
                """,
                (
                    "Gemini validation is stale after a manual change.",
                    now,
                    str(reason or "").strip() or "manual_change",
                    now,
                    order_id,
                ),
            )
            updated = cursor.rowcount > 0
        conn.commit()
    if updated:
        record_order_event(
            order_id=order_id,
            event_type="validation_marked_stale",
            actor_user_id=actor_user_id,
            event_data={"reason": str(reason or "").strip() or "manual_change"},
        )
    return updated


def resolve_validation(
    *,
    order_id: str,
    actor_user_id: str | None,
    note: str,
) -> dict[str, Any]:
    now = _now()
    note_text = str(note or "").strip()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orders
                SET validation_status = %s,
                    validation_summary = %s,
                    validation_checked_at = %s,
                    validation_stale_reason = '',
                    updated_at = %s
                WHERE id = %s
                  AND deleted_at IS NULL
                RETURNING validation_status,
                          validation_summary,
                          validation_checked_at,
                          validation_provider,
                          validation_model,
                          validation_stale_reason
                """,
                (
                    VALIDATION_STATUS_RESOLVED,
                    "Gemini validation resolved manually.",
                    now,
                    now,
                    order_id,
                ),
            )
            row = cursor.fetchone()
            if not row:
                raise OrderStoreError(404, "not_found", "Order not found")
        conn.commit()
    record_order_event(
        order_id=order_id,
        event_type="validation_resolved",
        actor_user_id=actor_user_id,
        event_data={"note": note_text},
    )
    return {
        "validation_status": normalize_validation_status(row.get("validation_status")),
        "validation_summary": str(row.get("validation_summary") or ""),
        "validation_checked_at": _to_iso(row.get("validation_checked_at")) if row.get("validation_checked_at") else "",
        "validation_provider": str(row.get("validation_provider") or ""),
        "validation_model": str(row.get("validation_model") or ""),
        "validation_stale_reason": str(row.get("validation_stale_reason") or ""),
    }


def _checksum(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), size


def register_order_files(*, order_id: str, revision_id: str | None, file_type: str, storage_paths: list[str]) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for storage_path in storage_paths:
                if not storage_path:
                    continue
                path = Path(storage_path)
                checksum = ""
                size = 0
                if path.exists() and path.is_file():
                    try:
                        checksum, size = _checksum(path)
                    except OSError:
                        checksum, size = "", 0
                cursor.execute(
                    """
                    INSERT INTO order_files (id, order_id, revision_id, file_type, storage_path, checksum_sha256, size_bytes, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), order_id, revision_id, file_type, storage_path, checksum, size, now),
                )
        conn.commit()


def list_review_tasks(
    *,
    states: set[str] | None = None,
    assigned_user_id: str | None = None,
    include_unassigned: bool = True,
    allowed_client_branches: set[str] | None = None,
) -> list[dict[str, Any]]:
    where_parts = ["o.deleted_at IS NULL"]
    params: list[Any] = []
    if states:
        where_parts.append("t.state = ANY(%s)")
        params.append(list(states))
    else:
        where_parts.append("t.state NOT IN ('resolved', 'cancelled')")
    if assigned_user_id:
        if include_unassigned:
            where_parts.append("(t.assigned_user_id = %s OR t.assigned_user_id IS NULL)")
        else:
            where_parts.append("t.assigned_user_id = %s")
        params.append(assigned_user_id)
    normalized_branches = _normalize_branch_set(allowed_client_branches)
    if normalized_branches is not None:
        if not normalized_branches:
            where_parts.append("1 = 0")
        else:
            where_parts.append(f"{_EXTRACTION_BRANCH_SQL} = ANY(%s)")
            params.append(normalized_branches)
    where_sql = " AND ".join(where_parts)
    rows = fetch_all(
        f"""
        SELECT t.id,
               t.order_id,
               t.task_type,
               t.state,
               t.priority,
               t.assigned_user_id,
               t.claimed_at,
               t.claim_expires_at,
               t.due_at,
               t.resolved_at,
               t.resolution_outcome,
               t.resolution_note,
               t.created_at,
               t.updated_at,
               u.username AS assigned_username,
               o.status AS order_status,
               o.external_message_id,
               o.ticket_number,
               o.kom_nr,
               o.kom_name
        FROM order_review_tasks t
        JOIN orders o ON o.id = t.order_id
        LEFT JOIN users u ON u.id = t.assigned_user_id
        WHERE {where_sql}
        ORDER BY
            CASE t.state
                WHEN 'claimed' THEN 0
                WHEN 'in_progress' THEN 1
                WHEN 'queued' THEN 2
                ELSE 3
            END,
            t.priority ASC,
            COALESCE(t.due_at, t.created_at) ASC
        """,
        params,
    )
    tasks: list[dict[str, Any]] = []
    for row in rows:
        tasks.append(
            {
                "id": str(row["id"]),
                "order_id": str(row["order_id"]),
                "task_type": row.get("task_type"),
                "state": row.get("state"),
                "priority": int(row.get("priority") or 0),
                "assigned_user_id": str(row["assigned_user_id"]) if row.get("assigned_user_id") else None,
                "assigned_user": row.get("assigned_username"),
                "claimed_at": _to_iso(row.get("claimed_at")) if row.get("claimed_at") else None,
                "claim_expires_at": _to_iso(row.get("claim_expires_at")) if row.get("claim_expires_at") else None,
                "due_at": _to_iso(row.get("due_at")) if row.get("due_at") else None,
                "resolved_at": _to_iso(row.get("resolved_at")) if row.get("resolved_at") else None,
                "resolution_outcome": row.get("resolution_outcome"),
                "resolution_note": row.get("resolution_note"),
                "created_at": _to_iso(row.get("created_at")) if row.get("created_at") else None,
                "updated_at": _to_iso(row.get("updated_at")) if row.get("updated_at") else None,
                "order_status": normalize_status(row.get("order_status")),
                "message_id": row.get("external_message_id"),
                "ticket_number": row.get("ticket_number") or "",
                "kom_nr": row.get("kom_nr") or "",
                "kom_name": row.get("kom_name") or "",
            }
        )
    return tasks


def _load_task_for_update(conn, task_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM order_review_tasks WHERE id = %s FOR UPDATE", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def _task_by_id(task_id: str) -> dict[str, Any] | None:
    items = [task for task in list_review_tasks() if task["id"] == task_id]
    return items[0] if items else None


def claim_task(*, task_id: str, user_id: str, lease_seconds: int = 300) -> dict[str, Any]:
    now = _now()
    lease_seconds = max(30, min(3600, int(lease_seconds)))
    lease_until = now + timedelta(seconds=lease_seconds)
    with get_connection() as conn:
        task = _load_task_for_update(conn, task_id)
        if not task:
            raise OrderStoreError(404, "not_found", "Review task not found")
        if task.get("state") in TASK_DONE_STATES:
            raise OrderStoreError(409, "conflict", "Review task is already resolved")
        assigned_user_id = str(task.get("assigned_user_id") or "")
        claim_expires = task.get("claim_expires_at")
        active_other_claim = (
            assigned_user_id
            and assigned_user_id != user_id
            and isinstance(claim_expires, datetime)
            and claim_expires > now
        )
        if active_other_claim:
            raise OrderStoreError(409, "conflict", "Task is currently claimed by another reviewer")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET assigned_user_id = %s,
                    state = 'claimed',
                    claimed_at = COALESCE(claimed_at, %s),
                    claim_expires_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (user_id, now, lease_until, now, task_id),
            )
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, NULL, 'review_task_claimed', 'user', %s, %s::jsonb, %s)
                """,
                (task["order_id"], user_id, _jsonb({"task_id": task_id, "claim_expires_at": lease_until.isoformat()}), now),
            )
        conn.commit()
    claimed = _task_by_id(task_id)
    if not claimed:
        raise OrderStoreError(500, "internal_error", "Claim succeeded but task reload failed")
    return claimed


def heartbeat_task(*, task_id: str, user_id: str, lease_seconds: int = 300) -> dict[str, Any]:
    now = _now()
    lease_seconds = max(30, min(3600, int(lease_seconds)))
    lease_until = now + timedelta(seconds=lease_seconds)
    with get_connection() as conn:
        task = _load_task_for_update(conn, task_id)
        if not task:
            raise OrderStoreError(404, "not_found", "Review task not found")
        if task.get("state") in TASK_DONE_STATES:
            raise OrderStoreError(409, "conflict", "Review task is already resolved")
        if str(task.get("assigned_user_id") or "") != user_id:
            raise OrderStoreError(403, "forbidden", "Task is assigned to another reviewer")
        expires_at = task.get("claim_expires_at")
        if not isinstance(expires_at, datetime) or expires_at <= now:
            raise OrderStoreError(403, "forbidden", "Task claim has expired")
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET state = 'in_progress',
                    claim_expires_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (lease_until, now, task_id),
            )
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, NULL, 'review_task_heartbeat', 'user', %s, %s::jsonb, %s)
                """,
                (task["order_id"], user_id, _jsonb({"task_id": task_id, "claim_expires_at": lease_until.isoformat()}), now),
            )
        conn.commit()
    heartbeat = _task_by_id(task_id)
    if not heartbeat:
        raise OrderStoreError(500, "internal_error", "Heartbeat succeeded but task reload failed")
    return heartbeat


def resolve_task(
    *,
    task_id: str,
    user_id: str,
    is_admin: bool,
    outcome: str,
    note: str,
    force: bool = False,
) -> dict[str, Any]:
    now = _now()
    outcome_text = (outcome or "resolved").strip() or "resolved"
    note_text = (note or "").strip()
    with get_connection() as conn:
        task = _load_task_for_update(conn, task_id)
        if not task:
            raise OrderStoreError(404, "not_found", "Review task not found")
        if task.get("state") in TASK_DONE_STATES:
            raise OrderStoreError(409, "conflict", "Review task is already resolved")
        if not is_admin and str(task.get("assigned_user_id") or "") != user_id:
            raise OrderStoreError(403, "forbidden", "Only the assigned reviewer can resolve this task")
        if force and not is_admin:
            raise OrderStoreError(403, "forbidden", "Force resolve requires admin role")
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE order_review_tasks
                SET state = 'resolved',
                    resolved_at = %s,
                    resolution_outcome = %s,
                    resolution_note = %s,
                    claim_expires_at = NULL,
                    updated_at = %s
                WHERE id = %s
                """,
                (now, outcome_text, note_text, now, task_id),
            )
            cursor.execute(
                """
                INSERT INTO order_events (order_id, revision_id, event_type, actor_type, actor_user_id, event_data, created_at)
                VALUES (%s, NULL, 'review_task_resolved', %s, %s, %s::jsonb, %s)
                """,
                (
                    task["order_id"],
                    "user" if user_id else "system",
                    user_id,
                    _jsonb({"task_id": task_id, "outcome": outcome_text, "force": bool(force)}),
                    now,
                ),
            )
        conn.commit()
    resolved = _task_by_id(task_id)
    if resolved:
        return resolved
    return {
        "id": task_id,
        "order_id": str(task["order_id"]),
        "state": "resolved",
        "resolution_outcome": outcome_text,
        "resolution_note": note_text,
        "resolved_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# PX triple-control helpers
# ---------------------------------------------------------------------------

def get_px_controls(order_id: str) -> dict[str, Any] | None:
    """Return the current PX controls record for an order, or None if not found."""
    row = fetch_one(
        """
        SELECT order_id, px_status,
               control_1_user_id, control_1_at,
               control_2_user_id, control_2_at,
               final_control_user_id, final_control_at,
               xml_sent_at
        FROM order_px_controls
        WHERE order_id = %s
        """,
        (order_id,),
    )
    if not row:
        return None
    return {
        "order_id": str(row["order_id"]),
        "px_status": str(row["px_status"] or "pending"),
        "control_1_user_id": str(row["control_1_user_id"]) if row.get("control_1_user_id") else None,
        "control_1_at": _to_iso(row["control_1_at"]) if row.get("control_1_at") else None,
        "control_2_user_id": str(row["control_2_user_id"]) if row.get("control_2_user_id") else None,
        "control_2_at": _to_iso(row["control_2_at"]) if row.get("control_2_at") else None,
        "final_control_user_id": str(row["final_control_user_id"]) if row.get("final_control_user_id") else None,
        "final_control_at": _to_iso(row["final_control_at"]) if row.get("final_control_at") else None,
        "xml_sent_at": _to_iso(row["xml_sent_at"]) if row.get("xml_sent_at") else None,
    }


def get_px_status_map(order_ids: list[str]) -> dict[str, str]:
    """Return a mapping of order_id -> px_status for a batch of orders."""
    if not order_ids:
        return {}
    rows = fetch_all(
        """
        SELECT order_id::text, px_status
        FROM order_px_controls
        WHERE order_id = ANY(%s::uuid[])
        """,
        (order_ids,),
    )
    return {str(row["order_id"]): str(row["px_status"] or "pending") for row in rows}


def confirm_px_control(order_id: str, level: str, user_id: str) -> None:
    """Confirm one of the three PX control steps for an order."""
    _STATUS_MAP = {
        "control_1": "control_1_done",
        "control_2": "control_2_done",
        "final_control": "done",
    }
    new_status = _STATUS_MAP[level]
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE order_px_controls
                SET {level}_user_id = %s,
                    {level}_at = %s,
                    px_status = %s,
                    updated_at = %s
                WHERE order_id = %s
                """,
                (user_id, now, new_status, now, order_id),
            )
        conn.commit()


def mark_px_xml_sent(order_id: str) -> None:
    """Record that the PX XML email was sent."""
    execute(
        "UPDATE order_px_controls SET xml_sent_at = %s, updated_at = %s WHERE order_id = %s",
        (_now(), _now(), order_id),
    )

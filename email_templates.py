from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REQUIRED_TEMPLATE_IDS = {
    "missing_lieferanschrift",
    "missing_bestellendes_haus",
    "missing_modellnummer",
    "missing_artikelnummer",
    "missing_menge",
    "missing_multiple_pflichtfelder",
    "missing_furnplan",
    "unterlage_unleserlich",
}

_REQUIRED_PLACEHOLDERS = {"kommisionsnummer", "fehlende_pflichtfelder_liste"}


def load_reply_templates(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    _validate_reply_templates(data, Path(path))
    return data


def _validate_reply_templates(data: Any, path: Path) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"Reply templates file {path} must contain a JSON object.")

    placeholders = data.get("placeholders")
    if not isinstance(placeholders, dict):
        raise ValueError(f"Reply templates file {path} is missing 'placeholders' object.")
    missing_placeholders = sorted(_REQUIRED_PLACEHOLDERS - set(placeholders.keys()))
    if missing_placeholders:
        raise ValueError(
            f"Reply templates file {path} is missing required placeholders: {', '.join(missing_placeholders)}"
        )

    templates = data.get("templates")
    if not isinstance(templates, dict):
        raise ValueError(f"Reply templates file {path} is missing 'templates' object.")

    missing_templates = sorted(_REQUIRED_TEMPLATE_IDS - set(templates.keys()))
    if missing_templates:
        raise ValueError(
            f"Reply templates file {path} is missing required templates: {', '.join(missing_templates)}"
        )

    for template_id, template_data in templates.items():
        if not isinstance(template_data, dict):
            raise ValueError(f"Template '{template_id}' in {path} must be an object.")
        subject = str(template_data.get("subject", "") or "").strip()
        body = str(template_data.get("body", "") or "").strip()
        if not subject:
            raise ValueError(f"Template '{template_id}' in {path} has empty subject.")
        if not body:
            raise ValueError(f"Template '{template_id}' in {path} has empty body.")

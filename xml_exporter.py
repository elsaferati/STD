import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import re

from config import Config

_MANUFACTURER_ILN_MAP = {
    "staud": "4039262000004",
    "rauch": "4003769000008",
    "nolte": "4022956000006",
    "wimex": "4011808000003",
    "express": "4013227000009",
}

def _get_val(data: Dict[str, Any], key: str, default: str = "") -> str:
    """Helper to safely get value from data dict structure."""
    if not data:
        return default
    entry = data.get(key)
    if isinstance(entry, dict):
        return str(entry.get("value", default) or default)
    return str(entry or default)


def _sanitize_for_filename(value: str) -> str:
    """Keep only alphanumeric, underscore, hyphen; safe for filenames and _SAFE_ID_RE."""
    if not value:
        return ""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return s.strip("_") or ""


def _effective_xml_base_name(data: Dict[str, Any]) -> str:
    """Return base name for XML files: ticket_number, else kom_nr, else kom_name, else 'unknown'."""
    header = data.get("header") or {}
    ticket_number = _sanitize_for_filename(_get_val(header, "ticket_number"))
    if ticket_number:
        return ticket_number
    kom_nr = _sanitize_for_filename(_get_val(header, "kom_nr"))
    if kom_nr:
        return kom_nr
    kom_name = _sanitize_for_filename(_get_val(header, "kom_name"))
    if kom_name:
        return kom_name
    return "unknown"

def _prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, "utf-8")
    reparsed = minidom.parseString(rough_string)
    # The default prettify adds separate lines which is good, but we want to match the minimal style if possible.
    # actually minidom prettify is fine.
    return reparsed.toprettyxml(indent="  ")

def _normalize_address_spacing(address: str) -> str:
    """Fix missing spaces in address strings between components."""
    if not address:
        return address
    
    # 1. Insert space before country code prefix (D-, A-, CH-) when preceded by digit
    #    Example: "103D-46149" -> "103 D-46149"
    address = re.sub(r'(\d)([A-Z]{1,2}-\d)', r'\1 \2', address)
    
    # 2. Insert space before 5-digit German ZIP when preceded by 1-3 digit house number
    #    Example: "2238112" -> "22 38112"
    #    IMPORTANT: Only match 6-8 consecutive digits to avoid splitting already-formatted ZIPs
    #    Use negative lookbehinds to avoid:
    #    - Splitting after country code hyphen (D-46149)
    #    - Splitting in middle of digit sequences (would create "3 8112" from "38112")
    address = re.sub(r'(?<![-\d])(\d{1,3})(\d{5})(?=\s|$|[A-Z])', r'\1 \2', address)
    
    # Note: Austrian 4-digit ZIP pattern removed - it was incorrectly splitting German 5-digit ZIPs
    # Austrian addresses with "A-" prefix are handled by step 1 above
    
    # 3. Insert space before country names when preceded by letter
    #    Example: "NastättenGermany" -> "Nastätten Germany"
    countries = r'(Germany|Deutschland|Austria|Österreich|Switzerland|Schweiz|France|Frankreich|Belgium|Belgien|Netherlands|Niederlande|Italy|Italien)'
    address = re.sub(rf'([a-zA-ZäöüÄÖÜß/])({countries})(?=\s|$)', r'\1 \2', address)
    
    return address


def _split_article_id(article_id: str) -> tuple:
    """Split article_id on first hyphen into (model_number, article_number)."""
    fixed = _fix_article_id_ocr(str(article_id or ""))
    if "-" in fixed:
        idx = fixed.index("-")
        return fixed[:idx], fixed[idx + 1:]
    return fixed, ""


def _fix_article_id_ocr(article_id: str) -> str:
    """
    Fix common OCR character swap errors in Article IDs.
    
    Patterns fixed:
    - CQSNI -> CQSN1 (cabinet prefix: I mistaken for 1)
    - CQI6  -> CQ16  (bed prefix: I mistaken for 1)
    - OI00  -> OJ00  (accessory prefix: I mistaken for J)
    - ZBO0  -> ZB00  (general: O mistaken for 0)
    """
    if not article_id:
        return article_id
    
    # Pattern 1: Cabinet prefix - CQSNI -> CQSN1
    # Example: CQSNI6TP... -> CQSN16TP..., CQSNI699... -> CQSN1699...
    if article_id.startswith("CQSNI"):
        article_id = "CQSN1" + article_id[5:]
    
    # Pattern 2: Bed prefix - CQI6 -> CQ16
    # Example: CQI616... -> CQ1616...
    if article_id.startswith("CQI6"):
        article_id = "CQ16" + article_id[4:]
    
    # Pattern 3: Accessory prefix - OI00 -> OJ00
    # Example: OI00-66979 -> OJ00-66979
    if article_id.startswith("OI00"):
        article_id = "OJ00" + article_id[4:]
    
    # Pattern 4: General prefix O->0 fix - ZBO0 -> ZB00
    # Also handle similar patterns where O appears where 0 is expected
    if article_id.startswith("ZBO0"):
        article_id = "ZB00" + article_id[4:]
    
    return article_id


def _delivery_week_to_xml_format(value: str) -> str:
    """
    Convert delivery_week string to XML format YYYYWWWO (e.g. 2026 week 5 -> 202605WO).
    Supports: "2026 Week - 05" (from delivery_logic) and "KW05/2026" or "KW 05/2026".
    """
    if not value or not str(value).strip():
        return ""
    s = str(value).strip()
    # "2026 Week - 05" (from delivery_logic)
    m = re.match(r"(\d{4})\s*Week\s*-\s*(\d{1,2})\b", s, re.IGNORECASE)
    if m:
        year, week = int(m.group(1)), int(m.group(2))
        if 1 <= week <= 53:
            return f"{year}{week:02d}WO"
    # "KW05/2026" or "KW 05 / 2026"
    m = re.search(r"(?:KW|Woche)\s*(\d{1,2})\s*[/.-]?\s*(\d{4})", s, re.IGNORECASE)
    if m:
        week, year = int(m.group(1)), int(m.group(2))
        if 1 <= week <= 53:
            return f"{year}{week:02d}WO"
    return ""


def generate_order_info_xml(data: Dict[str, Any], base_name: str, config: Config, output_dir: Path) -> Path:
    """
    Generates OrderInfo_TIMESTAMP.xml
    """
    header = data.get("header", {})
    
    # Root element
    root = ET.Element("Order")
    
    # OrderInformations element
    # Mapping based on analysis:
    # StoreName -> Config
    # StoreAddress -> Config
    # Seller -> Config
    # CommissionNumber -> kom_nr
    # CommissionName -> kom_name
    # DateOfDelivery -> delivery_week (calculated from delivery_logic)
    # DeliveryAddress -> lieferanschrift
    # DealerNumberAtManufacturer -> kundennummer
    # ASAP -> "1" (hardcoded/default)
    
    order_info = ET.SubElement(root, "OrderInformations")
    order_info.set("OrderID", _get_val(header, "ticket_number"))
    order_info.set("DealerNumberAtManufacturer", _get_val(header, "kundennummer"))
    order_info.set("CommissionNumber", _get_val(header, "kom_nr"))
    order_info.set("CommissionName", _get_val(header, "kom_name"))
    order_info.set("DateOfDelivery", _delivery_week_to_xml_format(_get_val(header, "delivery_week")))
    order_info.set("StoreName", _get_val(header, "store_name"))
    order_info.set("StoreAddress", _normalize_address_spacing(_get_val(header, "store_address")))
    order_info.set("Seller", _get_val(header, "seller"))
    
    # Clean up address for XML attribute (single line or preserved? Example had raw newlines)
    # The example had "Im Gewerbepark 1\n76863 Herxheim\nGermany" inside the attribute.
    # So we keep newlines.
    order_info.set("DeliveryAddress", _normalize_address_spacing(_get_val(header, "lieferanschrift")))
    order_info.set("ASAP", "1") 

    filename = f"OrderInfo_{base_name}.xml"
    output_path = output_dir / filename
    
    xml_str = _prettify_xml(root)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_str)
        
    return output_path

def generate_article_info_xml(data: Dict[str, Any], base_name: str, output_dir: Path) -> Path:
    """
    Generates OrderArticleInfo_TIMESTAMP.xml
    Uses optional `articles` data when present, otherwise falls back to basic `items`.
    """
    header = data.get("header", {})
    items = data.get("items", [])
    program_info = data.get("program") or {}
    if not isinstance(program_info, dict):
        program_info = {}
    articles = data.get("articles", [])

    root = ET.Element("OrderItems")
    ET.SubElement(root, "OrderID").text = _get_val(header, "ticket_number")
    items_elem = ET.SubElement(root, "Items")

    program_name = str(program_info.get("program_name", "") or "")
    program_furncloud = str(program_info.get("furncloud_id", "") or "")

    use_detailed = bool(articles)
    if use_detailed:
        _build_items_from_articles(items_elem, articles, program_name, program_furncloud)
    else:
        _build_items_from_items(items_elem, items, program_name, program_furncloud)

    filename = f"OrderArticleInfo_{base_name}.xml"
    output_path = output_dir / filename
    xml_str = _prettify_xml(root)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_str)
    return output_path


def _build_items_from_articles(items_elem, articles, program_name, program_furncloud):
    for idx, article in enumerate(articles, start=1):
        model_num, article_num = _split_article_id(article.get("article_id", ""))
        qty = article.get("quantity", 1)
        try:
            qty_str = f"{float(qty):.1f}"
        except (ValueError, TypeError):
            qty_str = "1.0"
        item = ET.SubElement(items_elem, "Item")
        ET.SubElement(item, "Position").text = str(idx)
        ET.SubElement(item, "ModelNumber").text = model_num
        ET.SubElement(item, "ArticleNumber").text = article_num
        ET.SubElement(item, "Model").text = program_name
        ET.SubElement(item, "Quantity").text = qty_str
        ET.SubElement(item, "FurncloudID").text = program_furncloud
        ET.SubElement(item, "Description").text = str(article.get("description", "") or "")


def _build_items_from_items(items_elem, items, program_name, program_furncloud):
    for idx, it in enumerate(items, start=1):
        modellnummer = _get_val(it, "modellnummer")
        artikelnummer = _get_val(it, "artikelnummer")
        furncloud = _get_val(it, "furncloud_id") or program_furncloud
        qty_val = _get_val(it, "menge", "1")
        try:
            qty_str = f"{float(qty_val):.1f}"
        except (ValueError, TypeError):
            qty_str = "1.0"
        item = ET.SubElement(items_elem, "Item")
        ET.SubElement(item, "Position").text = str(idx)
        ET.SubElement(item, "ModelNumber").text = _fix_article_id_ocr(modellnummer)
        ET.SubElement(item, "ArticleNumber").text = artikelnummer
        ET.SubElement(item, "Model").text = program_name
        ET.SubElement(item, "Quantity").text = qty_str
        ET.SubElement(item, "FurncloudID").text = furncloud
        ET.SubElement(item, "Description").text = ""

def export_xmls(data: Dict[str, Any], base_name: str, config: Config, output_dir: Path) -> List[Path]:
    """Generates both XML files and returns their paths. Filename base = kom_nr else kom_name else 'unknown' (no message_id)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_base = _effective_xml_base_name(data)
    p1 = generate_order_info_xml(data, effective_base, config, output_dir)
    p2 = generate_article_info_xml(data, effective_base, output_dir)
    return [p1, p2]

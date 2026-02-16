import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import re

from config import Config

try:
    from prompts_detail import MANUFACTURER_ILN_MAP as _MANUFACTURER_ILN_MAP
except Exception:
    _MANUFACTURER_ILN_MAP = {"staud": "4039262000004"}

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
    Uses detailed article data from second extraction if available,
    otherwise falls back to basic items array.
    """
    header = data.get("header", {})
    items = data.get("items", [])
    program_info = data.get("program") or {}
    if not isinstance(program_info, dict):
        program_info = {}
    articles = data.get("articles", [])
    
    # Determine if we have detailed article data
    use_detailed = bool(articles)
    
    # Root with namespace
    root = ET.Element("Documents", {"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    doc = ET.SubElement(root, "Document")
    orders = ET.SubElement(doc, "Orders")
    order = ET.SubElement(orders, "Order")
    
    ET.SubElement(order, "transaction_ID")  # Empty
    ET.SubElement(order, "Language").text = "de"
    
    prog = ET.SubElement(order, "Program")
    
    manufacturer_name = str(program_info.get("manufacturer_name", "") or "")
    manufacturer_iln = str(program_info.get("manufacturer_iln", "") or "")
    if manufacturer_name and not manufacturer_iln:
        manufacturer_iln = str(_MANUFACTURER_ILN_MAP.get(manufacturer_name.strip().lower(), "") or "")

    # Fallback for older/partial JSONs without program section: default to Staud for XXLUTZ/MÖMAX flows.
    if not manufacturer_name and not manufacturer_iln:
        store_name = _get_val(header, "store_name", "").strip().lower()
        if any(token in store_name for token in ("xxxlutz", "mömax", "moemax", "bdsk")):
            manufacturer_name = "Staud"
            manufacturer_iln = str(_MANUFACTURER_ILN_MAP.get("staud", "4039262000004") or "")

    # manufacturer and ILN from program; prog_id and progname empty
    ET.SubElement(prog, "manufacturer_longname").text = manufacturer_name
    ET.SubElement(prog, "iln_manufacturer").text = manufacturer_iln
    ET.SubElement(prog, "prog_id")
    ET.SubElement(prog, "progname")
    
    # Global remarks (furncloud id)
    furncloud_id = program_info.get("furncloud_id", "")
    if not furncloud_id:
        # Fallback: scan items for furncloud_id
        for item in items:
            val = _get_val(item, "furncloud_id")
            if val:
                furncloud_id = val
                break
    
    remarks = ET.SubElement(prog, "Remarks")
    if furncloud_id:
        ET.SubElement(remarks, "Remarkline").text = f"furncloud: [{furncloud_id}]"
    
    if use_detailed:
        # Use detailed articles from second extraction
        _build_lines_from_articles(prog, articles)
    else:
        # Fallback to basic items array
        _build_lines_from_items(prog, items)
    
    filename = f"OrderArticleInfo_{base_name}.xml"
    output_path = output_dir / filename
    
    # Prettify
    xml_str = _prettify_xml(root)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_str)
    
    return output_path


def _build_lines_from_articles(prog: ET.Element, articles: List[Dict[str, Any]]) -> None:
    """
    Build Line elements from detailed articles array.
    Only Article_ID and Quantity are populated; rest empty. Furncloud is only in Program Remarks.
    """
    for article in articles:
        line = ET.SubElement(prog, "Line")
        
        ET.SubElement(line, "GUID")
        ET.SubElement(line, "Article_ID").text = _fix_article_id_ocr(str(article.get("article_id", "")))
        ET.SubElement(line, "ArticleDescription")
        ET.SubElement(line, "Height")
        ET.SubElement(line, "Width")
        ET.SubElement(line, "Depth")
        cad = ET.SubElement(line, "CadData")
        for attr in ["px", "py", "pz", "dx", "dy", "dz", "rx", "ry", "rz"]:
            cad.set(attr, "0.0000")
        cad.set("IIx", "0")
        qty = article.get("quantity", 1)
        try:
            qty_str = f"{float(qty):.2f}"
        except (ValueError, TypeError):
            qty_str = "1.00"
        ET.SubElement(line, "Quantity").text = qty_str
        ET.SubElement(line, "Quantity_unit")
        ET.SubElement(line, "PriceGroup")
        ET.SubElement(line, "VzParentGuid")
        ET.SubElement(line, "PosParentGuid")
        ET.SubElement(line, "PosNr")
        ET.SubElement(line, "Remarks")
        props = ET.SubElement(line, "InternalProperties")
        for i in range(78):
            ET.SubElement(props, f"Propertie_{i}")
        sublines = ET.SubElement(line, "SubLines")
        subobj = ET.SubElement(sublines, "SubObj")
        ET.SubElement(subobj, "SubObjGuid")


def _build_lines_from_items(prog: ET.Element, items: List[Dict[str, Any]]) -> None:
    """
    Fallback: Build Line elements from basic items array.
    Only Article_ID (modellnummer-artikelnummer) and Quantity are populated; rest empty. Furncloud is only in Program Remarks.
    """
    for item in items:
        line = ET.SubElement(prog, "Line")
        modellnummer = _get_val(item, "modellnummer")
        artikelnummer = _get_val(item, "artikelnummer")
        if modellnummer and artikelnummer:
            article_id_str = f"{modellnummer}-{artikelnummer}"
        else:
            article_id_str = modellnummer or artikelnummer
        ET.SubElement(line, "GUID")
        ET.SubElement(line, "Article_ID").text = _fix_article_id_ocr(article_id_str)
        ET.SubElement(line, "ArticleDescription")
        ET.SubElement(line, "Height")
        ET.SubElement(line, "Width")
        ET.SubElement(line, "Depth")
        cad = ET.SubElement(line, "CadData")
        for attr in ["px", "py", "pz", "dx", "dy", "dz", "rx", "ry", "rz"]:
            cad.set(attr, "0.0000")
        cad.set("IIx", "0")
        qty_val = _get_val(item, "menge", "1")
        try:
            qty_str = f"{float(qty_val):.2f}"
        except (ValueError, TypeError):
            qty_str = "1.00"
        ET.SubElement(line, "Quantity").text = qty_str
        ET.SubElement(line, "Quantity_unit")
        ET.SubElement(line, "PriceGroup")
        ET.SubElement(line, "VzParentGuid")
        ET.SubElement(line, "PosParentGuid")
        ET.SubElement(line, "PosNr")
        ET.SubElement(line, "Remarks")
        props = ET.SubElement(line, "InternalProperties")
        for i in range(78):
            ET.SubElement(props, f"Propertie_{i}")
        sublines = ET.SubElement(line, "SubLines")
        subobj = ET.SubElement(sublines, "SubObj")
        ET.SubElement(subobj, "SubObjGuid")

def export_xmls(data: Dict[str, Any], base_name: str, config: Config, output_dir: Path) -> List[Path]:
    """Generates both XML files and returns their paths. Filename base = kom_nr else kom_name else 'unknown' (no message_id)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_base = _effective_xml_base_name(data)
    p1 = generate_order_info_xml(data, effective_base, config, output_dir)
    p2 = generate_article_info_xml(data, effective_base, output_dir)
    return [p1, p2]

from normalize import normalize_output
from xml_exporter import export_xmls
from config import Config
from pathlib import Path

def test_full_pipeline_iln():
    data = {
        "header": {
            "lieferanschrift": "Leopoldshöher Str. 1-11\n32791 Lage / Pottenhausen",
            "kundennummer": "12345",
            "kom_nr": "KOM123",
            "bestelldatum": "2024-01-20"
        },
        "items": [
            {"artikelnummer": "ART1", "modellnummer": "MOD1", "menge": "1"}
        ]
    }
    
    warnings = []
    normalized = normalize_output(data, "test_msg", "2024-01-20T10:00:00", True, warnings)
    
    print("Normalized Header ILN:", normalized.get("header", {}).get("iln"))
    
    config = Config()
    output_dir = Path("./test_output_iln")
    export_xmls(normalized, "test_base", config, output_dir)
    
    # Check XML content
    xml_path = output_dir / "OrderInfo_test_base.xml"
    if xml_path.exists():
        with open(xml_path, "r", encoding="utf-8") as f:
            content = f.read()
            if 'ILN="9007019005065"' in content:
                print("XML Export SUCCESS: ILN found in XML")
            else:
                print("XML Export FAILURE: ILN not found or incorrect in XML")
                print(content)

if __name__ == "__main__":
    test_full_pipeline_iln()

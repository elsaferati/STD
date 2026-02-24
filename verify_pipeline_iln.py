from normalize import normalize_output
from xml_exporter import export_xmls
from config import Config
from pathlib import Path


def test_full_pipeline_iln():
    data = {
        "header": {
            "lieferanschrift": "",
            "kundennummer": "12345",
            "kom_nr": "KOM123",
            "bestelldatum": "2024-01-20",
            "adressnummer": "999",
            "iln": "4040051007005",
            "iln_anl": "4040051007005",
        },
        "items": [
            {"artikelnummer": "ART1", "modellnummer": "MOD1", "menge": "1"}
        ],
    }

    warnings = []
    normalized = normalize_output(
        data, "test_msg", "2024-01-20T10:00:00", True, warnings
    )

    header = normalized.get("header", {})
    print("Normalized Header ILN:", header.get("iln"))
    print("Normalized Header ILN-ANL:", header.get("iln_anl"))
    print("Normalized Header Adressnummer:", header.get("adressnummer"))

    iln_val = (
        header.get("iln", {}).get("value")
        if isinstance(header.get("iln"), dict)
        else header.get("iln")
    )
    iln_anl_val = (
        header.get("iln_anl", {}).get("value")
        if isinstance(header.get("iln_anl"), dict)
        else header.get("iln_anl")
    )
    adress_val = (
        header.get("adressnummer", {}).get("value")
        if isinstance(header.get("adressnummer"), dict)
        else header.get("adressnummer")
    )

    assert iln_val == "4040051007005", "ILN should remain in header.iln"
    assert iln_anl_val == "4040051007005", "ILN-Anl should remain in header.iln_anl"
    assert adress_val == "999", "adressnummer should not be overwritten by iln"

    config = Config()
    output_dir = Path("./test_output_iln")
    export_xmls(normalized, "test_base", config, output_dir)

    # Check XML content
    xml_path = output_dir / "OrderInfo_test_base.xml"
    if xml_path.exists():
        with open(xml_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "<OrderInformations" in content:
                print("XML Export SUCCESS: OrderInfo generated.")
            else:
                print("XML Export FAILURE: OrderInfo missing.")
                print(content)


if __name__ == "__main__":
    test_full_pipeline_iln()

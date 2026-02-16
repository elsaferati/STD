import json
from pathlib import Path
from unittest.mock import MagicMock
from pipeline import process_message, ProcessedResult
from normalize import normalize_output
from config import Config
from email_ingest import IngestedEmail

def test_human_review_preservation():
    # Mock configuration
    config = Config.from_env()
    config.output_dir = Path("./test_output_human_loop")
    config.output_dir.mkdir(exist_ok=True)

    # Mock Extractor
    extractor = MagicMock()
    
    # Mock LLM Response with human_review_needed = True
    mock_response = {
        "header": {
            "kundennummer": {"value": "12345", "source": "pdf", "confidence": 0.9},
            "human_review_needed": {"value": True, "source": "pdf", "confidence": 1.0}
        },
        "items": [],
        "warnings": [],
        "errors": []
    }
    
    # Mock extraction method
    extractor.extract.return_value = json.dumps(mock_response)

    # Create dummy message
    message = IngestedEmail(
        message_id="test_human_review",
        received_at="2025-01-01T12:00:00",
        subject="Test Human Review",
        sender="test@example.com",
        body_text="Test body",
        attachments=[]
    )

    # Run processing
    result = process_message(message, config, extractor)
    
    # Check if normalized data has the flag
    print("Normalized Data Human Review:", result.data["header"].get("human_review_needed"))
    
    # Verify the value is strictly True or boolean-like
    flag = result.data["header"].get("human_review_needed", {}).get("value")
    if flag is True:
        print("SUCCESS: Human review flag preserved as True.")
    else:
        print(f"FAILURE: Human review flag is {flag}")

    # Write to disk effectively simulating the app
    output_path = config.output_dir / "test_human_review.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.data, f, indent=2)

    print(f"Written to {output_path}")

if __name__ == "__main__":
    test_human_review_preservation()

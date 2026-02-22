## Hybrid PDF Input (Images + PDF Text) for Code Accuracy

### Summary
Add **digital text extraction from PDFs** (using PyMuPDF) and send that text **alongside each rendered PDF page image** in the same OpenAI request. Update prompts so the model uses the PDF text **only to verify/correct `modellnummer` + `artikelnummer`** (and `article_id` in the detail call), while keeping **item count + `menge` sourced from the image**.

---

## Decisions Locked In (per your answers)
- **PDF strategy:** keep the current **PDF→images** flow (Poppler/`pdftoppm`) and additionally extract PDF text locally.
- **Validation scope:** only validate **`modellnummer` + `artikelnummer`** (and detail extraction `article_id`) against PDF text; **quantities/item count must come from image**.
- **Verification method:** **prompt-only** (no extra post-processing validator).

---

## Implementation Details

### 1) Extract PDF page text (PyMuPDF)
- Add a helper in `pipeline.py`:
  - Input: `pdf_bytes`, `max_pages`, `max_chars_per_page`
  - Output: list of page texts indexed by page number (1-based in labels, 0-based internally)
- Use `fitz.open(stream=pdf_bytes, filetype="pdf")` and `page.get_text()` for each page up to `MAX_PDF_PAGES`.

**Truncation rule**
- Introduce a per-page cap to prevent huge prompts:
  - `MAX_PDF_TEXT_CHARS_PER_PAGE` (default: `8000`)
  - If a page’s extracted text exceeds the cap, truncate and add a pipeline warning like:
    - `"PDF text truncated for <filename> page <n> to <cap> chars"`

**Failure rule**
- If extraction fails for a PDF, keep processing images as today and add a warning:
  - `"PDF text extraction failed for <filename>: <error>"`

---

### 2) Produce a “PDF text by image name” map during image preparation
- Change `pipeline._prepare_images(...)` to return **two values**:
  1. `images: list[ImageInput]` (unchanged behavior)
  2. `pdf_text_by_image_name: dict[str, str]`
- While converting each PDF to images, also extract its page texts and attach the right page text to the right image by parsing the `-<page>` suffix in the PNG filename.
- When `MAX_IMAGES` truncates the final `images` list, also drop any corresponding entries from `pdf_text_by_image_name` to keep them consistent.

---

### 3) Send PDF text + image together in OpenAI request
- Update `openai_extract.py`:
  - Extend `OpenAIExtractor.extract_with_prompts(... )` with an optional parameter:
    - `page_text_by_image_name: dict[str, str] | None = None`
  - Extend `OpenAIExtractor.extract_article_details(...)` similarly.
- In both methods, when iterating images:
  - Add the existing “Image idx source/name …” text
  - If `image.name` exists in `page_text_by_image_name`, add an `input_text` block like:
    - `"PDF extracted text for this page (digital, not OCR):\n<text>"`
  - Then add the `input_image`.

This ensures the model sees **(label → digital text → image)** per PDF page.

---

### 4) Update prompts to enforce the “verify codes only” rule
Update these files:
- `prompts.py`
- `prompts_detail.py`
- `prompts_momax_bg.py`

Add a short, explicit section (near the top of user instructions) stating:

1) **What the model receives**
- For PDF pages: an image of the page **and** the page’s **extracted digital PDF text**.

2) **What to use PDF text for**
- Use PDF text **only** to confirm/correct:
  - `items[*].modellnummer`
  - `items[*].artikelnummer`
  - (detail extraction) `articles[*].article_id`

3) **What NOT to use PDF text for**
- Do **not** use PDF text to determine:
  - number of item rows
  - `items[*].menge`  
  These must be read from the **image table**.

4) **Confusable character rule (fix the current pitfall)**
- Replace the current “zero not O” wording with a safer rule:
  - “Distinguish **letter `O`** vs **digit `0`**. Some codes contain both (e.g. `OJ00` starts with letter `O` and ends with two zeros). When PDF extracted text is available, copy codes from it exactly.”

---

### 5) Wire it into the pipeline (main + detail extraction)
- In `pipeline.process_message(...)`:
  - Replace `images = _prepare_images(...)` with:
    - `images, pdf_text_by_image_name = _prepare_images(...)`
  - Pass `page_text_by_image_name=pdf_text_by_image_name` into:
    - `extractor.extract_with_prompts(...)`
    - `extractor.extract_article_details(...)`

---

## Config / Env Vars
- Add to `config.py`:
  - `max_pdf_text_chars_per_page: int`
  - Read from env: `MAX_PDF_TEXT_CHARS_PER_PAGE` (default `8000`)
  - If set to `0`, skip extracting/sending PDF text (feature-off switch)
- Document in `README.md` config table.

---

## Testing / Acceptance Criteria (manual + repo scripts)
1) **PDF with embedded text**
- Run your normal pipeline on a known furnplan PDF where you’ve seen `OJ00`-style issues.
- Confirm the model output no longer flips `OJ00` → `0J00`.

2) **Scanned PDF (no embedded text)**
- Ensure extraction still works image-only and no crashes; warnings should note missing/empty PDF text if applicable.

3) **Multi-attachment mix**
- PDF + image attachments: confirm images still sent, and only PDF-derived images get adjacent PDF text blocks.

4) **Detail extraction**
- Verify `article_id` comes out with correct characters when PDF text exists, while quantities remain image-derived.

---

## Notes / Assumptions
- PyMuPDF (`fitz`) is already a dependency and used elsewhere in the repo (routing), so we reuse it.
- This improves accuracy substantially for **digitally-generated PDFs**; for scanned PDFs, the extracted text may be empty and the model will rely on vision as before.

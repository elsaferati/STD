# Multi‑Client Extraction Branches + OpenAI Routing

## Summary
Implement a runtime “branch” system where **only the extraction step** (prompts + any extraction-specific fixups) varies per client, while the shared backend flow (Kundennummer lookup, Excel search, normalization, delivery logic, XML export, reply-email logic, etc.) remains unchanged. Add an **OpenAI classifier call at the start of processing** to route each incoming message to the correct client branch.

Success means:
- Existing XXLUTZ/MÖMAX extraction continues to work unchanged (now as `xxxlutz_default` branch).
- Existing `momax_bg` special-case remains correct and is routable.
- Adding a new client is “add one prompts/module + register branch,” no pipeline rewrites.
- If routing is uncertain/unknown, the system uses the default prompt **and forces `human_review_needed=true`**.

---

## 1) Define a Branch/Registry Abstraction
### Add file: `extraction_branches.py`
Create a small branch registry that describes each client extraction profile.

**Data model**
- `DEFAULT_BRANCH_ID = "xxxlutz_default"`
- `@dataclass(frozen=True) class ExtractionBranch:`
  - `id: str` (ASCII, stable identifier; e.g. `xxxlutz_default`, `momax_bg`, `segmueller`)
  - `label: str` (human readable)
  - `description: str` (1–2 lines for classifier prompt)
  - `system_prompt: str`
  - `build_user_instructions: Callable[[list[str]], str]` (takes `source_priority`)
  - `enable_detail_extraction: bool` (default `False` unless explicitly needed)
  - `is_momax_bg: bool` (only `True` for the BG branch to preserve existing normalization behavior)
  - `hard_detector: Callable[[list[Attachment]], bool] | None`
    - Use this for “fail-closed” deterministic detectors (initially only `momax_bg.is_momax_bg_two_pdf_case`).

**Registry**
- Define `BRANCHES: dict[str, ExtractionBranch]` with at least:
  1. `xxxlutz_default`
     - `system_prompt = prompts.SYSTEM_PROMPT`
     - `build_user_instructions = prompts.build_user_instructions`
     - `enable_detail_extraction = True` (keep existing behavior)
     - `is_momax_bg = False`
  2. `momax_bg`
     - `system_prompt = prompts.SYSTEM_PROMPT` (as today)
     - `build_user_instructions = prompts_momax_bg.build_user_instructions_momax_bg`
     - `enable_detail_extraction = False` (keep existing behavior)
     - `is_momax_bg = True`
     - `hard_detector = momax_bg.is_momax_bg_two_pdf_case`

**Helpers**
- `def get_branch(branch_id: str) -> ExtractionBranch:` return branch if known else default.

---

## 2) Add an OpenAI Router (Classifier)
### Add file: `extraction_router.py`
This module is responsible for *one thing*: return a routing decision for a message.

**Config knobs (env + `Config`)**
Extend `config.py` / `Config` with:
- `router_enabled: bool` (env `ROUTER_ENABLED`, default `true`)
- `router_min_confidence: float` (env `ROUTER_MIN_CONFIDENCE`, default `0.75`)
- (optional but recommended) `router_max_body_chars: int` (env `ROUTER_MAX_BODY_CHARS`, default `4000`)
- (optional) `router_max_pdf_preview_chars: int` (env `ROUTER_MAX_PDF_PREVIEW_CHARS`, default `2000`)

**Decision model**
- `@dataclass class RouteDecision:`
  - `selected_branch_id: str` (final branch used)
  - `classifier_branch_id: str` (raw model output, or `"unknown"`)
  - `confidence: float`
  - `reason: str` (short)
  - `forced_by_detector: bool`
  - `used_fallback: bool` (true when low-confidence/unknown/error → default branch)

**Attachment preview extraction (text-only)**
- Build a text summary for routing input:
  - Message fields: `message_id`, `received_at`, `subject`, `sender`
  - Email body: first `router_max_body_chars` chars
  - Attachments list: `filename`, `content_type`, `size_bytes`
  - For each PDF attachment: extract **first page text** via PyMuPDF (`fitz`), normalize whitespace, truncate to `router_max_pdf_preview_chars`.
  - Include `momax_bg_detector = True/False` from hard detector.

**Router prompt**
- System prompt: “You are a routing classifier. Choose exactly one `branch_id` from this list: …”
- Dynamically embed the list of branches from `extraction_branches.BRANCHES` (id + description).
- Require strict JSON output:
  ```json
  { "branch_id": "xxxlutz_default|momax_bg|…|unknown", "confidence": 0.0, "reason": "…" }
  ```
- Rules:
  - If it doesn’t match any known branch, return `"unknown"` with low confidence.
  - If `momax_bg_detector=true`, return `"momax_bg"` with confidence `1.0` (still overridden server-side if needed).

**Routing algorithm**
`def route_message(message: IngestedEmail, config: Config, extractor: OpenAIExtractor) -> RouteDecision:`
1. Compute `forced_branch_id` from any `hard_detector` in the registry (initially only BG).
2. If `not config.router_enabled`:
   - Return forced branch if present else default, with `used_fallback=True` (and `forced_by_detector` if applicable).
3. Else call OpenAI once using `extractor.complete_text(router_system_prompt, routing_user_text)`.
4. Parse JSON via `openai_extract.parse_json_response`.
5. Validate:
   - `branch_id` is string
   - `confidence` is float in `[0,1]`
   - `branch_id` is either `"unknown"` or present in `BRANCHES`
6. Select:
   - If `forced_branch_id` exists → use it (`forced_by_detector=True`, `used_fallback=False`).
   - Else if `branch_id` known AND `confidence >= router_min_confidence` → use it.
   - Else → use default branch with `used_fallback=True`.
7. Return `RouteDecision` including raw classifier output for auditing.

**Audit trail requirement**
- Always produce a concise warning string for the pipeline, e.g.:
  - `Routing: selected=momax_bg confidence=0.93 forced=false fallback=false`
  - `Routing: selected=xxxlutz_default confidence=0.41 forced=false fallback=true (unknown/low confidence)`

---

## 3) Make Extraction Branch-Selectable (Prompts + System Prompt)
### Update: `openai_extract.py`
Goal: allow pipeline to call the same extraction code path with different prompts.

**Changes**
- Store temperature and actually use it:
  - In `__init__`: `self.temperature = temperature`
  - Add `temperature=self.temperature` to:
    - `client.responses.create(...)`
    - `client.chat.completions.create(...)`
- Add a new method (public):
  - `def extract_with_prompts(self, *, message_id, received_at, email_text, images, source_priority, subject="", sender="", system_prompt: str, user_instructions: str) -> str`
  - Build the same `content` list as `extract()` but use the passed `user_instructions`.
  - Call `_create_response_with_prompt(content, system_prompt)` and return `_response_to_text`.

**Keep backward compatibility**
- Keep existing `extract()` method unchanged (or internally delegate to `extract_with_prompts` using `prompts.SYSTEM_PROMPT` + `prompts.build_user_instructions`).

---

## 4) Update the Pipeline to Use Router + Branches
### Update: `pipeline.py`
Replace the current “BG vs default” branching with router-driven branch selection, while keeping the downstream steps intact.

**At the start of `process_message()`**
1. Truncate email body as today.
2. Call `route = extraction_router.route_message(message, config, extractor)`.
3. Resolve `branch = extraction_branches.get_branch(route.selected_branch_id)`.
4. Append routing audit line to `warnings`.

**Extraction call (branch-controlled)**
- Prepare images as today (`images = _prepare_images(...)`).
- Build `user_instructions = branch.build_user_instructions(config.source_priority)`.
- Call:
  - `response_text = extractor.extract_with_prompts(..., system_prompt=branch.system_prompt, user_instructions=user_instructions)`
- Keep existing retry loop (3 attempts) around the extraction call.

**Branch-specific extraction fixups**
Keep existing MOMAX BG-only fixups, but key them off `branch.is_momax_bg` (or `branch.id == "momax_bg"`):
- Pre-normalization: enforce `header.kom_name` empty derived, remove `kom_name_pdf` if present (same as now).
- Post-normalization: repair `kom_nr` and `bestelldatum` from PDF suffix; reset `reply_needed` derived to `False` (same as now).

**Shared backend stays shared**
After normalization, keep the rest of the pipeline as-is, with only these generalized conditions:
- Pass `is_momax_bg=branch.is_momax_bg` into `normalize_output(...)`.
- AI customer match: run for all branches except BG (keep current behavior, but express as `if not branch.is_momax_bg: ...`).
- Detail extraction (second call): run only when `branch.enable_detail_extraction` is true (replacing `(not use_momax_bg)`).

**Fallback behavior (your selected requirement)**
If `route.used_fallback` is `True`:
- Force `header.human_review_needed.value = True` (do not overwrite if it’s already true).
- Set source to `derived`, confidence `1.0`, `derived_from="routing_fallback"`.
- Add a warning like `Routing fallback: forced human_review_needed=true`.

---

## 5) How to Add a New Client Branch (Workflow Doc)
### Update: `README.md`
Add a “Adding a new client” section:
1. Create `prompts_<client_id>.py` with:
   - `SYSTEM_PROMPT_<client>` (optional; or reuse existing generic one)
   - `build_user_instructions_<client>(source_priority)`
2. Register a new `ExtractionBranch` entry in `extraction_branches.py`:
   - `id="<client_id>"`
   - `description` including the key identifying signals (sender domain, header text, etc.)
   - Decide `enable_detail_extraction` (default `False` unless needed)
3. Add sample cases under a new folder (e.g. `CLIENT CASES/<client_id>/`) for manual verification.
4. Run the verify scripts / manual pipeline run on samples.

Also document env vars:
- `ROUTER_ENABLED`
- `ROUTER_MIN_CONFIDENCE`
- (if implemented) `ROUTER_MAX_BODY_CHARS`, `ROUTER_MAX_PDF_PREVIEW_CHARS`

---

## 6) Update/Extend Local Verification Scripts
### Update existing scripts using `MagicMock` extractor
Because routing adds a new OpenAI call (`complete_text`) at the start, update:
- `verify_momax_bg.py`
- `verify_reply_needed.py`
- `verify_human_review.py`

Approach (choose one and implement consistently):
- Preferred: set `extractor.complete_text.return_value = json.dumps({"branch_id":"xxxlutz_default","confidence":1.0,"reason":"test"})` (or `momax_bg` for BG tests).
- Alternative: set `ROUTER_ENABLED=false` inside the script (env) to bypass routing during these verifications.

### Add a small router verification helper (optional but recommended)
Add `verify_routing.py` that:
- Mocks `complete_text` to return:
  1. valid branch high confidence → routes to that branch
  2. unknown/low confidence → routes to default + forces human review
  3. malformed JSON → routes to default + forces human review
- Asserts the warning line and `human_review_needed` behavior.

---

## Assumptions / Defaults Locked In
- “Branch” means runtime extraction profile (not git branches).
- Router is **text-only**: subject/sender/body + PDF first-page text previews + attachment metadata.
- Router chooses among **explicit registered client IDs**; it may output `"unknown"`.
- If routing is low-confidence/unknown/error: use `xxxlutz_default` extraction **and force** `human_review_needed=true`.
- MOMAX BG is protected with a deterministic detector (hard override), so it won’t regress if the classifier misroutes.

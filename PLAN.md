# Add Gemini Post-Generation Validation

## Summary
- Add a second AI step after extraction and XML assembly that compares the source order evidence against the finalized XML output and flags likely mistakes.
- Use Gemini as a dedicated validator, not as a replacement for the current OpenAI extraction path.
- Surface the result as a separate persisted review state labeled `Gemini Review`, instead of overloading the existing order lifecycle statuses like `reply`, `waiting_for_reply`, or `client_replied`.
- Run it for all newly processed orders, including follow-up/reply updates. With the chosen inline-only source handling, later manual edits will mark the prior Gemini result `stale` rather than rerunning Gemini.

## Implementation Changes
- Add Gemini config and dependency:
  - Add `google-genai` to `requirements.txt`.
  - Add env/config fields: `GEMINI_API_KEY`, `GEMINI_MODEL` default `gemini-2.5-flash`, `GEMINI_VALIDATION_ENABLED`, `GEMINI_VALIDATION_TIMEOUT_SECONDS`, `GEMINI_VALIDATION_MAX_EMAIL_CHARS`, `GEMINI_VALIDATION_MAX_ATTACHMENTS`.
- Add a dedicated validator module:
  - Create a small `GeminiValidator` wrapper using the native Google SDK.
  - Input bundle: branch id, subject, sender, email body, PDF attachments when present, finalized XML text for both XMLs, and a compact normalized header/items snapshot.
  - Output schema: `validation_status` (`passed|flagged|skipped|error`), `summary`, and `issues[]` with stable fields like `severity`, `scope`, `field_path`, `source_evidence`, `expected_value`, `xml_value`, `reason`.
  - Prompt Gemini to compare only what is explicitly present in the evidence and never invent missing fields.
- Refactor XML generation slightly so validation uses the exact final XML payload:
  - Split XML creation into “build XML strings in memory” and “write XML files”.
  - Use the in-memory XML strings for Gemini, then write the same strings to disk.
- Wire validation into processing flows:
  - In normal ingestion, run Gemini after normalized order data and XML payloads are finalized, before the final order persistence step.
  - In `process_client_reply` and `process_new_email_followup`, run the same validator on the updated order payload and regenerated XML.
  - If Gemini returns `flagged`, keep the XML files but persist the finding and place the order in `Gemini Review`.
  - If Gemini errors or times out, persist `validation_status='error'` and continue; validation must not break order ingestion.
- Persist validation separately from core order status:
  - Add order-level summary columns such as `validation_status`, `validation_summary`, `validation_checked_at`, `validation_provider`, `validation_model`, and `validation_stale_reason`.
  - Add a new `order_validation_runs` table keyed by `order_id` and `revision_id` to store the full structured Gemini result for history and detail-page display.
  - Do not replace the current `status` column. `Gemini Review` is a separate queue/filter backed by `validation_status IN ('flagged','stale')`.
- Extend API and UI surfaces:
  - Add `validation_status`, `validation_summary`, `validation_checked_at`, and `validation_issues` to order detail payloads.
  - Add `validation_status` filter support and a `gemini_review` count to the orders list API.
  - Add a `Gemini Review` tab in the orders UI.
  - Show a validation badge, summary, timestamp, and issue list on the order detail page.
  - Add `POST /api/orders/<order_id>/validation/resolve` so a reviewer can clear the Gemini finding with a note after checking/fixing the order.
- Handle later edits with the chosen inline-only model:
  - On manual save or manual XML regeneration, do not rerun Gemini.
  - If the order already has a Gemini result, mark it `stale` and keep it in the `Gemini Review` queue until a human resolves it.
  - Historical orders are not backfilled because the original email/PDF sources are not stored.

## Public API / Type Additions
- New config fields: `gemini_*`.
- New order fields in API responses and CSV/export payloads:
  - `validation_status`
  - `validation_summary`
  - `validation_checked_at`
  - `validation_provider`
  - `validation_model`
  - `validation_issues`
  - `validation_stale_reason`
- New API endpoint:
  - `POST /api/orders/<order_id>/validation/resolve`
- New persisted validation states:
  - `not_run`
  - `passed`
  - `flagged`
  - `stale`
  - `skipped`
  - `error`
  - `resolved`

## Test Plan
- Mocked validator tests for `passed`, `flagged`, `skipped`, and `error`.
- Ingestion-path tests verifying:
  - flagged orders enter `Gemini Review`
  - passed orders do not
  - validator failures do not stop XML generation or order persistence
- Reply/follow-up tests verifying Gemini runs on updated orders too.
- Persistence/API tests verifying new fields, filters, counts, and resolve endpoint behavior.
- Manual edit tests verifying existing Gemini results become `stale`.
- UI verification for:
  - `Gemini Review` tab/count
  - detail-page validation report
  - resolve action
  - XML download still available while the order is in Gemini Review

## Assumptions and Defaults
- Default model: `gemini-2.5-flash`.
- Native Google SDK is preferred over OpenAI-compat mode because this validator needs direct Files API support and structured schema output.
- Validation compares PDF + email + XML when PDFs exist; if there is no PDF, it falls back to email-vs-XML and may return `skipped` when evidence is insufficient.
- Soft gate means a separate review queue/state, not a hard block on XML file download.
- Official feasibility references:
  - [Gemini API quickstart](https://ai.google.dev/gemini-api/docs/quickstart)
  - [Gemini Files API](https://ai.google.dev/gemini-api/docs/files)
  - [Structured output](https://ai.google.dev/gemini-api/docs/structured-output)
  - [OpenAI compatibility guidance](https://ai.google.dev/gemini-api/docs/openai)

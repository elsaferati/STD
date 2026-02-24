from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from openai import OpenAI

from prompts import SYSTEM_PROMPT, build_user_instructions
from prompts_verify_items import (
    VERIFY_ITEMS_SYSTEM_PROMPT,
    build_verify_items_instructions,
)


@dataclass
class ImageInput:
    name: str
    source: str
    data_url: str


def _verification_page_sort_key(page_name: str) -> tuple[int, str]:
    stem = Path(page_name or "").stem
    match = re.search(r"-(\d+)$", stem)
    if match:
        try:
            return int(match.group(1)), page_name or ""
        except ValueError:
            pass
    return (10**9), page_name or ""


def _response_to_text(response: Any) -> str:
    if hasattr(response, "output_text") and response.output_text:
        return response.output_text
    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        if message is None and isinstance(first, dict):
            message = first.get("message")
        if message:
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                content = message.get("content")
            if isinstance(content, list):
                parts = []
                for part in content:
                    text = getattr(part, "text", None)
                    if text is None and isinstance(part, dict):
                        text = part.get("text")
                    if text:
                        parts.append(text)
                return "".join(parts)
            if content:
                return str(content)
    if isinstance(response, dict):
        if "output_text" in response:
            return response["output_text"] or ""
        output = response.get("output", [])
    else:
        output = getattr(response, "output", [])

    for item in output:
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content", [])
        if not content:
            continue
        for part in content:
            text = getattr(part, "text", None)
            if text is None and isinstance(part, dict):
                text = part.get("text")
            if text:
                return text
    return ""


class OpenAIExtractor:
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float,
        reasoning_effort: str,
        max_output_tokens: int,
    ) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self._supports_response_format = True

    def extract(
        self,
        message_id: str,
        received_at: str,
        email_text: str,
        images: list[ImageInput],
        source_priority: list[str],
        subject: str = "",
        sender: str = "",
    ) -> str:
        user_instructions = build_user_instructions(source_priority)
        return self.extract_with_prompts(
            message_id=message_id,
            received_at=received_at,
            email_text=email_text,
            images=images,
            source_priority=source_priority,
            subject=subject,
            sender=sender,
            system_prompt=SYSTEM_PROMPT,
            user_instructions=user_instructions,
        )

    def extract_with_prompts(
        self,
        *,
        message_id: str,
        received_at: str,
        email_text: str,
        images: list[ImageInput],
        source_priority: list[str],
        subject: str = "",
        sender: str = "",
        system_prompt: str,
        user_instructions: str,
        page_text_by_image_name: dict[str, str] | None = None,
    ) -> str:
        content = [
            {"type": "input_text", "text": user_instructions},
            {
                "type": "input_text",
                "text": (
                    f"Message-ID: {message_id}\n"
                    f"Received-At: {received_at}\n\n"
                    f"Subject: {subject}\n"
                    f"Sender: {sender}\n\n"
                    f"Email body (raw text):\n{email_text or ''}"
                ),
            },
        ]

        for idx, image in enumerate(images, start=1):
            content.append(
                {
                    "type": "input_text",
                    "text": f"Image {idx} source: {image.source}; name: {image.name}",
                }
            )
            page_text = (
                page_text_by_image_name.get(image.name, "")
                if page_text_by_image_name
                else ""
            )
            if page_text:
                content.append(
                    {
                        "type": "input_text",
                        "text": (
                            "PDF extracted text for this page (digital, not OCR):\n"
                            f"{page_text}"
                        ),
                    }
                )
            content.append({"type": "input_image", "image_url": image.data_url})

        response = self._create_response_with_prompt(content, system_prompt)

        return _response_to_text(response)

    def verify_items_from_text(
        self,
        items_snapshot: list[dict[str, Any]],
        page_text_by_image_name: dict[str, str] | None = None,
        verification_profile: str = "porta",
    ) -> str:
        user_instructions = build_verify_items_instructions(verification_profile)
        content = [
            {"type": "input_text", "text": user_instructions},
            {
                "type": "input_text",
                "text": (
                    "Current extracted items snapshot (use line_no as stable key):\n"
                    f"{json.dumps(items_snapshot, ensure_ascii=False, indent=2)}"
                ),
            },
        ]

        usable_page_texts: list[tuple[str, str]] = []
        if page_text_by_image_name:
            for page_name, page_text in page_text_by_image_name.items():
                text = str(page_text or "")
                if text.strip():
                    usable_page_texts.append((page_name, text))

        usable_page_texts.sort(key=lambda item: _verification_page_sort_key(item[0]))
        for idx, (page_name, page_text) in enumerate(usable_page_texts, start=1):
            content.append(
                {
                    "type": "input_text",
                    "text": f"PDF text page {idx}: {page_name}",
                }
            )
            content.append(
                {
                    "type": "input_text",
                    "text": (
                        "Digital PDF text for this page (no image evidence is provided):\n"
                        f"{page_text}"
                    ),
                }
            )

        response = self._create_response_with_prompt(content, VERIFY_ITEMS_SYSTEM_PROMPT)
        return _response_to_text(response)

    def complete_text(self, system_prompt: str, user_text: str) -> str:
        """
        Single text-only completion (system + user message, no images).
        Used e.g. by AI customer-match fallback. Returns the assistant text.
        """
        content = [{"type": "input_text", "text": user_text}]
        response = self._create_response_with_prompt(content, system_prompt)
        return _response_to_text(response)

    def _create_response(self, content: list[dict[str, Any]]) -> Any:
        """Create response using the default SYSTEM_PROMPT."""
        return self._create_response_with_prompt(content, SYSTEM_PROMPT)

    def _create_response_with_prompt(self, content: list[dict[str, Any]], system_prompt: str) -> Any:
        """Create response using a specified system prompt."""
        try:
            return self._responses_create_with_prompt(content, system_prompt)
        except AttributeError:
            return self._chat_fallback_with_prompt(content, system_prompt)

    def _chat_fallback_with_prompt(self, content: list[dict[str, Any]], system_prompt: str) -> Any:
        """Fallback to chat completions API with custom system prompt."""
        chat_content = []
        for part in content:
            if part.get("type") == "input_text":
                chat_content.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "input_image":
                chat_content.append(
                    {"type": "image_url", "image_url": {"url": part.get("image_url", "")}}
                )

        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chat_content},
            ],
            "max_tokens": self.max_output_tokens,
        }

        try:
            return self.client.chat.completions.create(**params)
        except Exception:
            raise

    def _responses_create_with_prompt(self, content: list[dict[str, Any]], system_prompt: str) -> Any:
        """Use responses API with custom system prompt."""
        params: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": content},
            ],
            "temperature": self.temperature,
            "reasoning": {"effort": self.reasoning_effort},
            "max_output_tokens": self.max_output_tokens,
        }
        if self._supports_response_format:
            params["response_format"] = {"type": "json_object"}

        try:
            return self.client.responses.create(**params)
        except TypeError as exc:
            message = str(exc)
            if "response_format" in message:
                self._supports_response_format = False
                params.pop("response_format", None)
                return self.client.responses.create(**params)
            raise
        except Exception as exc:
            message = str(exc)
            retried = False
            if "response_format" in message and "Unsupported parameter" in message:
                self._supports_response_format = False
                params.pop("response_format", None)
                retried = True
            if retried:
                return self.client.responses.create(**params)
            raise


def parse_json_response(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])

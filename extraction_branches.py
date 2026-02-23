from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from email_ingest import Attachment
import momax_bg
import prompts
import prompts_momax_bg
import prompts_porta

DEFAULT_BRANCH_ID = "xxxlutz_default"


@dataclass(frozen=True)
class ExtractionBranch:
    id: str
    label: str
    description: str
    system_prompt: str
    build_user_instructions: Callable[[list[str]], str]
    enable_detail_extraction: bool = False
    enable_item_code_verification: bool = False
    is_momax_bg: bool = False
    hard_detector: Callable[[list[Attachment]], bool] | None = None


BRANCHES: dict[str, ExtractionBranch] = {
    "xxxlutz_default": ExtractionBranch(
        id="xxxlutz_default",
        label="XXXLutz Default",
        description=(
            "Default XXLutz/Moemax extraction profile for standard emails and"
            " furnplan-style attachments."
        ),
        system_prompt=prompts.SYSTEM_PROMPT,
        build_user_instructions=prompts.build_user_instructions,
        enable_detail_extraction=True,
        is_momax_bg=False,
    ),
    "momax_bg": ExtractionBranch(
        id="momax_bg",
        label="MOMAX BG",
        description=(
            "Bulgaria MOMAX/MOEMAX/AIKO split-order profile with BG-specific"
            " extraction rules and downstream normalization."
        ),
        system_prompt=prompts.SYSTEM_PROMPT,
        build_user_instructions=prompts_momax_bg.build_user_instructions_momax_bg,
        enable_detail_extraction=False,
        is_momax_bg=True,
        hard_detector=momax_bg.is_momax_bg_two_pdf_case,
    ),
    "porta": ExtractionBranch(
        id="porta",
        label="Porta",
        description=(
            "Porta orders (email + PDF) with second-pass item-code verification."
        ),
        system_prompt=prompts_porta.PORTA_SYSTEM_PROMPT,
        build_user_instructions=prompts_porta.build_user_instructions_porta,
        enable_detail_extraction=False,
        enable_item_code_verification=True,
        is_momax_bg=False,
    ),
}


def get_branch(branch_id: str) -> ExtractionBranch:
    return BRANCHES.get((branch_id or "").strip(), BRANCHES[DEFAULT_BRANCH_ID])

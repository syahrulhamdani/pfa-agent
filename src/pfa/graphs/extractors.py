"""Gemini-backed extraction and correction parsing, via structured output."""

import base64

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from pfa.core.exceptions import LLMError
from pfa.schemas.extraction import CorrectionResult, ExtractedReceipt
from pfa.schemas.transactions import PendingTransaction

EXTRACT_PROMPT = (
    "Read this receipt and return its fields. Only report what is clearly visible: "
    "if a field is blurry, cut off or absent, return null for it. Never guess an "
    "amount, date or merchant. Choose the category from this list only: {categories}. "
    "The description should say briefly what was bought."
)

CORRECTION_PROMPT = (
    "A user is confirming a receipt that was read automatically.\n"
    "Current values: {current}\n"
    "Allowed categories: {categories}\n"
    "The user's cards: {cards}\n"
    "User message: {text!r}\n"
    "If the message corrects or supplies a value of this receipt, set "
    "is_correction to true and fill only the fields it changes. Otherwise, such as "
    "for a question or small talk, set is_correction to false and leave the rest null."
)


class GeminiExtractor:
    """Reads a receipt image with Gemini Pro and structured output."""

    def __init__(self, model: BaseChatModel) -> None:
        """Wraps the extraction model."""
        self._model = model.with_structured_output(ExtractedReceipt)

    async def __call__(
        self, content: bytes, mime_type: str, categories: list[str]
    ) -> ExtractedReceipt:
        """Extracts fields from one receipt image held in memory.

        Raises:
            LLMError: If the model call fails.
        """
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": EXTRACT_PROMPT.format(categories=", ".join(categories)),
                },
                {
                    "type": "image",
                    "base64": base64.b64encode(content).decode(),
                    "mime_type": mime_type,
                },
            ]
        )
        try:
            return await self._model.ainvoke(
                [message],
                config={"run_name": "extract_receipt", "tags": ["pfa", "extraction"]},
            )
        except Exception as exc:  # Gemini rate limits, timeouts, parse failures.
            raise LLMError(f"extraction model call failed: {exc}") from exc


class GeminiCorrectionParser:
    """Turns a typed message into field changes with Flash Lite."""

    def __init__(self, model: BaseChatModel) -> None:
        """Wraps the chat model."""
        self._model = model.with_structured_output(CorrectionResult)

    async def __call__(
        self,
        text: str,
        current: PendingTransaction,
        categories: list[str],
        cards: list[str],
    ) -> CorrectionResult:
        """Interprets a message as a correction, or reports that it is not one.

        Raises:
            LLMError: If the model call fails.
        """
        prompt = CORRECTION_PROMPT.format(
            current=current.model_dump(mode="json", exclude={"transaction_id"}),
            categories=", ".join(categories),
            cards=", ".join(cards) or "none yet",
            text=text,
        )
        try:
            return await self._model.ainvoke(
                prompt,
                config={"run_name": "parse_correction", "tags": ["pfa", "extraction"]},
            )
        except Exception as exc:
            raise LLMError(f"correction model call failed: {exc}") from exc

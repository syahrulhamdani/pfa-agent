"""Gemini-backed extraction and correction parsing, via structured output."""

import base64

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from pfa.core.exceptions import LLMError
from pfa.core.tracing import STATEMENT_ROWS_MARKER
from pfa.schemas.extraction import (
    CorrectionResult,
    ExtractedReceipt,
    ExtractedStatement,
)
from pfa.schemas.statements import StatementFormat
from pfa.schemas.transactions import PendingTransaction
from pfa.services.statements import read_table, table_batches

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


STATEMENT_PROMPT = (
    "This is a bank or credit card statement. Return the card or account it belongs "
    "to (card_hint: the bank name and the last four digits if shown) and every line "
    "in `transactions`, in order. Report only what is clearly there: if a merchant, "
    "amount or date is unreadable, return null for it. Never invent lines. Each "
    'amount is the absolute value as a positive number. Set direction to "out" for '
    'money spent or paid away, and to "in" for money received: salary, refunds and '
    "reversals, interest, transfers in, and payments made to a card account. "
    'Use the category "Transfer" only for money moved between the user\'s own '
    "cards, accounts or pockets, such as paying a card bill from a bank account or "
    "topping up an e-wallet. Money sent to or received from another person or a "
    "business is not a transfer: give it the category that fits best. "
    "Choose each category from this list only: {categories}."
)


class GeminiStatementExtractor:
    """Reads a statement with Gemini Pro: PDFs directly, CSV and Excel as text."""

    def __init__(self, model: BaseChatModel) -> None:
        """Wraps the extraction model."""
        self._model = model.with_structured_output(ExtractedStatement)

    async def __call__(
        self, content: bytes, fmt: StatementFormat, categories: list[str]
    ) -> ExtractedStatement:
        """Extracts the card hint and every line of a statement held in memory.

        Spreadsheets are parsed in Python first and sent in batches of rows, so each
        answer stays short; the batches are merged. A PDF is sent as one document.

        Raises:
            StatementError: If a spreadsheet is empty, too large or unreadable.
            LLMError: If a model call fails.
        """
        instruction = STATEMENT_PROMPT.format(categories=", ".join(categories))
        if fmt == "pdf":
            file_block = {
                "type": "file",
                "base64": base64.b64encode(content).decode(),
                "mime_type": "application/pdf",
            }
            results = [
                await self._ask([{"type": "text", "text": instruction}, file_block])
            ]
        else:
            results = [
                await self._ask(
                    [
                        {
                            "type": "text",
                            "text": (
                                f"{instruction}\n\n{STATEMENT_ROWS_MARKER}\n{batch}"
                            ),
                        }
                    ]
                )
                for batch in table_batches(await read_table(content, fmt))
            ]
        return ExtractedStatement(
            card_hint=next((r.card_hint for r in results if r.card_hint), None),
            transactions=[row for r in results for row in r.transactions],
        )

    async def _ask(self, blocks: list[dict]) -> ExtractedStatement:
        try:
            return await self._model.ainvoke(
                [HumanMessage(content=blocks)],
                config={"run_name": "extract_statement", "tags": ["pfa", "extraction"]},
            )
        except Exception as exc:  # Gemini rate limits, timeouts, parse failures.
            raise LLMError(f"statement model call failed: {exc}") from exc

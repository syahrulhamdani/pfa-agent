"""The model's part in summaries and chat answers: words only, never figures.

The model is shown the rendered facts and nothing else. It is told to copy figures
exactly and never to calculate; the caller then rejects any reply that quotes a figure
that is not in the facts.
"""

import re
from typing import Literal, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from pfa.core.exceptions import LLMError

RECOMMEND_PROMPT = (
    "You are pfa, a calm personal finance assistant. Write 3 to 5 short pieces of "
    "advice for the user, based ONLY on the facts below. Rules: use only figures that "
    "appear in the facts and copy them exactly as written; never add, subtract, "
    "average, estimate, round or convert figures, and never mention a figure that is "
    "not listed. Write plain text, one piece of advice per line, with no list "
    "numbering, no bullet symbols, no markdown and no emoji. Put anything under "
    "'Needs attention' first, then what the savings goals need, then a pattern in "
    "the spending. If nothing needs attention, say so in one line. If nothing was "
    "recorded in the period, say that plainly. Never describe spending as steady, "
    "rising, falling or unusual unless the facts themselves compare it with an "
    "earlier period. Do not name a currency."
)

ANSWER_PROMPT = (
    "You are pfa, a calm personal finance assistant. Answer the user's question in 1 "
    "to 3 short sentences, using ONLY the facts below. Give the takeaway in plain "
    "words and do not list figures: the user sees every figure laid out in a table "
    "right under your answer, so quote at most the one or two that matter most. "
    "Rules: use only figures that "
    "appear in the facts and copy them exactly as written; never add, subtract, "
    "average, estimate, round or convert figures. If the facts do not contain what "
    "the question needs, say what you cannot see and what would help (for example "
    "uploading receipts or setting a budget). If nothing was recorded in the "
    "period, say that plainly. Never describe spending as steady, rising, falling or "
    "unusual unless the facts themselves compare it with an earlier period. Plain "
    "text only, no markdown, no emoji. Do not name a currency."
)

ROUTER_PROMPT = (
    "Decide whether the user's message asks about their own money: spending, income, "
    "budgets, savings goals, how they are doing, or advice about them. If so, "
    "kind is 'insights'; otherwise 'casual' (greetings, thanks, anything else). For "
    "insights, set period to the time frame they mean (day, week, month, quarter or "
    "year; default month) and offset to 0 for the current one or -1 for the one "
    "before ('last week' is week with offset -1). Set category only if they name one "
    "of these categories: {categories}; otherwise leave it empty."
)

MAX_ADVICE_LINES = 5
MAX_LINE_CHARS = 320
_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•#>]+)\s*")


class Route(BaseModel):
    """What a chat message is asking for."""

    kind: Literal["casual", "insights"] = "casual"
    period: Literal["day", "week", "month", "quarter", "year"] = "month"
    offset: int = Field(0, ge=-12, le=0)
    category: str | None = None


class Router(Protocol):
    """Decides how a chat message should be handled."""

    async def __call__(self, text: str) -> Route:
        """Returns the route for `text`."""
        ...


class Writer(Protocol):
    """Writes words from facts. `instruction` is the system prompt to use."""

    async def __call__(self, instruction: str, facts_text: str, question: str) -> str:
        """Returns text written from `facts_text` under `instruction`."""
        ...


class GeminiWriter:
    """Writes advice and answers with the fast chat model."""

    def __init__(self, model: BaseChatModel) -> None:
        """Keeps the model to call."""
        self._model = model

    async def __call__(self, instruction: str, facts_text: str, question: str) -> str:
        """Returns the model's text.

        Raises:
            LLMError: If the call fails or comes back empty.
        """
        human = f"Facts:\n{facts_text}"
        if question:
            human += f"\n\nQuestion: {question}"
        try:
            response = await self._model.ainvoke(
                [SystemMessage(instruction), HumanMessage(human)],
                config={"run_name": "write_from_facts", "tags": ["pfa", "insights"]},
            )
        except Exception as exc:  # rate limits, timeouts, network errors
            raise LLMError(f"insight model call failed: {exc}") from exc
        text = response.text.strip()
        if not text:
            raise LLMError("insight model returned nothing")
        return text


class GeminiRouter:
    """Routes a chat message with structured output from the chat model."""

    def __init__(self, model: BaseChatModel, category_names) -> None:
        """Keeps the model and a function returning the category names."""
        self._structured = model.with_structured_output(Route)
        self._category_names = category_names

    async def __call__(self, text: str) -> Route:
        """Returns the route, treating any failure as a casual message."""
        prompt = ROUTER_PROMPT.format(categories=", ".join(self._category_names()))
        try:
            route = await self._structured.ainvoke(
                [SystemMessage(prompt), HumanMessage(text)],
                config={"run_name": "route_chat", "tags": ["pfa", "routing"]},
            )
        except Exception:
            return Route()
        return route if isinstance(route, Route) else Route()


def advice_lines(text: str) -> list[str]:
    """Splits a model's reply into clean one-line pieces of advice."""
    lines = [_MARKER.sub("", line).strip() for line in text.splitlines()]
    return [line[:MAX_LINE_CHARS] for line in lines if line][:MAX_ADVICE_LINES]

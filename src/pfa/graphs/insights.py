"""The model's part in summaries and chat answers: words only, never figures.

The model is shown the rendered facts and nothing else. It is told to copy figures
exactly and never to calculate. For arithmetic in a chat answer it is given a
calculator tool that only accepts numbers found in the facts or in the user's
question; the caller then rejects any reply that quotes a figure that is none of: a
fact, a number from the question, or a calculator result.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from pfa.core.exceptions import LLMError
from pfa.services.calculator import (
    FUNCTION_HELP,
    CalculationError,
    evaluate,
    format_result,
    literals,
)
from pfa.services.insights import figures_in

CALCULATOR_RULES = (
    "For ANY arithmetic (sums, differences, products, ratios, percentages, averages, "
    "per-day or per-week amounts, projections) you MUST call the calculate tool and "
    "quote its result exactly; never work arithmetic out yourself, not even a simple "
    "one. Give the tool an expression using only numbers that appear in the facts or "
    "in the user's question, written without thousands separators. Functions: "
    f"{FUNCTION_HELP}. If the tool returns an error, tell the user you could not work "
    "it out."
)

RECOMMEND_PROMPT = (
    "You are pfa, a calm personal finance assistant. Write 3 to 5 short pieces of "
    "advice for the user, based ONLY on the facts below. Rules: use only figures that "
    "appear in the facts and copy them exactly as written; never add, subtract, "
    "average, estimate, round or convert figures yourself, and never mention a "
    "figure that is neither listed nor a calculate result. Write plain text, one "
    "piece of advice per line, with no list "
    "numbering, no bullet symbols, no markdown and no emoji. Put anything under "
    "'Needs attention' first, then what the savings goals need, then a pattern in "
    "the spending. If nothing needs attention, say so in one line. If nothing was "
    "recorded in the period, say that plainly. Never describe spending as steady, "
    "rising, falling or unusual unless the facts themselves compare it with an "
    "earlier period. Do not name a currency. "
    f"{CALCULATOR_RULES}"
)

ANSWER_PROMPT = (
    "You are pfa, a calm personal finance assistant. Answer the user's question in 1 "
    "to 3 short sentences, using ONLY the facts below. Give the takeaway in plain "
    "words and do not list figures: the user sees every figure laid out in a table "
    "right under your answer, so quote at most the one or two that matter most. "
    "Rules: use only figures that appear in the facts and copy them exactly as "
    "written; never add, subtract, average, estimate, round or convert figures "
    "yourself. If the facts do not contain what the question needs, say what you "
    "cannot see and what would help (for example uploading receipts or setting a "
    "budget). If nothing was recorded in the period, say that plainly. Never "
    "describe spending as steady, rising, falling or unusual unless the facts "
    "themselves compare it with an earlier period. Plain text only, no markdown, "
    f"no emoji. Do not name a currency. {CALCULATOR_RULES}"
)

CALCULATE_PROMPT = (
    "You are pfa, a calm personal finance assistant. The user asked for a "
    "calculation. Work it out with the calculate tool and answer in one or two short "
    "sentences that state the result and what it means. Use only numbers the user "
    "gave; if they did not give enough numbers, say which ones you need. Plain text "
    "only, no markdown, no emoji. Do not name a currency. "
    f"{CALCULATOR_RULES}"
)

ROUTER_PROMPT = (
    "Decide what the user's message asks. kind is 'insights' if it asks about their "
    "own money: spending, income, budgets, savings goals, how they are doing, or "
    "advice about them. kind is 'calculate' if it is arithmetic with numbers they "
    "give, not about their recorded data (for example 'what is 15% of 2,000,000' or "
    "'if I save 500 a week for 10 weeks'). Otherwise kind is 'casual' (greetings, "
    "thanks, anything else). For insights, set period to the time frame they mean "
    "(day, week, month, quarter or year; default month) and offset to 0 for the "
    "current one or -1 for the one before ('last week' is week with offset -1). Set "
    "category only if they name one of these categories: {categories}; otherwise "
    "leave it empty."
)

# Unit conversions the calculator always accepts, besides the numbers in the facts and
# the question: percent, months in a year, days in a week, and so on. They are not
# data, so allowing them never lets the model feed the calculator an invented amount.
UNIT_CONSTANTS = frozenset(Decimal(n) for n in (0, 1, 2, 7, 12, 30, 52, 100, 365))

MAX_ADVICE_LINES = 5
MAX_LINE_CHARS = 320
MAX_TOOL_ROUNDS = 4
_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•#>]+)\s*")


class Route(BaseModel):
    """What a chat message is asking for."""

    kind: Literal["casual", "insights", "calculate"] = "casual"
    period: Literal["day", "week", "month", "quarter", "year"] = "month"
    offset: int = Field(0, ge=-12, le=0)
    category: str | None = None


@dataclass(frozen=True)
class Written:
    """What a writer produced: the words, and the numbers a calculator gave it."""

    text: str
    calculated: frozenset[Decimal] = frozenset()


def as_written(value: "str | Written") -> Written:
    """Accepts a writer's answer as plain text or as `Written`."""
    return value if isinstance(value, Written) else Written(value)


class Router(Protocol):
    """Decides how a chat message should be handled."""

    async def __call__(self, text: str) -> Route:
        """Returns the route for `text`."""
        ...


class Writer(Protocol):
    """Writes words from facts. `instruction` is the system prompt to use."""

    async def __call__(
        self, instruction: str, facts_text: str, question: str
    ) -> "str | Written":
        """Returns text written from `facts_text` under `instruction`."""
        ...


def make_calculate_tool(allowed: set[Decimal], results: set[Decimal]) -> StructuredTool:
    """Builds the calculator the model must use.

    The tool refuses an expression that contains a number that is neither in `allowed`
    (the facts and the user's question) nor a unit conversion such as 100 for percent,
    so the model cannot feed it invented inputs. Every result it gives is added to
    `results`.
    """
    allowed = allowed | UNIT_CONSTANTS

    def calculate(expression: str) -> str:
        try:
            unknown = literals(expression) - allowed
            if unknown:
                shown = ", ".join(sorted(format_result(n) for n in unknown))
                return (
                    f"Error: the number(s) {shown} are not in the facts or the "
                    "question. Use only numbers from those."
                )
            text = format_result(evaluate(expression))
        except CalculationError as error:
            return f"Error: {error}"
        results.add(Decimal(text))
        return text

    return StructuredTool.from_function(
        func=calculate,
        name="calculate",
        description=(
            "Works out arithmetic exactly. Pass one expression, such as '1100 / 7' or "
            f"'pct_of(900, 1100)'. Functions: {FUNCTION_HELP}. Use only numbers from "
            "the facts or the question, without thousands separators."
        ),
    )


class GeminiWriter:
    """Writes advice and answers with the fast chat model."""

    def __init__(self, model: BaseChatModel, *, calculator: bool = False) -> None:
        """Keeps the model to call.

        Args:
            model: The chat model.
            calculator: Whether the model may call the calculator. Summaries and chat
                answers both turn it on.
        """
        self._model = model
        self._calculator = calculator

    async def __call__(
        self, instruction: str, facts_text: str, question: str
    ) -> Written:
        """Returns the model's text and any numbers its calculator produced.

        Raises:
            LLMError: If the call fails, comes back empty, or keeps calculating
                without ever answering.
        """
        human = f"Facts:\n{facts_text}" if facts_text else "No facts are needed."
        if question:
            human += f"\n\nQuestion: {question}"
        results: set[Decimal] = set()
        model = self._model
        tool = None
        if self._calculator:
            tool = make_calculate_tool(figures_in(f"{facts_text}\n{question}"), results)
            model = self._model.bind_tools([tool])
        messages = [SystemMessage(instruction), HumanMessage(human)]
        config = {"run_name": "write_from_facts", "tags": ["pfa", "insights"]}
        try:
            for _ in range(MAX_TOOL_ROUNDS + 1):
                response = await model.ainvoke(messages, config=config)
                if tool is None or not response.tool_calls:
                    break
                messages.append(response)
                for call in response.tool_calls:
                    output = await tool.ainvoke(call["args"])
                    messages.append(
                        ToolMessage(content=output, tool_call_id=call["id"])
                    )
            else:
                raise LLMError("insight model kept calculating without answering")
        except LLMError:
            raise
        except Exception as exc:  # rate limits, timeouts, network errors
            raise LLMError(f"insight model call failed: {exc}") from exc
        text = response.text.strip()
        if not text:
            raise LLMError("insight model returned nothing")
        return Written(text, frozenset(results))


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

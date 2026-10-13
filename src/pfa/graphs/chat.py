"""Chat graph: casual replies from Flash Lite, with persistent per-chat memory.

A message about the user's own money is routed to an insights answer instead: the
facts are computed in code, the model writes the words from them, and any reply that
quotes a figure outside the facts is replaced by the facts themselves.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, trim_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from pfa.core.exceptions import LLMError
from pfa.graphs.insights import ANSWER_PROMPT, Route, Router, Writer
from pfa.schemas.insights import InsightFacts
from pfa.services.insights import numbers_grounded, render_facts, render_stats

# Only the most recent messages are sent to Gemini; the full history stays stored.
MAX_HISTORY_MESSAGES = 20

BUSY_REPLY = "I'm busy right now. Please try again in a moment."
FIGURES_INTRO = "Here is how {label} looks:"

SYSTEM_PROMPT = (
    "You are pfa, a personal finance assistant chatting with one person on Telegram. "
    "Talk like a calm, sharp person, not a bot menu. Be concise and professional, "
    "with filler and emoji that makes you more human. You can receive receipts and "
    "statements as uploads and help them understand their spending. "
    "Never invent numbers about their money."
)


@dataclass(frozen=True)
class InsightsConfig:
    """What the chat graph needs to answer questions about the user's money."""

    router: Router
    facts: Callable[[Route], Awaitable[InsightFacts]]
    writer: Writer


async def answer_from_facts(config: InsightsConfig, route: Route, question: str) -> str:
    """Answers a question about the user's money from computed facts.

    The answer is a few sentences from the model (used only if every figure in them
    is one of the facts) followed by the figures laid out one per line by code. If
    the model fails or strays, a plain introduction and the same figures are sent.
    """
    facts = await config.facts(route)
    facts_text = render_facts(facts)
    stats = render_stats(facts)  # the figures, laid out to be read
    try:
        text = (await config.writer(ANSWER_PROMPT, facts_text, question)).strip()
    except LLMError:
        logger.exception("Insight model failed; answering with the figures alone")
        return f"{FIGURES_INTRO.format(label=facts.label)}\n\n{stats}"
    if not text or not numbers_grounded(text, facts_text):
        logger.warning("Insight answer quoted figures not in the facts; using figures")
        return f"{FIGURES_INTRO.format(label=facts.label)}\n\n{stats}"
    return f"{text}\n\n{stats}"


def build_chat_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver,
    insights: InsightsConfig | None = None,
) -> CompiledStateGraph:
    """Builds the chat graph.

    Args:
        model: The chat model to call.
        checkpointer: Where conversation history is stored. Postgres in the app,
            in memory in tests.
        insights: Answers questions about the user's own money. Without it, every
            message gets a casual reply.

    Returns:
        A compiled graph. Invoke it with a `thread_id` in the config to keep a
        separate conversation per chat.
    """

    async def reply(state: MessagesState) -> dict:
        if insights is not None:
            question = state["messages"][-1].text
            route = await insights.router(question)
            if route.kind == "insights":
                answer = await answer_from_facts(insights, route, question)
                return {"messages": [AIMessage(answer)]}
        history = trim_messages(
            state["messages"],
            strategy="last",
            token_counter=len,
            max_tokens=MAX_HISTORY_MESSAGES,
            start_on="human",
        )
        response = await model.ainvoke([SystemMessage(SYSTEM_PROMPT), *history])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("reply", reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    return graph.compile(checkpointer=checkpointer)


async def chat_reply(graph: CompiledStateGraph, chat_id: int, text: str) -> str:
    """Runs one user message through the graph and returns the reply text.

    Args:
        graph: The compiled chat graph.
        chat_id: Telegram chat id, used as the conversation thread.
        text: The user's message.

    Returns:
        The assistant's reply text.

    Raises:
        LLMError: If the model call fails or returns no text.
    """
    try:
        result = await graph.ainvoke(
            {"messages": [("user", text)]},
            config={
                "configurable": {"thread_id": str(chat_id)},
                "run_name": "chat",
                "tags": ["pfa", "chat"],
            },
        )
    except Exception as exc:  # Gemini rate limits, timeouts, network errors.
        raise LLMError(f"chat model call failed: {exc}") from exc
    answer = result["messages"][-1].text.strip()
    if not answer:
        raise LLMError("chat model returned an empty reply")
    return answer

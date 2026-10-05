"""Chat graph: casual replies from Flash Lite, with per-chat memory."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pfa.core.exceptions import LLMError

BUSY_REPLY = "I'm busy right now. Please try again in a moment."

SYSTEM_PROMPT = (
    "You are pfa, a personal finance assistant chatting with one person on Telegram. "
    "Talk like a calm, sharp person, not a bot menu. Be concise and professional, "
    "with filler and emoji that makes you more human. You can receive receipts and "
    "statements as uploads and help them understand their spending. "
    "Never invent numbers about their money."
)


def build_chat_graph(model: BaseChatModel) -> CompiledStateGraph:
    """Builds the chat graph.

    Args:
        model: The chat model to call.

    Returns:
        A compiled graph. Invoke it with a `thread_id` in the config to keep a
        separate conversation per chat.
    """

    async def reply(state: MessagesState) -> dict:
        response = await model.ainvoke(
            [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        )
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("reply", reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    return graph.compile(checkpointer=InMemorySaver())


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
            config={"configurable": {"thread_id": str(chat_id)}},
        )
    except Exception as exc:  # Gemini rate limits, timeouts, network errors.
        raise LLMError(f"chat model call failed: {exc}") from exc
    answer = result["messages"][-1].text.strip()
    if not answer:
        raise LLMError("chat model returned an empty reply")
    return answer

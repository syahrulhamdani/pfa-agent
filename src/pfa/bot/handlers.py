"""Telegram handlers."""

from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from pfa.core.exceptions import LLMError
from pfa.graphs.chat import BUSY_REPLY, chat_reply


def is_authorized(update: Update, allowed_chat_id: int) -> bool:
    """Returns True only for the one configured chat."""
    chat = update.effective_chat
    return chat is not None and chat.id == allowed_chat_id


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answers a casual text message through the chat graph."""
    allowed_chat_id: int = context.bot_data["chat_id"]
    graph: CompiledStateGraph = context.bot_data["chat_graph"]
    if not is_authorized(update, allowed_chat_id):
        logger.warning("Ignoring message from unauthorized chat")
        return
    message = update.effective_message
    if message is None or not message.text:
        return
    try:
        answer = await chat_reply(graph, allowed_chat_id, message.text)
    except LLMError:
        logger.exception("Chat reply failed")
        answer = BUSY_REPLY
    await message.reply_text(answer)

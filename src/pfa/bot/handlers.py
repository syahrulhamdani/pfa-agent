"""Telegram handlers."""

from langgraph.graph.state import CompiledStateGraph
from loguru import logger
from telegram import LinkPreviewOptions, Update
from telegram.ext import ContextTypes

from pfa.bot.formatting import (
    FAILED_TEXT,
    SIGNED_OUT_TEXT,
    UNSUPPORTED_TEXT,
    login_text,
)
from pfa.bot.uploads import UploadCoordinator
from pfa.core.exceptions import LLMError
from pfa.graphs.chat import BUSY_REPLY, chat_reply


def is_authorized(update: Update, allowed_chat_id: int) -> bool:
    """Returns True only for the one configured chat."""
    chat = update.effective_chat
    return chat is not None and chat.id == allowed_chat_id


def describe_update(update: Update) -> str:
    """Summarizes an update for logs without including message contents."""
    message = update.effective_message
    kinds = []
    if message is not None:
        for kind in ("text", "photo", "document"):
            if getattr(message, kind, None):
                kinds.append(kind)
    if getattr(update, "callback_query", None) is not None:
        kinds.append("callback")
    chat = update.effective_chat
    update_id = getattr(update, "update_id", None)
    chat_id = chat.id if chat else None
    return f"update_id={update_id} chat_id={chat_id} kinds={kinds or ['other']}"


async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs every incoming update, so a silent bot can be told from a deaf one."""
    logger.info("Received {}", describe_update(update))


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs any exception a handler raised and tells the user something broke."""
    # Log a redacted summary: a full update contains message text and file details.
    summary = (
        describe_update(update) if isinstance(update, Update) else type(update).__name__
    )
    logger.opt(exception=context.error).error(
        "Unhandled error while handling {}", summary
    )
    if isinstance(update, Update) and is_authorized(
        update, context.bot_data["chat_id"]
    ):
        message = update.effective_message
        if message is not None:
            await message.reply_text(FAILED_TEXT)


async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies to /login with a fresh single-use sign-in link for the web app."""
    if not is_authorized(update, context.bot_data["chat_id"]):
        logger.warning("Ignoring /login from unauthorized chat")
        return
    message = update.effective_message
    if message is None:
        return
    link = await context.bot_data["issue_link"]()
    await message.reply_text(
        login_text(link, context.bot_data["link_ttl_minutes"]),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def handle_signout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ends every web session and unused sign-in link."""
    if not is_authorized(update, context.bot_data["chat_id"]):
        logger.warning("Ignoring /signout from unauthorized chat")
        return
    message = update.effective_message
    if message is None:
        return
    await context.bot_data["revoke_sessions"]()
    logger.info("All web sessions were ended with /signout")
    await message.reply_text(SIGNED_OUT_TEXT)


async def handle_demo_nudge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a nudge right now, so it can be seen without waiting for a slot."""
    if not is_authorized(update, context.bot_data["chat_id"]):
        logger.warning("Ignoring /demo_nudge from unauthorized chat")
        return
    await context.bot_data["send_nudge"]()


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Treats text as a correction if a receipt awaits it, else as casual chat."""
    allowed_chat_id: int = context.bot_data["chat_id"]
    graph: CompiledStateGraph = context.bot_data["chat_graph"]
    if not is_authorized(update, allowed_chat_id):
        logger.warning("Ignoring message from unauthorized chat")
        return
    message = update.effective_message
    if message is None or not message.text:
        return
    coordinator: UploadCoordinator | None = context.bot_data.get("coordinator")
    if coordinator is not None and await coordinator.resume_text(message.text):
        return
    try:
        answer = await chat_reply(graph, allowed_chat_id, message.text)
    except LLMError:
        logger.exception("Chat reply failed")
        answer = BUSY_REPLY
    await message.reply_text(answer)


async def handle_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accepts a receipt photo (or image file) and starts extraction."""
    if not is_authorized(update, context.bot_data["chat_id"]):
        logger.warning(
            "Ignoring upload from unauthorized chat: {}", describe_update(update)
        )
        return
    message = update.effective_message
    coordinator: UploadCoordinator = context.bot_data["coordinator"]
    if message is None:
        return
    if message.photo:
        file_id, filename, mime_type = (
            message.photo[-1].file_id,
            "receipt.jpg",
            "image/jpeg",
        )
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        document = message.document
        file_id = document.file_id
        filename = document.file_name or "receipt.jpg"
        mime_type = document.mime_type
    else:
        logger.info("Rejected unsupported upload: {}", describe_update(update))
        await message.reply_text(UNSUPPORTED_TEXT)
        return
    logger.info("Accepting upload {} ({})", filename, mime_type)
    try:
        await coordinator.receive(message, file_id, filename, mime_type)
    except Exception:
        logger.exception("Could not accept upload")
        await message.reply_text(FAILED_TEXT)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the Confirm and card buttons."""
    query = update.callback_query
    if query is None or not is_authorized(update, context.bot_data["chat_id"]):
        logger.warning("Ignoring callback: {}", describe_update(update))
        return
    await query.answer()
    coordinator: UploadCoordinator = context.bot_data["coordinator"]
    kind, _, rest = (query.data or "").partition(":")
    try:
        if kind == "confirm":
            decision = {"action": "confirm"}
            upload_id = int(rest)
        elif kind == "card":
            upload, _, card = rest.partition(":")
            upload_id = int(upload)
            decision = {"action": "set_card", "card_id": int(card)}
        else:
            return
    except ValueError:
        logger.warning("Ignoring malformed callback data {!r}", query.data)
        return
    await query.edit_message_reply_markup(reply_markup=None)
    try:
        await coordinator.resume(upload_id, decision)
    except Exception:
        logger.exception("Could not resume upload {}", upload_id)
        await context.bot.send_message(context.bot_data["chat_id"], FAILED_TEXT)

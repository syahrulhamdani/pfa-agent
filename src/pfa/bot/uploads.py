"""Runs the extraction graph for Telegram uploads without blocking the chat."""

import asyncio
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Bot, LinkPreviewOptions, Message, ReplyParameters

from pfa.bot.formatting import (
    FAILED_TEXT,
    PROCESSING_TEXT,
    format_review,
    review_keyboard,
    saved_text,
)
from pfa.core.config import Settings
from pfa.graphs.extraction import NOT_A_CORRECTION, pending_interrupt, thread_config
from pfa.models import UploadStatus
from pfa.repository.finance import UploadRepository
from pfa.services.auth import LinkIssuer


class UploadCoordinator:
    """Owns the lifecycle of an upload: download, extract, confirm, save."""

    def __init__(
        self,
        *,
        bot: Bot,
        graph: CompiledStateGraph,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        issue_link: LinkIssuer,
    ) -> None:
        """Wires the coordinator to Telegram, the graph and the database."""
        self._bot = bot
        self._graph = graph
        self._session_factory = session_factory
        self._settings = settings
        self._issue_link = issue_link
        self._tasks: set[asyncio.Task] = set()
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def receive(
        self, message: Message, file_id: str, filename: str, mime_type: str
    ) -> None:
        """Saves an upload, acknowledges it, and starts extraction in the background."""
        logger.info("Downloading {} from Telegram", filename)
        telegram_file = await self._bot.get_file(file_id)
        directory = Path(self._settings.upload_dir)
        directory.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix or ".bin"
        path = directory / f"{uuid.uuid4().hex}{suffix}"
        await telegram_file.download_to_drive(path)
        logger.info("Saved upload to {} ({} bytes)", path, path.stat().st_size)
        async with self._session_factory() as session:
            upload = await UploadRepository(session).add(
                telegram_message_id=message.message_id,
                kind="image",
                filename=filename,
                file_path=str(path),
                mime_type=mime_type,
            )
        logger.info("Upload {} recorded; starting extraction", upload.id)
        await message.reply_text(PROCESSING_TEXT)
        task = asyncio.create_task(self._extract(upload.id, message.message_id))
        self._tasks.add(task)  # keep a reference so it is not garbage collected
        task.add_done_callback(self._tasks.discard)

    async def resume(self, upload_id: int, decision: dict[str, Any]) -> None:
        """Resumes a paused upload with a button press or confirmation."""
        await self._run(upload_id, Command(resume=decision))

    async def resume_text(self, text: str) -> bool:
        """Offers a typed message to the newest open upload as a correction.

        Returns:
            True if the message was handled as a correction. False if there is no
            open upload or the text is not a correction, so normal chat should answer.
        """
        async with self._session_factory() as session:
            upload = await UploadRepository(session).latest_open()
        if upload is None:
            logger.info("Text is not a correction: no receipt is waiting on the user")
            return False
        logger.info("Offering text to open upload {} as a correction", upload.id)
        try:
            return await self._run(
                upload.id,
                Command(resume={"action": "text", "text": text}),
                quiet_chat=True,
            )
        except Exception:
            logger.exception("Correction parsing failed; falling back to chat")
            return False

    async def _extract(self, upload_id: int, message_id: int) -> None:
        try:
            await self._run(upload_id, {"upload_id": upload_id})
        except Exception:
            logger.exception("Extraction failed for upload {}", upload_id)
            async with self._session_factory() as session:
                await UploadRepository(session).set_status(
                    upload_id, UploadStatus.FAILED
                )
            await self._send(FAILED_TEXT, message_id)

    async def _run(
        self, upload_id: int, graph_input: Any, quiet_chat: bool = False
    ) -> bool:
        async with self._locks[upload_id]:
            logger.info("Running extraction graph for upload {}", upload_id)
            result = await self._graph.ainvoke(graph_input, thread_config(upload_id))
        payload = pending_interrupt(result)
        logger.info(
            "Graph for upload {} {}",
            upload_id,
            "paused for the user" if payload else "finished",
        )
        if payload and quiet_chat and payload.get("notice") == NOT_A_CORRECTION:
            logger.info("Model judged the text not a correction; answering as chat")
            return False
        if payload and payload.get("notice"):
            logger.info("Review notice for upload {}: {}", upload_id, payload["notice"])
        async with self._session_factory() as session:
            upload = await UploadRepository(session).get(upload_id)
        if payload:
            await self._send(
                format_review(payload),
                upload.telegram_message_id,
                review_keyboard(payload),
            )
        else:
            link = await self._issue_link()
            await self._send(
                saved_text(link, self._settings.auth_link_ttl_minutes),
                upload.telegram_message_id,
                no_preview=True,  # a preview bot fetching the link must not use it up
            )
        return True

    async def _send(
        self, text: str, reply_to: int, markup: Any = None, no_preview: bool = False
    ) -> None:
        await self._bot.send_message(
            chat_id=self._settings.telegram_chat_id,
            text=text,
            reply_markup=markup,
            link_preview_options=LinkPreviewOptions(is_disabled=no_preview),
            reply_parameters=ReplyParameters(
                message_id=reply_to, allow_sending_without_reply=True
            ),
        )

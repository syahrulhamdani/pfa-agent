"""Boundary: typed text is a correction only when the graph says so."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from pfa.bot.formatting import FAILED_TEXT, PROCESSING_TEXT
from pfa.bot.uploads import UploadCoordinator
from pfa.graphs.extraction import NOT_A_CORRECTION
from pfa.models import Upload, UploadStatus
from pfa.repository.finance import UploadRepository
from pfa.services.images import ImageStash

LINK = "http://web/auth?token=T&next=/transactions/today"

PAYLOAD = {
    "upload_id": 1,
    "transaction": {"merchant": "Indomaret"},
    "missing": [],
    "cards": [],
    "notice": None,
}


async def _upload(session_factory):
    async with session_factory() as session:
        return await UploadRepository(session).add(
            telegram_message_id=10,
            kind="image",
            filename="r.jpg",
            mime_type="image/jpeg",
        )


def _coordinator(session_factory, settings, result):
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value=result))
    bot = SimpleNamespace(send_message=AsyncMock())
    coordinator = UploadCoordinator(
        bot=bot,
        graph=graph,
        session_factory=session_factory,
        settings=settings,
        issue_link=AsyncMock(return_value=LINK),
        images=ImageStash(),
    )
    return coordinator, bot, graph


def _paused(notice=None):
    interrupt = SimpleNamespace(value={**PAYLOAD, "notice": notice})
    return {"__interrupt__": [interrupt]}


async def test_text_without_open_upload_is_not_handled(session_factory, settings):
    coordinator, bot, graph = _coordinator(session_factory, settings, {})
    assert await coordinator.resume_text("hello") is False
    graph.ainvoke.assert_not_called()


async def test_non_correction_text_falls_back_to_chat_quietly(
    session_factory, settings
):
    await _upload(session_factory)
    async with session_factory() as session:
        await UploadRepository(session).set_status(1, UploadStatus.NEEDS_INPUT)
    coordinator, bot, _ = _coordinator(
        session_factory, settings, _paused(NOT_A_CORRECTION)
    )
    assert await coordinator.resume_text("how am I doing?") is False
    bot.send_message.assert_not_called()


async def test_correction_resends_review_threaded_to_upload(session_factory, settings):
    await _upload(session_factory)
    async with session_factory() as session:
        await UploadRepository(session).set_status(1, UploadStatus.NEEDS_INPUT)
    coordinator, bot, _ = _coordinator(session_factory, settings, _paused())
    assert await coordinator.resume_text("it was 50000") is True
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["reply_parameters"].message_id == 10
    assert "Indomaret" in kwargs["text"]


async def test_model_failure_on_text_falls_back_to_chat(session_factory, settings):
    await _upload(session_factory)
    async with session_factory() as session:
        await UploadRepository(session).set_status(1, UploadStatus.NEEDS_INPUT)
    coordinator, bot, graph = _coordinator(session_factory, settings, {})
    graph.ainvoke.side_effect = RuntimeError("gemini down")
    assert await coordinator.resume_text("it was 50000") is False


async def test_finished_graph_sends_saved_link(session_factory, settings):
    await _upload(session_factory)
    coordinator, bot, _ = _coordinator(session_factory, settings, {})
    await coordinator.resume(1, {"action": "confirm"})
    kwargs = bot.send_message.await_args.kwargs
    assert LINK in kwargs["text"]
    assert "Saved" in kwargs["text"]
    assert str(settings.auth_link_ttl_minutes) in kwargs["text"]
    assert kwargs["link_preview_options"].is_disabled  # a bot must not open the link


# --- receive(): the getFile download, the database record, the background start ---


class FakeTelegramFile:
    def __init__(self, content: bytes = b"fake-jpeg-bytes", fail: bool = False):
        self.content = content
        self.fail = fail

    async def download_as_bytearray(self):
        if self.fail:
            raise OSError("download interrupted")
        return bytearray(self.content)


def _receive_setup(
    session_factory, settings, tmp_path, result=None, telegram_file=None
):
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value=result or _paused()))
    bot = SimpleNamespace(
        get_file=AsyncMock(return_value=telegram_file or FakeTelegramFile()),
        send_message=AsyncMock(),
    )
    coordinator = UploadCoordinator(
        bot=bot,
        graph=graph,
        session_factory=session_factory,
        settings=settings,
        issue_link=AsyncMock(return_value=LINK),
        images=ImageStash(),
    )
    message = SimpleNamespace(message_id=55, reply_text=AsyncMock())
    return coordinator, bot, graph, message, settings


async def _all_uploads(session_factory):

    async with session_factory() as session:
        return list(await session.scalars(select(Upload)))


async def test_receive_keeps_the_image_in_memory_only(
    session_factory, settings, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)  # any file the app wrote would land here
    coordinator, bot, graph, message, _ = _receive_setup(
        session_factory, settings, tmp_path
    )
    held_during_extraction = []

    async def extraction_run(graph_input, config):
        held_during_extraction.append(coordinator._images.get(graph_input["upload_id"]))
        return _paused()

    graph.ainvoke.side_effect = extraction_run

    await coordinator.receive(message, "file-abc", "receipt.jpg", "image/jpeg")

    bot.get_file.assert_awaited_once_with("file-abc")  # Telegram getFile
    message.reply_text.assert_awaited_once_with(PROCESSING_TEXT)
    (upload,) = await _all_uploads(session_factory)
    assert upload.telegram_message_id == 55
    assert upload.mime_type == "image/jpeg"
    assert upload.filename == "receipt.jpg"
    assert upload.status == UploadStatus.PROCESSING
    assert not hasattr(upload, "file_path")

    await asyncio.gather(*coordinator._tasks)  # the background extraction
    assert held_during_extraction == [b"fake-jpeg-bytes"]  # the graph saw the bytes
    assert len(coordinator._images) == 0  # and they are gone afterwards
    assert list(tmp_path.rglob("*")) == []  # nothing was written to disk
    review = bot.send_message.await_args.kwargs
    assert review["reply_parameters"].message_id == 55
    assert "Indomaret" in review["text"]


async def test_receive_records_filename_and_mime_type_of_image_files(
    session_factory, settings, tmp_path
):
    coordinator, *_, message, _ = _receive_setup(session_factory, settings, tmp_path)
    await coordinator.receive(message, "f", "scan.PNG", "image/png")
    (upload,) = await _all_uploads(session_factory)
    assert upload.filename == "scan.PNG"
    assert upload.mime_type == "image/png"


async def test_getfile_failure_records_nothing(session_factory, settings, tmp_path):
    coordinator, bot, graph, message, _ = _receive_setup(
        session_factory, settings, tmp_path
    )
    bot.get_file.side_effect = RuntimeError("telegram unreachable")
    with pytest.raises(RuntimeError):
        await coordinator.receive(message, "f", "r.jpg", "image/jpeg")
    assert await _all_uploads(session_factory) == []
    message.reply_text.assert_not_called()
    graph.ainvoke.assert_not_called()


async def test_download_failure_records_nothing(session_factory, settings, tmp_path):
    coordinator, _, graph, message, _ = _receive_setup(
        session_factory,
        settings,
        tmp_path,
        telegram_file=FakeTelegramFile(fail=True),
    )
    with pytest.raises(OSError):
        await coordinator.receive(message, "f", "r.jpg", "image/jpeg")
    assert await _all_uploads(session_factory) == []
    graph.ainvoke.assert_not_called()


async def test_extraction_failure_marks_failed_and_tells_user(
    session_factory, settings, tmp_path
):

    coordinator, bot, graph, message, _ = _receive_setup(
        session_factory, settings, tmp_path
    )
    graph.ainvoke.side_effect = RuntimeError("gemini down")
    await coordinator.receive(message, "f", "r.jpg", "image/jpeg")
    await asyncio.gather(*coordinator._tasks)

    (upload,) = await _all_uploads(session_factory)
    assert upload.status == UploadStatus.FAILED
    assert len(coordinator._images) == 0  # dropped even though extraction failed
    sent = bot.send_message.await_args.kwargs
    assert sent["text"] == FAILED_TEXT
    assert sent["reply_parameters"].message_id == 55

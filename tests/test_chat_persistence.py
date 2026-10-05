"""Boundary: chat history survives a restart when stored in Postgres.

Needs the compose database (`docker compose up -d db`); skipped otherwise.
"""

import uuid

import psycopg
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from pfa.core.config import Settings
from pfa.graphs.chat import build_chat_graph, chat_reply

CONN = Settings.model_fields["database_url"].default.replace("+asyncpg", "", 1)


@pytest.fixture
def require_db():
    try:
        psycopg.connect(CONN, connect_timeout=2).close()
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running")


async def test_history_survives_restart(require_db):
    chat_id = uuid.uuid4().int % 10**9  # fresh thread per run
    seen: list[int] = []

    class Recording(GenericFakeChatModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append(len(messages))
            return super()._generate(messages, *args, **kwargs)

    for text in ("first", "second"):  # two "process lifetimes"
        async with AsyncPostgresSaver.from_conn_string(CONN) as saver:
            await saver.setup()
            model = Recording(messages=iter([AIMessage(content="ok")]))
            graph = build_chat_graph(model, saver)
            await chat_reply(graph, chat_id, text)

    # system+1 on the first run; system+3 once the stored history is loaded
    assert seen == [2, 4]

"""Boundary: chat_reply returns model text, keeps per-chat memory, wraps failures."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from pfa.core.exceptions import LLMError
from pfa.graphs.chat import build_chat_graph, chat_reply


async def test_reply_returns_model_text(fake_model_factory):
    graph = build_chat_graph(fake_model_factory("  Hello there.  "))
    assert await chat_reply(graph, 1, "hi") == "Hello there."


async def test_memory_is_kept_per_chat():
    seen: list[int] = []

    class Recording(GenericFakeChatModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append(len(messages))
            return super()._generate(messages, *args, **kwargs)

    model = Recording(messages=iter(AIMessage(content=c) for c in "abc"))
    graph = build_chat_graph(model)
    await chat_reply(graph, 1, "first")
    await chat_reply(graph, 1, "second")
    await chat_reply(graph, 2, "other chat")
    # system+1, system+3 (history kept), system+1 (separate thread)
    assert seen == [2, 4, 2]


async def test_empty_reply_raises(fake_model_factory):
    graph = build_chat_graph(fake_model_factory("   "))
    with pytest.raises(LLMError):
        await chat_reply(graph, 1, "hi")


async def test_model_failure_is_wrapped():
    class Boom(GenericFakeChatModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("rate limited")

    graph = build_chat_graph(Boom(messages=iter([])))
    with pytest.raises(LLMError, match="rate limited"):
        await chat_reply(graph, 1, "hi")

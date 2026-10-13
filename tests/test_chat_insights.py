"""Boundary: chat answers about the user's money come from computed facts.

What is tested: a casual message still gets a casual reply and never touches the data;
a money question is routed, answered from the facts the code computed, and the model's
reply is used only if every figure in it is one of the facts; the router and the
writer cope with a model that fails or misbehaves.
"""

from datetime import date
from decimal import Decimal

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from pfa.core.exceptions import LLMError
from pfa.graphs.chat import InsightsConfig, build_chat_graph, chat_reply
from pfa.graphs.insights import (
    ANSWER_PROMPT,
    GeminiRouter,
    GeminiWriter,
    Route,
)
from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository
from pfa.schemas.analytics import Period
from pfa.services.analytics import shift_anchor
from pfa.services.insights import gather_facts, render_facts

TODAY = date(2026, 10, 14)  # a Wednesday; the week began on Monday Oct 12


class Recorder:
    """Stands in for the router, facts provider and writer, and records calls."""

    def __init__(self, route=None, facts=None, answer="You spent 900 on Dining."):
        self.route = route or Route(kind="insights", period="week", category="Dining")
        self._facts = facts
        self.answer = answer
        self.questions: list[str] = []
        self.routes: list[Route] = []
        self.writes: list[tuple[str, str, str]] = []

    async def router(self, text):
        self.questions.append(text)
        return self.route

    async def facts(self, route):
        self.routes.append(route)
        return self._facts

    async def writer(self, instruction, facts_text, question):
        self.writes.append((instruction, facts_text, question))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def config(self):
        return InsightsConfig(router=self.router, facts=self.facts, writer=self.writer)


async def real_facts(session_factory):
    """A facts provider like the app's, over a real database."""

    async def provide(route: Route):
        period = Period(route.period)
        async with session_factory() as session:
            return await gather_facts(
                session,
                period,
                shift_anchor(period, TODAY, route.offset),
                TODAY,
                category=route.category,
                partial=route.offset == 0,
            )

    return provide


async def seed(session_factory):
    async with session_factory() as session:
        dining = await CategoryRepository(session).get_id_by_name("Dining")
        session.add_all(
            Transaction(
                merchant=f"Warung {i}",
                category_id=dining,
                amount=Decimal(a),
                occurred_on=date.fromisoformat(d),
                direction="out",
                status="confirmed",
            )
            for i, (a, d) in enumerate(
                [("600", "2026-10-12"), ("300", "2026-10-13"), ("100", "2026-10-08")]
            )
        )
        await session.commit()


def casual_model(reply="Hello there."):
    return GenericFakeChatModel(messages=iter([AIMessage(content=reply)] * 5))


# --- routing ---


async def test_a_casual_message_never_touches_the_data():
    spy = Recorder(route=Route(kind="casual"))
    graph = build_chat_graph(casual_model(), InMemorySaver(), spy.config())
    assert await chat_reply(graph, 1, "good morning") == "Hello there."
    assert spy.questions == ["good morning"]
    assert spy.routes == [] and spy.writes == []


async def test_a_money_question_is_answered_from_the_facts(session_factory):
    await seed(session_factory)
    spy = Recorder()
    spy._facts = await (await real_facts(session_factory))(spy.route)
    graph = build_chat_graph(
        casual_model("SHOULD NOT BE USED"), InMemorySaver(), spy.config()
    )
    answer = await chat_reply(graph, 1, "how much did I spend on dining this week?")
    assert answer.startswith("You spent 900 on Dining.\n\n")
    assert "Dining: 900 spent (100% of your money out, 2 transactions)" in answer
    ((instruction, facts_text, question),) = spy.writes
    assert instruction == ANSWER_PROMPT
    assert question == "how much did I spend on dining this week?"
    assert "Asked about Dining: 900 spent" in facts_text


async def test_the_route_decides_the_period_the_offset_and_the_category(
    session_factory,
):
    await seed(session_factory)
    spy = Recorder(
        route=Route(kind="insights", period="week", offset=-1, category="Dining")
    )
    spy._facts = await (await real_facts(session_factory))(spy.route)
    graph = build_chat_graph(casual_model(), InMemorySaver(), spy.config())
    await chat_reply(graph, 1, "and last week?")
    assert spy.routes == [
        Route(kind="insights", period="week", offset=-1, category="Dining")
    ]
    # Last week held the 100 from Oct 8, not this week's 900.
    assert "Asked about Dining: 100 spent" in spy.writes[0][1]


async def test_the_figures_in_an_answer_match_the_analytics(session_factory):
    await seed(session_factory)
    provide = await real_facts(session_factory)
    spy = Recorder(answer="Dining took 900 this week, all of your spending.")
    spy.facts = provide
    graph = build_chat_graph(casual_model(), InMemorySaver(), spy.config())
    answer = await chat_reply(graph, 1, "dining this week?")
    facts = await provide(spy.route)
    assert facts.focus.total == Decimal("900.00")
    assert answer.startswith("Dining took 900 this week, all of your spending.\n\n")


# --- keeping the model to the facts ---


@pytest.mark.parametrize(
    "answer",
    ["You spent 1,200 on Dining.", "That is 45 a day.", "Up 80% on before."],
)
async def test_an_answer_with_an_invented_figure_is_replaced_by_the_facts(
    session_factory, answer
):
    await seed(session_factory)
    spy = Recorder(answer=answer)
    spy._facts = await (await real_facts(session_factory))(spy.route)
    graph = build_chat_graph(casual_model(), InMemorySaver(), spy.config())
    reply = await chat_reply(graph, 1, "dining?")
    assert reply.startswith("Here is how Week of Oct 12 – Oct 18, 2026")
    assert answer not in reply
    assert "Dining: 900 spent" in reply


@pytest.mark.parametrize("answer", [LLMError("rate limited"), "", "   "])
async def test_a_failing_or_empty_writer_falls_back_to_the_facts(
    session_factory, answer
):
    await seed(session_factory)
    spy = Recorder(answer=answer)
    spy._facts = await (await real_facts(session_factory))(spy.route)
    graph = build_chat_graph(casual_model(), InMemorySaver(), spy.config())
    reply = await chat_reply(graph, 1, "dining?")
    assert reply.startswith("Here is how Week of") and "900" in reply


async def test_a_category_with_nothing_spent_is_said_plainly(session_factory):
    spy = Recorder(
        route=Route(kind="insights", period="week", category="Transport"),
        answer="Nothing spent on Transport.",
    )
    spy._facts = await (await real_facts(session_factory))(spy.route)
    graph = build_chat_graph(casual_model(), InMemorySaver(), spy.config())
    reply = await chat_reply(graph, 1, "transport?")
    assert reply.startswith("Nothing spent on Transport.\n\n")
    assert "Transport: nothing spent in this period" in reply
    assert "nothing spent in this period" in spy.writes[0][1]


# --- memory ---


async def test_an_insights_answer_is_remembered_in_the_conversation(session_factory):
    await seed(session_factory)
    seen: list[int] = []

    class Recording(GenericFakeChatModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append(len(messages))
            return super()._generate(messages, *args, **kwargs)

    spy = Recorder()
    spy._facts = await (await real_facts(session_factory))(spy.route)
    model = Recording(messages=iter([AIMessage(content="ok")] * 3))
    graph = build_chat_graph(model, InMemorySaver(), spy.config())
    await chat_reply(graph, 1, "dining this week?")  # answered from the facts
    spy.route = Route(kind="casual")
    await chat_reply(graph, 1, "thanks")  # casual: the model sees the earlier turn
    assert seen == [4]  # system + question + answer + thanks


async def test_without_insights_every_message_is_casual():
    graph = build_chat_graph(casual_model("Hi."), InMemorySaver())
    assert await chat_reply(graph, 1, "how much did I spend?") == "Hi."


# --- the router and the writer ---


class StructuredStub:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.prompts = result, error, []

    def with_structured_output(self, schema):
        assert schema is Route
        return self

    async def ainvoke(self, messages, config=None):
        self.prompts.append(messages)
        if self.error:
            raise self.error
        return self.result


async def test_the_router_lists_the_categories_it_may_name():
    stub = StructuredStub(Route(kind="insights", period="year"))
    router = GeminiRouter(stub, lambda: ["Dining", "Groceries"])
    assert (await router("year so far?")).period == "year"
    assert "Dining, Groceries" in stub.prompts[0][0].content


async def test_a_router_failure_means_a_casual_message():
    router = GeminiRouter(StructuredStub(error=RuntimeError("quota")), lambda: [])
    assert (await router("anything")).kind == "casual"


async def test_a_router_that_returns_something_else_means_a_casual_message():
    router = GeminiRouter(StructuredStub(result={"kind": "insights"}), lambda: [])
    assert (await router("anything")).kind == "casual"


@pytest.mark.parametrize(
    "fields",
    [{"kind": "other"}, {"period": "decade"}, {"offset": 1}, {"offset": -13}],
)
def test_a_route_with_nonsense_is_refused(fields):
    with pytest.raises(ValidationError):
        Route(**fields)


def test_a_route_defaults_to_a_casual_message_about_this_month():
    route = Route()
    assert (route.kind, route.period, route.offset, route.category) == (
        "casual",
        "month",
        0,
        None,
    )


async def test_the_writer_returns_the_trimmed_text_and_shows_the_question():
    shown: list[str] = []

    class Model(GenericFakeChatModel):
        def _generate(self, messages, *args, **kwargs):
            shown.append(messages[1].content)
            return super()._generate(messages, *args, **kwargs)

    writer = GeminiWriter(Model(messages=iter([AIMessage(content="  Fine.  ")])))
    written = await writer("be brief", "Money out: 5", "how?")
    assert written.text == "Fine." and written.calculated == frozenset()
    assert "Facts:\nMoney out: 5" in shown[0] and "Question: how?" in shown[0]


async def test_the_writer_wraps_a_failure():
    class Boom(GenericFakeChatModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("rate limited")

    with pytest.raises(LLMError, match="rate limited"):
        await GeminiWriter(Boom(messages=iter([])))("x", "y", "")


async def test_the_writer_refuses_an_empty_reply():
    model = GenericFakeChatModel(messages=iter([AIMessage(content="   ")]))
    with pytest.raises(LLMError, match="nothing"):
        await GeminiWriter(model)("x", "y", "")


async def test_the_rendered_facts_are_what_the_writer_is_shown(session_factory):
    await seed(session_factory)
    provide = await real_facts(session_factory)
    route = Route(kind="insights", period="week")
    facts = await provide(route)
    spy = Recorder(route=route)
    spy.facts = provide
    graph = build_chat_graph(casual_model(), InMemorySaver(), spy.config())
    await chat_reply(graph, 1, "how am I doing?")
    assert spy.writes[0][1] == render_facts(facts)

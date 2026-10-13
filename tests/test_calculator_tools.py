"""Boundary: the model calculates only by calling the calculator tool.

What is tested: the tool accepts only numbers from the facts or the question and
records only its own results; the writer runs the tool-calling loop (several calls,
errors fed back, a cap on rounds); a figure the model produced without the tool is
refused in chat and in summaries; and a plain-arithmetic question has its own path.
"""

from datetime import date
from decimal import Decimal

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from pfa.core.exceptions import LLMError
from pfa.graphs.chat import (
    CALCULATION_FAILED,
    FIGURES_INTRO,
    InsightsConfig,
    build_chat_graph,
    chat_reply,
)
from pfa.graphs.insights import (
    ANSWER_PROMPT,
    CALCULATE_PROMPT,
    RECOMMEND_PROMPT,
    GeminiWriter,
    Route,
    Written,
    make_calculate_tool,
)
from pfa.graphs.recommendations import build_summary_graph
from pfa.models import Transaction
from pfa.repository.finance import CategoryRepository
from pfa.schemas.analytics import Period
from pfa.services.insights import gather_facts, render_facts
from pfa.services.summaries import SummaryService

TODAY = date(2026, 10, 14)  # a Wednesday; the week began on Monday Oct 12
D = Decimal


class ToolModel(BaseChatModel):
    """A fake chat model that answers from a script and records what it was sent."""

    script: list = Field(default_factory=list)
    seen: list = Field(default_factory=list)
    bound: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "tool-fake"

    def bind_tools(self, tools, **kwargs):
        self.bound.extend(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def call(expression, id="call_1"):
    return {"name": "calculate", "args": {"expression": expression}, "id": id}


def asks(*calls):
    return AIMessage(content="", tool_calls=list(calls))


def says(text):
    return AIMessage(content=text)


def tool_outputs(model):
    """What the calculator told the model, in order (the last round has them all)."""
    return [m.content for m in model.seen[-1] if isinstance(m, ToolMessage)]


# --- the tool itself ---


def test_the_tool_works_out_an_expression_from_allowed_numbers():
    results: set[Decimal] = set()
    tool = make_calculate_tool({D(1100), D(7)}, results)
    assert tool.invoke({"expression": "1100 / 7"}) == "157.14"
    assert results == {D("157.14")}


def test_the_tool_refuses_a_number_that_is_not_in_the_facts_or_the_question():
    results: set[Decimal] = set()
    tool = make_calculate_tool({D(1100)}, results)
    output = tool.invoke({"expression": "1100 * 1.1"})
    assert output.startswith("Error: the number(s) 1.1 are not in the facts")
    assert results == set()  # nothing was recorded


def test_the_tool_names_every_unknown_number_once_each():
    tool = make_calculate_tool(set(), set())
    output = tool.invoke({"expression": "5 + 5 + 9"})
    assert "5, 9" in output


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("1100 / 0", "Error: Cannot divide by zero."),
        ("1100 +", "Error: I could not read that calculation"),
        ("__import__('os')", "Error:"),
        ("", "Error: There is nothing to calculate."),
    ],
)
def test_the_tool_reports_problems_to_the_model_in_words(expression, message):
    results: set[Decimal] = set()
    tool = make_calculate_tool({D(1100), D(0)}, results)
    assert tool.invoke({"expression": expression}).startswith(message)
    assert results == set()


def test_a_number_the_user_gave_can_be_used_with_the_facts():
    tool = make_calculate_tool({D(2000000), D(15)}, set())
    assert tool.invoke({"expression": "2000000 * 15 / 100"}) == "300000"


@pytest.mark.parametrize(
    ("expression", "result"),
    [
        ("900 * 15 / 100", "135"),  # a percentage of an amount
        ("900 * 12", "10800"),  # a year of months
        ("900 / 7", "128.57"),  # a week of days
        ("(1 + 0) * 900", "900"),
    ],
)
def test_unit_conversions_are_always_allowed(expression, result):
    tool = make_calculate_tool({D(900), D(15)}, set())
    assert tool.invoke({"expression": expression}) == result


@pytest.mark.parametrize("invented", ["13", "250", "0.5", "1000000"])
def test_any_other_number_is_still_refused(invented):
    tool = make_calculate_tool({D(900)}, set())
    output = tool.invoke({"expression": f"900 * {invented}"})
    assert output.startswith("Error: the number(s)")


def test_the_tool_describes_itself_to_the_model():
    tool = make_calculate_tool(set(), set())
    assert tool.name == "calculate"
    assert "pct_of(part, whole)" in tool.description


# --- the writer's tool-calling loop ---


async def test_the_model_calls_the_tool_and_then_answers():
    model = ToolModel(script=[asks(call("1100 / 7")), says("About 157.14 a day.")])
    written = await GeminiWriter(model, calculator=True)(
        "inst", "Money out: 1,100\nLength of the period: 7 days", "daily average?"
    )
    assert written == Written("About 157.14 a day.", frozenset({D("157.14")}))
    assert tool_outputs(model) == ["157.14"]
    assert [t.name for t in model.bound] == ["calculate"]


async def test_several_calls_in_one_turn_and_over_several_turns():
    model = ToolModel(
        script=[
            asks(call("1100 / 7", "a"), call("5000 - 1100", "b")),
            asks(call("pct_of(900, 1100)", "c")),
            says("Done."),
        ]
    )
    written = await GeminiWriter(model, calculator=True)("inst", "900 1100 7 5000", "q")
    assert written.calculated == frozenset({D("157.14"), D(3900), D("81.82")})
    assert tool_outputs(model) == ["157.14", "3900", "81.82"]


async def test_an_error_goes_back_to_the_model_so_it_can_say_so():
    model = ToolModel(
        script=[asks(call("900 * 1.5")), says("I could not work that out.")]
    )
    written = await GeminiWriter(model, calculator=True)("inst", "Dining 900", "q")
    assert tool_outputs(model)[0].startswith("Error: the number(s) 1.5")
    assert written.text == "I could not work that out."
    assert written.calculated == frozenset()


async def test_the_tool_calls_and_results_are_part_of_the_conversation_sent_back():
    model = ToolModel(script=[asks(call("1100 / 7")), says("ok")])
    await GeminiWriter(model, calculator=True)("inst", "1100 7", "q")
    second = model.seen[1]
    assert [type(m).__name__ for m in second] == [
        "SystemMessage",
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]
    assert second[3].tool_call_id == "call_1"


async def test_a_model_that_never_stops_calculating_is_cut_off():
    model = ToolModel(script=[asks(call("1 + 1", f"c{i}")) for i in range(20)])
    with pytest.raises(LLMError, match="kept calculating"):
        await GeminiWriter(model, calculator=True)("inst", "1", "q")
    assert len(model.seen) == 5  # four rounds of calculating, then it gives up


async def test_without_the_calculator_no_tool_is_offered():
    model = ToolModel(script=[says("Plain.")])
    written = await GeminiWriter(model)("inst", "facts", "q")
    assert model.bound == [] and written == Written("Plain.")


async def test_a_failure_in_the_tool_loop_is_wrapped():
    class Boom(ToolModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("rate limited")

    with pytest.raises(LLMError, match="rate limited"):
        await GeminiWriter(Boom(), calculator=True)("inst", "facts", "q")


async def test_an_empty_final_answer_is_refused():
    model = ToolModel(script=[asks(call("1 + 1")), says("   ")])
    with pytest.raises(LLMError, match="nothing"):
        await GeminiWriter(model, calculator=True)("inst", "1", "q")


async def test_a_question_without_facts_still_lets_the_user_numbers_in():
    model = ToolModel(
        script=[asks(call("2000000 * 15 / 100")), says("That is 300000.")]
    )
    written = await GeminiWriter(model, calculator=True)(
        CALCULATE_PROMPT, "", "what is 15% of 2,000,000?"
    )
    assert tool_outputs(model) == ["300000"]
    assert written.calculated == frozenset({D(300000)})


# --- chat: a plain arithmetic question ---


def chat_graph(model, route, facts=None):
    async def router(text):
        return route

    async def provide(_route):
        return facts

    config = InsightsConfig(
        router=router,
        facts=provide,
        writer=GeminiWriter(model, calculator=True),
    )
    return build_chat_graph(ToolModel(script=[says("casual")]), InMemorySaver(), config)


async def test_a_plain_sum_is_worked_out_by_the_calculator():
    model = ToolModel(
        script=[asks(call("2000000 * 15 / 100")), says("15% of 2,000,000 is 300000.")]
    )
    graph = chat_graph(model, Route(kind="calculate"))
    answer = await chat_reply(graph, 1, "what is 15% of 2,000,000?")
    assert answer == "15% of 2,000,000 is 300000."
    assert model.seen[0][0].content == CALCULATE_PROMPT


async def test_a_sum_the_model_did_itself_is_refused():
    model = ToolModel(script=[says("15% of 2,000,000 is 300000.")])  # no tool call
    graph = chat_graph(model, Route(kind="calculate"))
    assert await chat_reply(graph, 1, "what is 15% of 2,000,000?") == CALCULATION_FAILED


async def test_a_wrong_sum_from_the_model_is_refused_even_after_a_correct_call():
    model = ToolModel(
        script=[asks(call("2000000 * 15 / 100")), says("That is 350000.")]
    )
    graph = chat_graph(model, Route(kind="calculate"))
    assert await chat_reply(graph, 1, "what is 15% of 2,000,000?") == CALCULATION_FAILED


async def test_a_calculation_that_fails_asks_the_user_to_restate_it():
    class Boom(ToolModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("down")

    graph = chat_graph(Boom(), Route(kind="calculate"))
    assert await chat_reply(graph, 1, "15% of 2,000,000?") == CALCULATION_FAILED


async def test_the_failure_message_tells_the_user_what_to_do():
    assert "give me the numbers plainly" in CALCULATION_FAILED
    assert "calculate" in CALCULATION_FAILED


async def test_a_calculation_never_touches_the_data():
    seen = []

    async def provide(route):
        seen.append(route)

    async def router(text):
        return Route(kind="calculate")

    model = ToolModel(script=[asks(call("2 * 3")), says("That is 6.")])
    config = InsightsConfig(
        router=router, facts=provide, writer=GeminiWriter(model, calculator=True)
    )
    graph = build_chat_graph(ToolModel(script=[]), InMemorySaver(), config)
    assert await chat_reply(graph, 1, "2 times 3") == "That is 6."
    assert seen == []


# --- chat: a question about the user's own money that needs a sum ---


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
            for i, (a, d) in enumerate([("600", "2026-10-12"), ("300", "2026-10-13")])
        )
        await session.commit()


async def week_facts(session_factory, **kwargs):
    async with session_factory() as session:
        return await gather_facts(
            session, Period.WEEK, TODAY, TODAY, partial=True, **kwargs
        )


async def test_a_daily_average_comes_from_the_calculator(session_factory):
    await seed(session_factory)
    facts = await week_facts(session_factory)
    text = render_facts(facts)
    assert "Days of the period so far: 3" in text  # Mon, Tue, Wed
    model = ToolModel(
        script=[asks(call("900 / 3")), says("You are averaging 300 a day so far.")]
    )
    graph = chat_graph(model, Route(kind="insights", period="week"), facts)
    answer = await chat_reply(graph, 1, "what is my average per day?")
    assert answer.startswith("You are averaging 300 a day so far.\n\n")
    assert model.seen[0][0].content == ANSWER_PROMPT
    assert "Money out: 900 (2 transactions)" in answer  # the figures follow


async def test_a_daily_average_the_model_did_itself_falls_back_to_the_figures(
    session_factory,
):
    await seed(session_factory)
    facts = await week_facts(session_factory)
    model = ToolModel(script=[says("You are averaging 300 a day so far.")])
    graph = chat_graph(model, Route(kind="insights", period="week"), facts)
    answer = await chat_reply(graph, 1, "what is my average per day?")
    assert answer.startswith(FIGURES_INTRO.format(label=facts.label))
    assert "averaging" not in answer


async def test_a_number_the_user_mentions_may_be_repeated_but_not_invented(
    session_factory,
):
    await seed(session_factory)
    facts = await week_facts(session_factory)
    ok = ToolModel(script=[says("Cutting 10% is a good aim for Dining.")])
    graph = chat_graph(ok, Route(kind="insights", period="week"), facts)
    answer = await chat_reply(graph, 1, "should I cut dining by 10%?")
    assert answer.startswith("Cutting 10% is a good aim for Dining.")  # 10 was theirs
    bad = ToolModel(script=[says("Cutting 11% is a good aim for Dining.")])
    graph = chat_graph(bad, Route(kind="insights", period="week"), facts)
    answer = await chat_reply(graph, 2, "should I cut dining by 10%?")
    assert answer.startswith("Here is how")  # 11 was invented


# --- summaries: the same rule ---


class FixedClock(SummaryService):
    async def monday_summary(self, now=None):
        return await super().monday_summary(None)


async def test_a_summary_may_use_the_calculator_for_its_advice(session_factory):
    await seed(session_factory)
    model = ToolModel(
        script=[
            asks(call("900 / 3")),
            says("Spending averages 300 a day so far.\nKeep an eye on Dining."),
        ]
    )
    graph = build_summary_graph(session_factory, GeminiWriter(model, calculator=True))
    service = SummaryService(session_factory, graph, "Asia/Jakarta")
    result = await service.demo_summary(
        __import__("datetime").datetime(
            2026, 10, 14, 3, 0, tzinfo=__import__("datetime").UTC
        )
    )
    assert result.summary.source == "model"
    assert result.summary.recommendations[0] == "Spending averages 300 a day so far."
    assert model.seen[0][0].content == RECOMMEND_PROMPT


async def test_a_summary_figure_the_model_did_by_itself_is_replaced(session_factory):
    await seed(session_factory)
    model = ToolModel(script=[says("Spending averages 300 a day so far.")])  # no call
    graph = build_summary_graph(session_factory, GeminiWriter(model, calculator=True))
    service = SummaryService(session_factory, graph, "Asia/Jakarta")
    from datetime import UTC, datetime

    result = await service.demo_summary(datetime(2026, 10, 14, 3, 0, tzinfo=UTC))
    assert result.summary.source == "fallback"
    assert "300 a day" not in " ".join(result.summary.recommendations)


def test_both_prompts_tell_the_model_to_use_the_calculator():
    for prompt in (RECOMMEND_PROMPT, ANSWER_PROMPT, CALCULATE_PROMPT):
        assert "you MUST call the calculate tool" in prompt
        assert "never work arithmetic out yourself" in prompt

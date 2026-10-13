"""Boundary: the calculator does exact arithmetic and lets nothing else through.

The strings below that look like code (`eval(...)`, `__import__(...)`) are attack
payloads the calculator must refuse; nothing here executes them.

What is tested: every operation and helper, exactness of decimals, precedence, the
limits that stop a runaway calculation, a long list of things that must be refused
(code, names, attributes, strings, tuples), plain-language errors, and how results are
written.
"""

from decimal import Decimal

import pytest

from pfa.services.calculator import (
    MAX_EXPRESSION_CHARS,
    CalculationError,
    evaluate,
    format_result,
    literals,
)

D = Decimal


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2", "3"),
        ("10 - 25", "-15"),
        ("6 * 7", "42"),
        ("1100 / 8", "137.5"),
        ("2 + 3 * 4", "14"),  # precedence
        ("(2 + 3) * 4", "20"),
        ("2 ** 3 ** 2", "512"),  # right to left, as in maths
        ("-5 + 3", "-2"),
        ("+5", "5"),
        ("--5", "5"),
        ("10 / 4 * 2", "5"),  # left to right
        ("0.1 + 0.2", "0.3"),  # exact, not 0.30000000000000004
        ("1.10 * 3", "3.30"),
        ("1000000 * 12", "12000000"),
        ("0", "0"),
        ("2 ** 0", "1"),
        ("2 ** -2", "0.25"),
        ("(1 + 0.05) ** 2", "1.1025"),  # compound growth
    ],
)
def test_arithmetic_is_exact(expression, expected):
    assert evaluate(expression) == D(expected)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("pct_of(900, 1100)", "81.8182"),
        ("pct_of(50, 200)", "25"),
        ("pct_of(300, 200)", "150"),
        ("pct_of(0, 200)", "0"),
        ("pct_change(400, 1100)", "175"),
        ("pct_change(1100, 400)", "-63.6364"),
        ("pct_change(100, 100)", "0"),
        ("avg(10, 20, 60)", "30"),
        ("avg(5)", "5"),
        ("sum(1, 2, 3, 4)", "10"),
        ("min(3, 1, 2)", "1"),
        ("max(3, 1, 2)", "3"),
        ("abs(-7.5)", "7.5"),
        ("round(2.345, 2)", "2.35"),  # half up, not banker's rounding
        ("round(2.5)", "3"),
        ("round(-2.5)", "-3"),
        ("round(1234.5678, 0)", "1235"),
        ("pct_of(1, 3) + 1", "34.3333"),
    ],
)
def test_the_helpers_work(expression, expected):
    # Compared to four places: the calculator itself carries many more.
    places = D(1).scaleb(-4)
    assert evaluate(expression).quantize(places) == D(expected).quantize(places)


def test_a_percentage_of_a_budget_is_what_a_person_expects():
    assert format_result(evaluate("pct_of(900, 1000)")) == "90"
    assert format_result(evaluate("pct_change(400, 1100)")) == "175"
    assert format_result(evaluate("1100 / 7")) == "157.14"
    assert format_result(evaluate("5000 - 1100")) == "3900"


# --- what must be refused, and said in plain words ---


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("1 / 0", "Cannot divide by zero."),
        ("5 / (3 - 3)", "Cannot divide by zero."),
        ("0 ** -1", "Cannot divide by zero."),
        ("pct_of(5, 0)", "Cannot work out a percentage of zero."),
        ("pct_change(0, 5)", "Cannot work out a change from zero."),
        ("2 ** 11", "Powers must be whole numbers"),
        ("2 ** -11", "Powers must be whole numbers"),
        ("2 ** 0.5", "Powers must be whole numbers"),
        ("9999999999 * 9999999999", "too large"),
        ("10 ** 10 * 10 ** 10", "too large"),
        ("round(1.5, 7)", "Round to a whole number of places"),
        ("round(1.5, 1.5)", "Round to a whole number of places"),
        ("round(1.5, -1)", "Round to a whole number of places"),
        ("pct_of(1)", "pct_of takes 2 numbers."),
        ("pct_change(1, 2, 3)", "pct_change takes 2 numbers."),
        ("round()", "round takes 1 to 2 numbers."),
        ("abs()", "abs takes 1 numbers."),
        ("avg()", "avg takes 1 to 50 numbers."),
        ("", "There is nothing to calculate."),
        ("   ", "There is nothing to calculate."),
    ],
)
def test_impossible_calculations_say_why(expression, message):
    with pytest.raises(CalculationError) as caught:
        evaluate(expression)
    assert message in str(caught.value)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "open('/etc/passwd')",
        "eval('1+1')",
        "exec('x=1')",
        "(1).__class__",
        "().__class__.__bases__",
        "[1, 2, 3]",
        "{1: 2}",
        "(1, 2)",
        "1,100",  # a thousands separator is a tuple, not a number
        "'abc'",
        "'a' * 5",
        "b'x'",
        "True",
        "False + 1",
        "None",
        "1 if True else 2",
        "lambda: 1",
        "x",
        "x + 1",
        "pi",
        "1 < 2",
        "1 and 2",
        "not 1",
        "1 // 2",
        "5 % 3",
        "1 << 4",
        "~1",
        "1 @ 2",
        "[i for i in range(3)]",
        "sum([1, 2, 3])",
        "sum(x for x in (1, 2))",
        "round(1.5, ndigits=1)",
        "avg(*[1, 2])",
        "math.sqrt(4)",
        "pct_of.__call__(1, 2)",
        "(lambda: 1)()",
        "f'{1}'",
        "1j",
        "1 +",
        "((1)",
        "1 2",
        "1 +* 2",
        "$5",
        "5%",
        "1_000",  # underscores parse as digits in Python; still only a number
    ][
        :-1
    ],  # the last case is a valid number and is tested separately below
)
def test_anything_that_is_not_plain_arithmetic_is_refused(expression):
    with pytest.raises(CalculationError):
        evaluate(expression)


def test_python_digit_separators_are_just_a_number():
    assert evaluate("1_000") == D(1000)


def test_errors_never_leak_internals():
    for expression in ("x", "__import__('os')", "1 +", "(1).real", "1 / 0"):
        with pytest.raises(CalculationError) as caught:
            evaluate(expression)
        text = str(caught.value)
        assert "Traceback" not in text and "ast." not in text and "Name" not in text


def test_a_calculation_that_is_too_long_is_refused():
    with pytest.raises(CalculationError, match="too long"):
        evaluate("1+" * MAX_EXPRESSION_CHARS + "1")


def test_a_calculation_with_too_many_parts_is_refused():
    expression = "+".join(["1"] * 60)  # short enough, but a lot of parts
    assert len(expression) < MAX_EXPRESSION_CHARS
    with pytest.raises(CalculationError, match="too complicated"):
        evaluate(expression)


def test_parentheses_alone_add_nothing():
    assert evaluate("(" * 90 + "1" + ")" * 90) == D(1)


def test_deep_nesting_of_functions_is_refused_without_crashing():
    expression = "abs(" * 30 + "1" + ")" * 30
    assert len(expression) < MAX_EXPRESSION_CHARS
    with pytest.raises(CalculationError, match="too complicated"):
        evaluate(expression)


def test_unbalanced_nesting_is_refused_without_crashing():
    with pytest.raises(CalculationError):
        evaluate("(" * 150)


def test_too_many_arguments_are_refused():
    with pytest.raises(CalculationError):
        evaluate("sum(" + ",".join(["1"] * 60) + ")")


def test_the_limits_are_sharp():
    assert evaluate("2 ** 10") == 1024
    assert evaluate("2 ** -10") == D(1) / 1024
    assert evaluate("999999999999999") == D(999999999999999)
    with pytest.raises(CalculationError, match="too large"):
        evaluate("1000000000000001")


# --- literals: the numbers an expression is built from ---


@pytest.mark.parametrize(
    ("expression", "found"),
    [
        ("1100 / 7", {D(1100), D(7)}),
        ("pct_of(900, 1100)", {D(900), D(1100)}),
        ("-5 + 3.5", {D(5), D("3.5")}),
        ("(2 + 3) * 2", {D(2), D(3)}),
        ("round(2.345, 2)", {D("2.345"), D(2)}),
    ],
)
def test_literals_lists_every_number_written(expression, found):
    assert literals(expression) == found


def test_literals_refuses_what_cannot_be_read():
    with pytest.raises(CalculationError):
        literals("1 +")
    with pytest.raises(CalculationError):
        literals("")


# --- writing a result ---


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (D("1650"), "1650"),
        (D("1650.00"), "1650"),
        (D("1650.50"), "1650.5"),
        (D("157.142857"), "157.14"),
        (D("0.005"), "0.01"),  # half up
        (D("0.004"), "0"),
        (D("-0.004"), "0"),  # never "-0"
        (D("-3900"), "-3900"),
        (D("-2.345"), "-2.35"),
        (D("0"), "0"),
        (D("999999999999999"), "999999999999999"),
        (D("100"), "100"),  # trailing zeros of a whole number are kept
        (D("1E+3"), "1000"),
    ],
)
def test_results_are_written_for_a_person(value, text):
    assert format_result(value) == text


def test_a_written_result_reads_back_as_the_same_number():
    for value in (D("157.142857"), D("-3900"), D("0.3"), D("12000000")):
        assert D(format_result(value)) == value.quantize(D("0.01")) or value.is_zero()

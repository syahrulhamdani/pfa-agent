"""A calculator pfa's model must use, so it never works figures out by itself.

Expressions are parsed, not executed: only numbers, + - * / and ** with a small whole
exponent, parentheses, and a short list of functions are allowed, and nothing else (no
names, attributes, strings or calls to anything else) can get through. Arithmetic is
exact decimal arithmetic, so 0.1 + 0.2 is 0.3, and every failure is a plain sentence a
person can read.
"""

import ast
import operator
from collections.abc import Callable
from decimal import (
    ROUND_HALF_UP,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

MAX_EXPRESSION_CHARS = 200
MAX_NODES = 80
MAX_ARGUMENTS = 50
MAX_ABS = Decimal("1e15")
MAX_POWER = 10
PRECISION = 34
RESULT_PLACES = Decimal("0.01")


class CalculationError(ValueError):
    """The calculation cannot be done; the message says why, in plain words."""


def _number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CalculationError("Only numbers can be used in a calculation.")
    return Decimal(str(value))


def _checked(value: Decimal) -> Decimal:
    if not value.is_finite() or abs(value) > MAX_ABS:
        raise CalculationError("That number is too large to work with.")
    return value


def _divide(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        raise CalculationError("Cannot divide by zero.")
    return a / b


def _power(base: Decimal, exponent: Decimal) -> Decimal:
    if exponent != exponent.to_integral_value() or abs(exponent) > MAX_POWER:
        raise CalculationError(
            f"Powers must be whole numbers from -{MAX_POWER} to {MAX_POWER}."
        )
    if base == 0 and exponent < 0:
        raise CalculationError("Cannot divide by zero.")
    return base ** int(exponent)


_BINARY: dict[type[ast.operator], Callable[[Decimal, Decimal], Decimal]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: _divide,
    ast.Pow: _power,
}


def _pct_of(part: Decimal, whole: Decimal) -> Decimal:
    if whole == 0:
        raise CalculationError("Cannot work out a percentage of zero.")
    return part / whole * 100


def _pct_change(old: Decimal, new: Decimal) -> Decimal:
    if old == 0:
        raise CalculationError("Cannot work out a change from zero.")
    return (new - old) / old * 100


def _round(value: Decimal, places: Decimal = Decimal(0)) -> Decimal:
    if places != places.to_integral_value() or not 0 <= places <= 6:
        raise CalculationError("Round to a whole number of places from 0 to 6.")
    return value.quantize(Decimal(1).scaleb(-int(places)), rounding=ROUND_HALF_UP)


def _at_least_one(name: str, args: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    if not args:
        raise CalculationError(f"{name} needs at least one number.")
    return args


# name -> (function, fewest arguments, most arguments)
_FUNCTIONS: dict[str, tuple[Callable[..., Decimal], int, int]] = {
    "pct_of": (_pct_of, 2, 2),
    "pct_change": (_pct_change, 2, 2),
    "round": (_round, 1, 2),
    "abs": (abs, 1, 1),
    "sum": (lambda *a: sum(_at_least_one("sum", a), Decimal(0)), 1, MAX_ARGUMENTS),
    "avg": (
        lambda *a: sum(_at_least_one("avg", a), Decimal(0)) / len(a),
        1,
        MAX_ARGUMENTS,
    ),
    "min": (lambda *a: min(_at_least_one("min", a)), 1, MAX_ARGUMENTS),
    "max": (lambda *a: max(_at_least_one("max", a)), 1, MAX_ARGUMENTS),
}

FUNCTION_HELP = (
    "pct_of(part, whole), pct_change(old, new), avg(a, b, ...), sum(a, b, ...), "
    "min(a, b, ...), max(a, b, ...), round(x, places), abs(x)"
)


def _evaluate(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant):
        return _checked(_number(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        value = _evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _checked(
            _BINARY[type(node.op)](_evaluate(node.left), _evaluate(node.right))
        )
    if isinstance(node, ast.Call):
        if (
            not isinstance(node.func, ast.Name)
            or node.func.id not in _FUNCTIONS
            or node.keywords
        ):
            raise CalculationError(f"Only these functions work: {FUNCTION_HELP}.")
        function, fewest, most = _FUNCTIONS[node.func.id]
        if not fewest <= len(node.args) <= most:
            raise CalculationError(
                f"{node.func.id} takes {fewest}"
                + ("" if fewest == most else f" to {most}")
                + " numbers."
            )
        return _checked(function(*(_evaluate(arg) for arg in node.args)))
    raise CalculationError(
        "I can only add, subtract, multiply, divide, raise to a small whole power, "
        f"and use these functions: {FUNCTION_HELP}. Write numbers without commas."
    )


def _parse(expression: str) -> ast.Expression:
    text = expression.strip()
    if not text:
        raise CalculationError("There is nothing to calculate.")
    if len(text) > MAX_EXPRESSION_CHARS:
        raise CalculationError("That calculation is too long.")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        raise CalculationError(
            "I could not read that calculation. Write numbers without commas."
        ) from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise CalculationError("That calculation is too complicated.")
    return tree


def evaluate(expression: str) -> Decimal:
    """Works out an expression exactly.

    Args:
        expression: For example "1100 / 7", "pct_of(900, 1100)" or "(1 + 5) ** 2".

    Returns:
        The exact result.

    Raises:
        CalculationError: If the expression is not allowed or cannot be worked out.
            The message is a plain sentence.
    """
    tree = _parse(expression)
    try:
        with localcontext() as context:
            context.prec = PRECISION
            return _evaluate(tree)
    except (InvalidOperation, DivisionByZero):
        raise CalculationError("That calculation cannot be worked out.") from None
    except Overflow:
        raise CalculationError("That number is too large to work with.") from None
    except RecursionError:
        raise CalculationError("That calculation is too complicated.") from None


def literals(expression: str) -> set[Decimal]:
    """Returns every number written in an expression.

    Raises:
        CalculationError: If the expression cannot be read.
    """
    return {
        _number(node.value)
        for node in ast.walk(_parse(expression))
        if isinstance(node, ast.Constant)
    }


def format_result(value: Decimal) -> str:
    """Writes a result for a person: two decimals at most, no trailing zeros.

    Thousands separators are left out so the text can be read back as a number.
    """
    rounded = value.quantize(RESULT_PLACES, rounding=ROUND_HALF_UP)
    text = f"{rounded:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text

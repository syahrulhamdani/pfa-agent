"""Readable answers for requests the API cannot accept.

FastAPI's default 422 body is a list of technical entries (regex patterns, parser
messages). The web app shows `detail` to the person using it, so it needs to say
which field is wrong and what a correct value looks like.
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Field names as the web app labels them, so a message points at something visible.
FIELD_LABELS = {
    "month": "Month",
    "date_from": "From",
    "date_to": "To",
    "min_amount": "Min amount",
    "max_amount": "Max amount",
    "basis": "Date field",
    "direction": "Type",
    "is_transfer": "Counting",
    "category": "Category",
    "name": "Name",
    "ids": "Selection",
    "period": "Period",
    "date": "Date",
    "last4": "Last 4 digits",
    "token": "Sign-in link",
}

# What a valid value looks like. Without an entry, the validator's own text is used.
FIELD_HINTS = {
    "month": "use the format YYYY-MM, for example 2026-10",
    "date_from": "use the format YYYY-MM-DD, for example 2026-10-05",
    "date_to": "use the format YYYY-MM-DD, for example 2026-10-05",
    "min_amount": "enter a number that is not negative, for example 25000",
    "max_amount": "enter a number that is not negative, for example 25000",
    "basis": "choose Receipt date or Confirmed date",
    "direction": "choose Money out or Money in",
    "is_transfer": "choose true or false",
    "name": "enter a name between 1 and 100 characters",
    "ids": "choose between 1 and 500 transactions",
    "period": "choose day, week, month, quarter or year",
    "date": "use the format YYYY-MM-DD, for example 2026-10-05, between 1970 and 2100",
    "category": "choose a category from the list",
    "last4": "enter exactly four digits, or leave it blank",
    "token": "the link is missing or malformed; send /login to pfa for a new one",
}


_PLACES = {"body", "query", "path", "header", "cookie"}


def describe_validation_error(error: dict) -> str:
    """Turns one validation error into a sentence a person can act on."""
    loc = error.get("loc") or ()
    message = str(error.get("msg", "is not valid")).removeprefix("Value error, ")
    # A problem with the request as a whole ("choose a category or a direction") has
    # no field to name, only the place it was found in.
    named = [str(p) for p in loc if not isinstance(p, int)]
    if named and all(p in _PLACES for p in named):
        return message[:1].upper() + message[1:]
    # The field is the last named part of the location; a trailing number is just a
    # position in a list ("ids", 0), which means nothing to the person reading it.
    field = next((str(p) for p in reversed(loc) if not isinstance(p, int)), "request")
    label = FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
    return f"{label}: {FIELD_HINTS.get(field) or message}"


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Answers a 422 with a readable `detail` and a structured `errors` list."""
    errors = exc.errors()
    message = "; ".join(dict.fromkeys(describe_validation_error(e) for e in errors))
    return JSONResponse(
        status_code=422,
        content={
            "detail": message,
            "errors": [
                {"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]}
                for e in errors
            ],
        },
    )

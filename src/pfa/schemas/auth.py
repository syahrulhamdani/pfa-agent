"""Types for sign-in."""

import enum


class TokenType(enum.StrEnum):
    """A login link token cannot be used as a session, and the other way round."""

    LOGIN = "login"
    SESSION = "session"

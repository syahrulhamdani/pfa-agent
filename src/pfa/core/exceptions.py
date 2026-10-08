"""Domain exceptions for pfa."""


class PfaError(Exception):
    """Base class for all pfa errors."""


class LLMError(PfaError):
    """Raised when a Gemini call fails or returns nothing usable."""


class StatementError(PfaError):
    """A problem with a statement, worded so that it can be shown to the user."""

    def __init__(self, message: str) -> None:
        """Keeps the user-facing message."""
        super().__init__(message)
        self.message = message


class AuthError(PfaError):
    """Raised when a token is missing, invalid, expired or of the wrong kind."""

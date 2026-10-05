"""Domain exceptions for pfa."""


class PfaError(Exception):
    """Base class for all pfa errors."""


class LLMError(PfaError):
    """Raised when a Gemini call fails or returns nothing usable."""

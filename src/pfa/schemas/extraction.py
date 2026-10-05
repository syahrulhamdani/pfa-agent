"""Pydantic models for what Gemini returns."""

from pydantic import BaseModel, Field


class ExtractedReceipt(BaseModel):
    """Fields read from one receipt. Anything unreadable stays null."""

    merchant: str | None = Field(None, description="Store or merchant name.")
    amount: float | None = Field(None, description="Total amount paid, as a number.")
    occurred_on: str | None = Field(
        None, description="Purchase date as YYYY-MM-DD, or null if unreadable."
    )
    category: str | None = Field(
        None, description="One name from the allowed category list, or null."
    )
    card_hint: str | None = Field(
        None,
        description=(
            "Anything that identifies the payment card or bank, such as a bank name "
            "or last four digits. Null if the receipt shows nothing."
        ),
    )
    description: str | None = Field(
        None, description="A short description of what was bought."
    )


class CorrectionResult(BaseModel):
    """A user's typed message, interpreted as a correction to a pending receipt."""

    is_correction: bool = Field(
        description="True only if the message changes a field of the pending receipt."
    )
    merchant: str | None = None
    amount: float | None = None
    occurred_on: str | None = Field(None, description="YYYY-MM-DD")
    category: str | None = Field(None, description="Must be an allowed category.")
    card: str | None = Field(
        None, description="Card or bank name, or last four digits."
    )
    description: str | None = None

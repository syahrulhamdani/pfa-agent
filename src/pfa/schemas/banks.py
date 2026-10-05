"""Request and response models for banks and cards."""

from pydantic import BaseModel, ConfigDict, Field


class BankCreate(BaseModel):
    """Body for creating a bank."""

    name: str = Field(min_length=1, max_length=100)


class BankRead(BaseModel):
    """A bank."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class CardCreate(BaseModel):
    """Body for creating a card under a bank."""

    name: str = Field(min_length=1, max_length=100)
    last4: str | None = Field(None, pattern=r"^\d{4}$")


class CardRead(BaseModel):
    """A card."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_id: int
    name: str
    last4: str | None

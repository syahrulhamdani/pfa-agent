"""Routes for banks and cards."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pfa.api.deps import get_session
from pfa.repository.finance import BankRepository, CardRepository
from pfa.schemas.banks import BankCreate, BankRead, CardCreate, CardRead

router = APIRouter(tags=["banks and cards"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/banks", response_model=BankRead, status_code=status.HTTP_201_CREATED)
async def create_bank(body: BankCreate, session: Session):
    """Creates a bank. Names are unique."""
    try:
        return await BankRepository(session).add(body.name.strip())
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bank already exists") from None


@router.get("/banks", response_model=list[BankRead])
async def list_banks(session: Session):
    """Lists all banks."""
    return await BankRepository(session).list_all()


@router.post(
    "/banks/{bank_id}/cards",
    response_model=CardRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_card(bank_id: int, body: CardCreate, session: Session):
    """Creates a card under a bank."""
    if await BankRepository(session).get(bank_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank not found")
    return await CardRepository(session).add(bank_id, body.name.strip(), body.last4)


@router.get("/cards", response_model=list[CardRead])
async def list_cards(session: Session):
    """Lists all cards."""
    return await CardRepository(session).list_all()

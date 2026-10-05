"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pfa.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Creates the async engine for the configured database."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Creates a session factory. Sessions do not expire objects on commit."""
    return async_sessionmaker(engine, expire_on_commit=False)

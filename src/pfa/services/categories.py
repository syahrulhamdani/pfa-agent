"""Category list: configured in a JSON file, seeded into the database at startup."""

import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pfa.core.exceptions import PfaError
from pfa.models import Category


def load_category_names(path: str | Path) -> list[str]:
    """Reads and validates the configured category names.

    Args:
        path: JSON file holding a list of category names.

    Returns:
        Names with surrounding whitespace removed and duplicates dropped, in order.

    Raises:
        PfaError: If the file is missing, is not a JSON list of strings, or has
            no usable names.
    """
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PfaError(f"cannot read categories from {path}: {exc}") from exc
    if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
        raise PfaError(f"{path} must contain a JSON list of strings")
    names = list(dict.fromkeys(n.strip() for n in raw if n.strip()))
    if not names:
        raise PfaError(f"{path} has no category names")
    return names


async def seed_categories(
    session_factory: async_sessionmaker[AsyncSession], names: list[str]
) -> None:
    """Inserts any missing categories. Never deletes or renames existing ones.

    Existing transactions reference categories, so removing a name from the file
    leaves it in the database.
    """
    async with session_factory() as session:
        await session.execute(
            insert(Category)
            .values([{"name": n} for n in names])
            .on_conflict_do_nothing(index_elements=["name"])
        )
        await session.commit()

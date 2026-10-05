"""Boundary: the category file is validated, and seeding is idempotent."""

import json

import pytest
from sqlalchemy import select

from pfa.core.exceptions import PfaError
from pfa.models import Category
from pfa.services.categories import load_category_names, seed_categories


def _write(tmp_path, content) -> str:
    path = tmp_path / "categories.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return str(path)


def test_load_strips_and_dedupes(tmp_path):
    path = _write(tmp_path, [" Dining ", "Groceries", "Dining", "", "  "])
    assert load_category_names(path) == ["Dining", "Groceries"]


@pytest.mark.parametrize("content", ["not json", '{"a": 1}', "[1, 2]", "[]", '["  "]'])
def test_load_rejects_bad_files(tmp_path, content):
    with pytest.raises(PfaError):
        load_category_names(_write(tmp_path, content))


def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(PfaError):
        load_category_names(tmp_path / "nope.json")


def test_repo_default_file_is_valid():
    assert "Other" in load_category_names("config/categories.json")


async def test_seed_adds_missing_and_never_deletes(session_factory):
    await seed_categories(session_factory, ["Dining", "Travel"])
    await seed_categories(session_factory, ["Dining", "Pets"])  # Travel dropped
    async with session_factory() as session:
        names = set(await session.scalars(select(Category.name)))
    assert {"Dining", "Travel", "Pets"} <= names

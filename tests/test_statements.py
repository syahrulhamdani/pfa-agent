"""Boundary: statement files become clean rows; the summary is computed in code."""

import io
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from pfa.core.exceptions import StatementError
from pfa.models.finance import Direction
from pfa.schemas.extraction import ExtractedStatementRow
from pfa.schemas.statements import Spend
from pfa.services.statements import (
    MAX_ROWS,
    ROWS_PER_BATCH,
    looks_like_duplicate,
    normalize_rows,
    parse_csv,
    parse_xlsx,
    read_table,
    statement_format,
    summarize,
    summarize_by_direction,
    table_batches,
)

# --- which files count as statements ---


@pytest.mark.parametrize(
    ("filename", "mime", "expected"),
    [
        ("march.pdf", "application/pdf", "pdf"),
        ("MARCH.PDF", None, "pdf"),
        ("march.csv", "text/csv", "csv"),
        ("march.CSV", "application/octet-stream", "csv"),
        ("march.xlsx", None, "xlsx"),
        ("noext", "application/pdf", "pdf"),  # no extension: the MIME type decides
        ("noext", "text/csv; charset=utf-8", "csv"),
        (
            "noext",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        ),
        ("old.xls", "application/vnd.ms-excel", None),  # legacy Excel is unsupported
        (
            "old.xls",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            None,
        ),
        ("notes.txt", "text/plain", None),
        ("photo.png", "image/png", None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_statement_format(filename, mime, expected):
    assert statement_format(filename, mime) == expected


# --- CSV ---


@pytest.mark.parametrize(
    "delimiter", [",", ";", "\t", "|"], ids=["comma", "semicolon", "tab", "pipe"]
)
def test_csv_delimiters_are_guessed(delimiter):
    text = delimiter.join(["Date", "Merchant", "Amount"]) + "\n"
    text += delimiter.join(["2026-10-01", "Indomaret", "45000"]) + "\n"
    text += delimiter.join(["2026-10-02", "Grab", "30000"]) + "\n"
    assert parse_csv(text.encode()) == [
        ["Date", "Merchant", "Amount"],
        ["2026-10-01", "Indomaret", "45000"],
        ["2026-10-02", "Grab", "30000"],
    ]


def test_csv_handles_quotes_bom_blank_lines_and_spaces():
    text = '﻿Date,Merchant,Amount\n\n"2026-10-01"," Toko, Maju ",45000\n,,\n'
    assert parse_csv(text.encode("utf-8")) == [
        ["Date", "Merchant", "Amount"],
        ["2026-10-01", "Toko, Maju", "45000"],
    ]


def test_csv_falls_back_to_latin_1():
    rows = parse_csv("Date,Merchant,Amount\n2026-10-01,Café,10\n".encode("latin-1"))
    assert rows[1][1] == "Café"


def test_empty_csv_has_no_rows():
    assert parse_csv(b"") == []
    assert parse_csv(b"\n\n,,\n") == []


# --- Excel ---


def workbook_bytes(*sheets: list[list]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index, rows in enumerate(sheets):
        sheet = workbook.create_sheet(f"Sheet{index + 1}")
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_xlsx_cells_become_readable_text():
    content = workbook_bytes(
        [
            ["Date", "Merchant", "Amount", "Note"],
            [datetime(2026, 10, 1), "Indomaret", 45000.5, None],
            [date(2026, 10, 2), "Grab", 30000, "ride"],
            [datetime(2026, 10, 3, 14, 30), "Cafe", 12.0, ""],
        ]
    )
    assert parse_xlsx(content) == [
        ["Date", "Merchant", "Amount", "Note"],
        ["2026-10-01", "Indomaret", "45000.5", ""],
        ["2026-10-02", "Grab", "30000", "ride"],
        ["2026-10-03 14:30:00", "Cafe", "12", ""],
    ]


def test_xlsx_uses_the_first_non_empty_sheet():
    content = workbook_bytes([], [["Date", "Amount"], ["2026-10-01", 5]])
    assert parse_xlsx(content) == [["Date", "Amount"], ["2026-10-01", "5"]]


def test_xlsx_that_is_not_a_workbook_is_a_clear_error():
    with pytest.raises(StatementError, match="valid .xlsx"):
        parse_xlsx(b"this is not an excel file")


# --- reading a table with limits ---


async def test_read_table_returns_rows_for_csv_and_xlsx():
    csv_rows = await read_table(b"Date,Amount\n2026-10-01,5\n", "csv")
    xlsx_rows = await read_table(
        workbook_bytes([["Date", "Amount"], ["2026-10-01", 5]]), "xlsx"
    )
    assert csv_rows == [["Date", "Amount"], ["2026-10-01", "5"]]
    assert xlsx_rows == [["Date", "Amount"], ["2026-10-01", "5"]]


@pytest.mark.parametrize("content", [b"", b"Date,Amount\n"])
async def test_a_file_with_no_data_rows_is_rejected(content):
    with pytest.raises(StatementError, match="couldn't find any transaction rows"):
        await read_table(content, "csv")


async def test_the_row_limit_is_enforced_but_the_limit_itself_is_allowed():
    def table(rows: int) -> bytes:
        return ("Date,Amount\n" + "2026-10-01,5\n" * rows).encode()

    assert len(await read_table(table(MAX_ROWS), "csv")) == MAX_ROWS + 1
    with pytest.raises(StatementError, match=f"limit is {MAX_ROWS}"):
        await read_table(table(MAX_ROWS + 1), "csv")


async def test_an_oversized_file_is_rejected_before_parsing():
    with pytest.raises(StatementError, match="larger than 10 MB"):
        await read_table(b"x" * (10 * 1024 * 1024 + 1), "csv")


# --- batches for the model ---


def test_batches_repeat_the_header_and_cover_every_row():
    rows = [["Date", "Amount"]] + [
        [f"2026-10-{i % 28 + 1:02d}", str(i)] for i in range(250)
    ]
    batches = table_batches(rows)
    assert len(batches) == 3  # 100 + 100 + 50
    assert all(b.splitlines()[0] == "Date\tAmount" for b in batches)
    assert [len(b.splitlines()) - 1 for b in batches] == [100, 100, 50]
    assert sum(len(b.splitlines()) - 1 for b in batches) == 250
    assert ROWS_PER_BATCH == 100


def test_cell_text_cannot_break_the_tab_separated_layout():
    batch = table_batches([["A", "B"], ["multi\nline", "tab\there"]])[0]
    assert batch.splitlines() == ["A\tB", "multi line\ttab here"]


# --- cleaning what the model returned ---


def row(**fields) -> ExtractedStatementRow:
    base = {"merchant": "Indomaret", "amount": 45000, "occurred_on": "2026-10-01"}
    return ExtractedStatementRow(**{**base, **fields})


def test_complete_spending_lines_are_kept_with_positive_amounts():
    result = normalize_rows(
        [row(amount=-45000.5, category=" Groceries ", description=" snacks ")]
    )
    (kept,) = result.rows
    assert kept.amount == Decimal("45000.50")
    assert kept.merchant == "Indomaret"
    assert kept.occurred_on == date(2026, 10, 1)
    assert kept.category == "Groceries"
    assert kept.description == "snacks"


def test_money_in_is_kept_with_its_direction_and_a_positive_amount():
    result = normalize_rows(
        [
            row(direction="out"),
            row(merchant="Salary", amount=9_000_000, direction="in"),
            row(merchant="Refund", amount=-12000.5, direction="in"),
        ]
    )
    assert [(r.merchant, r.direction) for r in result.rows] == [
        ("Indomaret", Direction.OUT),
        ("Salary", Direction.IN),
        ("Refund", Direction.IN),
    ]
    assert result.rows[2].amount == Decimal("12000.50")  # always positive
    assert result.skipped_unreadable == 0


def test_a_line_defaults_to_money_out_when_the_model_gives_no_direction():
    (kept,) = normalize_rows([row()]).rows
    assert kept.direction is Direction.OUT


@pytest.mark.parametrize(
    "bad",
    [
        {"merchant": None},
        {"merchant": "   "},
        {"amount": None},
        {"amount": 0},
        {"amount": float("nan")},
        {"amount": float("inf")},
        {"occurred_on": None},
        {"occurred_on": "5 Oct"},
        {"occurred_on": "2026-02-30"},
    ],
)
def test_lines_missing_a_required_value_are_left_out_not_guessed(bad):
    result = normalize_rows([row(**bad)])
    assert result.rows == []
    assert result.skipped_unreadable == 1


def test_blank_category_and_description_become_none():
    (kept,) = normalize_rows([row(category="  ", description="")]).rows
    assert kept.category is None
    assert kept.description is None


def test_a_mixed_statement_is_counted_exactly():
    result = normalize_rows(
        [
            row(),
            row(),
            row(direction="in"),
            row(amount=None),
            row(merchant=None, direction="in"),
        ]
    )
    assert len(result.rows) == 3
    assert [r.direction for r in result.rows].count(Direction.IN) == 1
    assert result.skipped_unreadable == 2  # unreadable lines are counted for both


# --- duplicates of saved transactions ---

BASE = Spend(
    merchant="Indomaret",
    amount=Decimal("45000.00"),
    occurred_on=date(2026, 10, 1),
    direction=Direction.OUT,
)


def like_base(**overrides) -> Spend:
    return BASE.model_copy(update=overrides)


def test_the_same_date_amount_and_merchant_is_a_duplicate_ignoring_case_and_spaces():
    assert looks_like_duplicate(BASE, BASE)
    assert looks_like_duplicate(like_base(merchant=" INDOMARET "), BASE)


@pytest.mark.parametrize(
    "other",
    [
        like_base(amount=Decimal("45000.01")),
        like_base(occurred_on=date(2026, 10, 2)),
        like_base(merchant="Alfamart"),
        like_base(direction=Direction.IN),  # a refund is not the purchase it undoes
    ],
    ids=["amount", "date", "merchant", "direction"],
)
def test_a_difference_in_any_part_is_not_a_duplicate(other):
    assert not looks_like_duplicate(BASE, other)
    assert not looks_like_duplicate(other, BASE)


# --- the summary ---


def test_an_empty_summary_has_no_extremes():
    summary = summarize([])
    assert (summary.count, summary.total, summary.highest, summary.lowest) == (
        0,
        Decimal("0.00"),
        None,
        None,
    )


def test_the_summary_is_exact_decimal_arithmetic():
    summary = summarize([Decimal("0.10"), Decimal("0.20"), Decimal("45000.00")])
    assert summary.count == 3
    assert summary.total == Decimal("45000.30")  # floats would give 45000.300000000003
    assert summary.highest == Decimal("45000.00")
    assert summary.lowest == Decimal("0.10")


def test_a_single_line_is_both_highest_and_lowest():
    summary = summarize([Decimal("12.50")])
    assert summary.highest == summary.lowest == summary.total == Decimal("12.50")


def test_money_in_and_out_are_summarised_separately():
    totals = summarize_by_direction(
        [
            (Direction.OUT, Decimal("100.00")),
            (Direction.OUT, Decimal("50.50")),
            (Direction.IN, Decimal("1000.00")),
            (Direction.OUT, Decimal("0.50")),
        ]
    )
    assert totals.money_out.count == 3
    assert totals.money_out.total == Decimal("151.00")
    assert totals.money_out.highest == Decimal("100.00")
    assert totals.money_out.lowest == Decimal("0.50")
    assert totals.money_in.count == 1
    assert totals.money_in.total == Decimal("1000.00")


def test_a_statement_with_only_one_direction_has_an_empty_other_side():
    only_in = summarize_by_direction([(Direction.IN, Decimal("5.00"))])
    assert only_in.money_out.count == 0
    assert only_in.money_out.total == Decimal("0.00")
    assert only_in.money_out.highest is None
    assert summarize_by_direction([]).money_in.count == 0

"""Boundary: statements reach the model as text batches or a PDF, then merge."""

import base64
import io

import pytest
from langchain_core.messages import HumanMessage
from openpyxl import Workbook

from pfa.core.exceptions import LLMError, StatementError
from pfa.graphs.extractors import GeminiStatementExtractor
from pfa.schemas.extraction import ExtractedStatement, ExtractedStatementRow

CATEGORIES = ["Groceries", "Dining", "Other"]


class QueueModel:
    """Stands in for the model: returns queued answers and records what it was sent."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.sent: list[list] = []

    def with_structured_output(self, schema):
        assert schema is ExtractedStatement
        return self

    async def ainvoke(self, messages, config=None):
        self.sent.append(messages)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def line(merchant="Indomaret", amount=45000, day="2026-10-01"):
    return ExtractedStatementRow(merchant=merchant, amount=amount, occurred_on=day)


def blocks_of(model: QueueModel, call: int = 0) -> list[dict]:
    (message,) = model.sent[call]
    assert isinstance(message, HumanMessage)
    return message.content


def csv_bytes(rows: int) -> bytes:
    body = "".join(
        f"2026-10-{i % 28 + 1:02d},Shop {i},{1000 + i}\n" for i in range(rows)
    )
    return ("Date,Merchant,Amount\n" + body).encode()


async def test_a_csv_is_sent_as_text_with_its_header_and_the_categories():
    model = QueueModel(ExtractedStatement(card_hint="BCA 1234", transactions=[line()]))
    result = await GeminiStatementExtractor(model)(csv_bytes(3), "csv", CATEGORIES)

    assert len(model.sent) == 1
    (block,) = blocks_of(model)
    assert block["type"] == "text"  # no file attached: the rows are the text
    assert "Groceries, Dining, Other" in block["text"]
    assert "Date\tMerchant\tAmount" in block["text"]
    assert "Shop 0" in block["text"]
    assert result.card_hint == "BCA 1234"
    assert [t.merchant for t in result.transactions] == ["Indomaret"]


async def test_a_pdf_is_sent_as_a_file_block_with_the_original_bytes():
    pdf = b"%PDF-1.7 pretend statement"
    model = QueueModel(ExtractedStatement(transactions=[line()]))
    await GeminiStatementExtractor(model)(pdf, "pdf", CATEGORIES)

    text_block, file_block = blocks_of(model)
    assert text_block["type"] == "text"
    assert file_block["type"] == "file"
    assert file_block["mime_type"] == "application/pdf"
    assert base64.b64decode(file_block["base64"]) == pdf
    assert len(model.sent) == 1


async def test_a_long_spreadsheet_is_sent_in_batches_and_merged_in_order():
    model = QueueModel(
        ExtractedStatement(transactions=[line("A1"), line("A2")]),
        ExtractedStatement(card_hint="Mandiri 9999", transactions=[line("B1")]),
        ExtractedStatement(card_hint="ignored later hint", transactions=[line("C1")]),
    )
    result = await GeminiStatementExtractor(model)(csv_bytes(250), "csv", CATEGORIES)

    assert len(model.sent) == 3  # 100 + 100 + 50 rows
    for call in range(3):
        assert "Date\tMerchant\tAmount" in blocks_of(model, call)[0]["text"]
    assert [t.merchant for t in result.transactions] == ["A1", "A2", "B1", "C1"]
    assert result.card_hint == "Mandiri 9999"  # the first hint found wins


async def test_an_excel_statement_is_read_in_python_then_sent_as_text():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Date", "Merchant", "Amount"])
    sheet.append(["2026-10-01", "Indomaret", 45000])
    buffer = io.BytesIO()
    workbook.save(buffer)

    model = QueueModel(ExtractedStatement(transactions=[line()]))
    await GeminiStatementExtractor(model)(buffer.getvalue(), "xlsx", CATEGORIES)
    (block,) = blocks_of(model)
    assert "Indomaret\t45000" in block["text"]


async def test_no_card_hint_anywhere_gives_none():
    model = QueueModel(ExtractedStatement(transactions=[line()]))
    result = await GeminiStatementExtractor(model)(csv_bytes(2), "csv", CATEGORIES)
    assert result.card_hint is None


@pytest.mark.parametrize("content", [b"", b"Date,Merchant,Amount\n"])
async def test_an_empty_spreadsheet_never_reaches_the_model(content):
    model = QueueModel()
    with pytest.raises(StatementError):
        await GeminiStatementExtractor(model)(content, "csv", CATEGORIES)
    assert model.sent == []


async def test_a_model_failure_becomes_an_llm_error():
    model = QueueModel(RuntimeError("rate limited"))
    with pytest.raises(LLMError, match="rate limited"):
        await GeminiStatementExtractor(model)(csv_bytes(2), "csv", CATEGORIES)


async def test_a_failure_in_a_later_batch_fails_the_whole_statement():
    model = QueueModel(
        ExtractedStatement(transactions=[line()]), RuntimeError("timeout")
    )
    with pytest.raises(LLMError):
        await GeminiStatementExtractor(model)(csv_bytes(150), "csv", CATEGORIES)

import io

import pytest
from openpyxl import Workbook

from apps.labtemplates.choice_import import HEADERS, download_template, parse_choices
from apps.labtemplates.errors import TemplateValidationError


def workbook_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_download_template_is_valid_and_answers_remain_private() -> None:
    rows, errors = parse_choices(download_template())
    assert errors == []
    assert rows[0]["task_type"] == "SINGLE_CHOICE"
    assert rows[0]["marking_spec"]["correct_option_ids"] == ["B"]
    assert "correct_option_ids" not in rows[0]["question_spec"]


def test_import_reports_row_errors_without_silently_skipping_invalid_answers() -> None:
    rows, errors = parse_choices(workbook_bytes([
        ["单选", "valid", "A", "B", "", "", "", "", "A", 5, ""],
        ["单选", "two answers", "A", "B", "", "", "", "", "A,B", 5, ""],
        ["多选", "formula", "=1+1", "B", "", "", "", "", "A,B", 5, ""],
        ["多选", "missing option", "A", "B", "", "", "", "", "A,C", 5, ""],
    ]))
    assert len(rows) == 1
    assert {error["row"] for error in errors} == {3, 4, 5}


def test_invalid_file_is_rejected() -> None:
    for content in (b"", b"not an xlsx"):
        with pytest.raises(TemplateValidationError):
            parse_choices(content)

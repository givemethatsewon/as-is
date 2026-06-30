from __future__ import annotations

from datetime import date

from app.services.uploads import preview_exports, preview_imports
from tests.helpers import add_import_lot


def test_import_preview_classifies_new_duplicate_conflict_and_error(db_session):
    add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2025, 1, 1),
        origin="CN",
        part="PN1",
        qty=10,
        line_no="001",
        row_no="01",
    )
    rows = [
        {
            "import_declaration_no": "A",
            "import_accepted_date": "2025-01-01",
            "origin": "CN",
            "hs_code": "8708309000",
            "line_no": "001",
            "row_no": "01",
            "part_number": "PN1",
            "spec": "TEST",
            "import_qty": "10",
            "qty_unit": "PC",
        },
        {
            "import_declaration_no": "A",
            "import_accepted_date": "2025-01-01",
            "origin": "CN",
            "hs_code": "8708309000",
            "line_no": "001",
            "row_no": "01",
            "part_number": "PN1",
            "spec": "TEST",
            "import_qty": "99",
            "qty_unit": "PC",
        },
        {
            "import_declaration_no": "B",
            "import_accepted_date": "2025-01-02",
            "origin": "CN",
            "hs_code": "8708309000",
            "line_no": "001",
            "row_no": "02",
            "part_number": "PN2",
            "spec": "TEST",
            "import_qty": "20",
            "qty_unit": "PC",
        },
        {
            "import_declaration_no": "C",
            "import_accepted_date": "bad-date",
            "origin": "CN",
            "hs_code": "8708309000",
            "line_no": "001",
            "row_no": "03",
            "part_number": "PN3",
            "spec": "TEST",
            "import_qty": "20",
            "qty_unit": "PC",
        },
    ]

    result = preview_imports(db_session, rows, "imports.csv")

    assert result.batch.duplicate_count == 1
    assert result.batch.conflict_count == 1
    assert result.batch.new_count == 1
    assert result.batch.error_count == 1


def test_import_preview_treats_spec_difference_as_conflict(db_session):
    add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2025, 1, 1),
        origin="CN",
        part="PN1",
        qty=10,
        line_no="001",
        row_no="01",
    )
    rows = [
        {
            "import_declaration_no": "A",
            "import_accepted_date": "2025-01-01",
            "origin": "CN",
            "hs_code": "8708309000",
            "line_no": "001",
            "row_no": "01",
            "part_number": "PN1",
            "spec": "DIFFERENT SPEC",
            "import_qty": "10",
            "qty_unit": "PC",
        }
    ]

    result = preview_imports(db_session, rows, "imports.csv")

    assert result.batch.duplicate_count == 0
    assert result.batch.conflict_count == 1


def test_export_preview_supports_contest_sample_headers(db_session):
    rows = [
        {
            "export_date": "2025-08-16",
            "Part Number": "MTG011114",
            "Description": "STEERING RACK",
            "U/Price": "3.5",
            "Qty": "800",
            "Amount": "2800",
            "원산지": "CN",
            "세번": "8708309000",
        }
    ]

    result = preview_exports(db_session, rows, "contest-export.xlsx")

    assert result.batch.new_count == 1
    assert result.batch.error_count == 0
    assert result.column_mapping["part_number"] == "Part Number"
    assert result.column_mapping["description"] == "Description"
    assert result.column_mapping["unit_price"] == "U/Price"
    assert result.column_mapping["export_date"] == "export_date"
    assert result.column_mapping["required_qty"] == "Qty"
    assert result.column_mapping["amount"] == "Amount"
    assert result.column_mapping["hs_code"] == "세번"


def test_export_preview_missing_required_column_uses_korean_message(db_session):
    rows = [{"Part Number": "MTG011114", "Qty": "800", "원산지": "CN"}]

    try:
        preview_exports(db_session, rows, "bad-export.xlsx")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("필수 컬럼 누락은 ValueError가 발생해야 합니다.")

    assert "필수 컬럼이 누락됐습니다" in message
    assert "수출 예정일 또는 수출일" in message
    assert "업로드 파일 컬럼" in message

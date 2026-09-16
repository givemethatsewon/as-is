from __future__ import annotations

from datetime import date

from app.services.uploads import preview_export_run
from tests.helpers import add_import_lot


def test_workbench_has_two_separate_primary_excel_actions(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "운영 워크벤치" in response.text
    assert "수입 재고 추가" in response.text
    assert "수출 매칭 시작" in response.text
    assert 'data-upload-type="imports"' in response.text
    assert 'data-upload-type="exports"' in response.text
    assert "직접 입력" not in response.text
    assert "Part Number · FIFO" in response.text
    assert "720일" not in response.text
    assert "품번 + 원산지" not in response.text


def test_export_review_groups_rows_with_expandable_allocations_and_shortage(client, db_session) -> None:
    add_import_lot(
        db_session,
        declaration="IMP-A",
        accepted=date(2026, 1, 1),
        origin="CN",
        part="PN-1",
        qty=3,
        hs_code="8501",
    )
    run = preview_export_run(
        db_session,
        [
            {
                "export_date": "2026-02-01",
                "order_no": "ORDER-1",
                "seq_no": "1",
                "origin": "CN",
                "part_number": "PN-1",
                "required_qty": "5",
            }
        ],
        "exports.xlsx",
    )

    response = client.get(f"/batches/{run.batch.id}")

    assert response.status_code == 200
    assert "수출 배정 검토" in response.text
    assert "ORDER-1" in response.text
    assert "IMP-A" in response.text
    assert "NO MATCH" in response.text
    assert "미배정 수량 2" in response.text
    assert "확정하고 재고 차감" in response.text
    assert "<details" in response.text
    assert "수입신고번호" in response.text
    assert "신고일자" in response.text
    assert "세번" in response.text
    assert "차감 전 수량" in response.text
    assert "차감 수량" in response.text
    assert "차감 후 잔량" in response.text


def test_batch_review_uses_50_row_pagination(client, db_session) -> None:
    rows = [
        {
            "import_declaration_no": f"IMP-{index:03d}",
            "import_accepted_date": "2026-01-01",
            "origin": "CN",
            "hs_code": "8501",
            "line_no": "1",
            "row_no": str(index),
            "part_number": f"PN-{index}",
            "spec": "ITEM",
            "import_qty": "1",
            "qty_unit": "PC",
        }
        for index in range(51)
    ]
    from app.services.uploads import preview_imports

    batch = preview_imports(db_session, rows, "imports.xlsx").batch

    first = client.get(f"/batches/{batch.id}")
    second = client.get(f"/batches/{batch.id}?page=2")

    assert first.text.count('class="review-row') == 50
    assert second.text.count('class="review-row') == 1
    assert "2 / 2" in second.text


def test_history_shows_result_download_and_file_level_revert(client, db_session) -> None:
    add_import_lot(
        db_session,
        declaration="IMP-A",
        accepted=date(2026, 1, 1),
        origin="CN",
        part="PN-1",
        qty=5,
    )
    from app.services.uploads import confirm_match_run

    run = preview_export_run(
        db_session,
        [{"export_date": "2026-02-01", "origin": "CN", "part_number": "PN-1", "required_qty": "2"}],
        "exports.xlsx",
    )
    confirm_match_run(db_session, run.batch.id)

    response = client.get("/history")

    assert response.status_code == 200
    assert "exports.xlsx" in response.text
    assert f"/api/match-runs/{run.batch.id}/result.xlsx" in response.text
    assert f"/batches/{run.batch.id}/revert" in response.text
    assert "파일 전체 되돌리기" in response.text


def test_frontend_contains_progress_polling_and_csrf_header() -> None:
    script = open("app/static/app.js", encoding="utf-8").read()

    assert "/api/upload-batches/" in script
    assert "X-CSRF-Token" in script
    assert "setInterval" in script

from __future__ import annotations

from datetime import date

from app.services.matching import run_matching
from app.services.summaries import expiring_import_lots, hs_code_warning_rows, matching_status_distribution
from tests.helpers import add_export_requirement, add_import_lot


def test_expiring_import_lots_returns_soonest_remaining_lots(db_session):
    soon = add_import_lot(db_session, declaration="A", accepted=date(2025, 5, 20), origin="CN", part="PN1", qty=10)
    later = add_import_lot(db_session, declaration="B", accepted=date(2025, 5, 30), origin="CN", part="PN2", qty=20)
    not_soon = add_import_lot(db_session, declaration="C", accepted=date(2025, 7, 1), origin="CN", part="PN3", qty=30)

    rows = expiring_import_lots(db_session, date(2026, 5, 1))

    assert [row["import_declaration_no"] for row in rows] == [soon.import_declaration_no, later.import_declaration_no]
    assert rows[0]["days_left"] == 14
    assert rows[1]["days_left"] == 24
    assert not_soon.import_declaration_no not in [row["import_declaration_no"] for row in rows]


def test_matching_status_distribution_includes_labels_and_percentages(db_session):
    matched = add_export_requirement(db_session, exported=date(2025, 1, 1), origin="CN", part="PN1", qty=1)
    partial = add_export_requirement(db_session, exported=date(2025, 1, 2), origin="CN", part="PN2", qty=1)
    matched.status = "matched"
    partial.status = "partial_matched"
    db_session.commit()

    rows = matching_status_distribution(db_session)

    by_status = {row["status"]: row for row in rows}
    assert by_status["matched"]["label"] == "매칭 완료"
    assert by_status["matched"]["count"] == 1
    assert by_status["partial_matched"]["percent"] == 50
    assert by_status["pending"]["count"] == 0


def test_hs_code_warning_rows_for_dashboard(db_session):
    add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2025, 1, 1),
        origin="CN",
        part="PN1",
        qty=10,
        hs_code="1111111111",
    )
    add_export_requirement(db_session, exported=date(2025, 2, 1), origin="CN", part="PN1", qty=5, hs_code="2222222222")

    run_matching(db_session)
    rows = hs_code_warning_rows(db_session)

    assert rows == [
        {
            "export_date": "2025-02-01",
            "part_number": "PN1",
            "origin": "CN",
            "export_hs_code": "2222222222",
            "import_hs_code": "1111111111",
            "import_declaration_no": "A",
            "line_no": "004",
            "row_no": "01",
            "matched_qty": 5,
        }
    ]


def test_dashboard_page_shows_customs_practitioner_insight_sections(client):
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "만료 임박 수입신고 Top 10" in response.text
    assert "수출 매칭 상태 분포" in response.text
    assert "HS 코드 확인 필요 목록" in response.text

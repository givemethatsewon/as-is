from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import ExportAllocation, ExportRequirement, ImportLot, PlannedAllocation, UploadPreviewRow
from app.services.uploads import (
    confirm_batch,
    confirm_match_run,
    preview_export_run,
    preview_imports,
    revert_match_run,
)
from tests.helpers import add_import_lot


def import_row(*, declaration: str, qty: int, spec: str = "TEST", part: str = "PN-1") -> dict[str, str]:
    return {
        "import_declaration_no": declaration,
        "import_accepted_date": "2026-01-01",
        "origin": "CN",
        "hs_code": "8501",
        "line_no": "1",
        "row_no": "1",
        "part_number": part,
        "spec": spec,
        "import_qty": str(qty),
        "qty_unit": "PC",
    }


def export_row(*, qty: int, seq: str = "1", hs_code: str = "DIFFERENT") -> dict[str, str]:
    return {
        "export_date": "2026-02-01",
        "order_no": "ORDER-1",
        "seq_no": seq,
        "origin": "CN",
        "part_number": " P N-1 ",
        "hs_code": hs_code,
        "required_qty": str(qty),
        "description": "MOTOR",
        "unit_price": "3.5",
        "amount": str(qty * 3.5),
    }


def test_import_exact_duplicate_is_skipped_and_conflict_blocks_whole_batch(db_session) -> None:
    add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2026, 1, 1),
        origin="CN",
        part="PN-1",
        qty=10,
        line_no="1",
        row_no="1",
        hs_code="8501",
    )
    duplicate = preview_imports(db_session, [import_row(declaration="A", qty=10)], "duplicate.xlsx")

    result = confirm_batch(db_session, duplicate.batch.id)

    assert result["inserted_count"] == 0
    assert result["skipped_count"] == 1
    assert duplicate.batch.status == "confirmed"

    conflict = preview_imports(
        db_session,
        [import_row(declaration="A", qty=99), import_row(declaration="B", qty=5)],
        "conflict.xlsx",
    )
    with pytest.raises(ValueError, match="conflict"):
        confirm_batch(db_session, conflict.batch.id)

    assert db_session.scalar(select(func.count()).select_from(ImportLot)) == 1


def test_export_preview_is_read_only_and_reserves_across_rows(db_session) -> None:
    lot = add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2026, 1, 1),
        origin="CN",
        part="PN-1",
        qty=10,
        hs_code="8501",
    )

    preview = preview_export_run(
        db_session,
        [export_row(qty=7, seq="1"), export_row(qty=7, seq="2")],
        "exports.xlsx",
        eligibility_days=720,
    )

    db_session.refresh(lot)
    plans = list(
        db_session.scalars(
                select(PlannedAllocation)
                .join(UploadPreviewRow, PlannedAllocation.preview_row_id == UploadPreviewRow.id)
                .where(PlannedAllocation.batch_id == preview.batch.id)
                .order_by(UploadPreviewRow.row_number, PlannedAllocation.sequence)
        )
    )
    assert lot.remaining_qty == 10
    assert [(plan.matched_qty, plan.shortage_qty, plan.hs_code) for plan in plans] == [
        (7, 0, "8501"),
        (3, 0, "8501"),
        (0, 4, None),
    ]


def test_stale_export_preview_is_rejected_without_stock_mutation(db_session) -> None:
    lot = add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2026, 1, 1),
        origin="CN",
        part="PN-1",
        qty=10,
    )
    preview = preview_export_run(db_session, [export_row(qty=5)], "exports.xlsx", eligibility_days=720)
    lot.remaining_qty = 9
    db_session.commit()

    with pytest.raises(ValueError, match="재고가 변경"):
        confirm_match_run(db_session, preview.batch.id)

    db_session.refresh(lot)
    assert lot.remaining_qty == 9
    assert db_session.scalar(select(func.count()).select_from(ExportAllocation)) == 0


def test_partial_match_confirmation_keeps_allocation_and_shortage(db_session) -> None:
    lot = add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2026, 1, 1),
        origin="CN",
        part="PN-1",
        qty=10,
        hs_code="8501",
    )
    preview = preview_export_run(db_session, [export_row(qty=15)], "exports.xlsx", eligibility_days=720)

    result = confirm_match_run(db_session, preview.batch.id)

    db_session.refresh(lot)
    requirement = db_session.scalar(select(ExportRequirement))
    allocation = db_session.scalar(select(ExportAllocation))
    shortage = db_session.scalar(
        select(PlannedAllocation).where(
            PlannedAllocation.batch_id == preview.batch.id,
            PlannedAllocation.shortage_qty > 0,
        )
    )
    assert result == {"batch_id": preview.batch.id, "export_count": 1, "allocation_count": 1, "shortage_count": 1}
    assert lot.remaining_qty == 0
    assert lot.used_qty == 10
    assert requirement.status == "partial_matched"
    assert allocation.matched_qty == 10
    assert shortage.shortage_qty == 5


def test_export_batch_revert_restores_exact_balances_once_and_keeps_history(db_session) -> None:
    first = add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2026, 1, 1),
        origin="CN",
        part="PN-1",
        qty=4,
    )
    second = add_import_lot(
        db_session,
        declaration="B",
        accepted=date(2026, 1, 2),
        origin="CN",
        part="PN-1",
        qty=6,
    )
    preview = preview_export_run(db_session, [export_row(qty=8)], "exports.xlsx", eligibility_days=720)
    confirm_match_run(db_session, preview.batch.id)

    result = revert_match_run(db_session, preview.batch.id)

    db_session.refresh(first)
    db_session.refresh(second)
    requirements = list(db_session.scalars(select(ExportRequirement)))
    allocations = list(db_session.scalars(select(ExportAllocation)))
    assert result["restored_qty"] == 8
    assert (first.remaining_qty, first.used_qty) == (4, 0)
    assert (second.remaining_qty, second.used_qty) == (6, 0)
    assert requirements[0].status == "reverted"
    assert len(allocations) == 2

    with pytest.raises(ValueError, match="이미 되돌린"):
        revert_match_run(db_session, preview.batch.id)

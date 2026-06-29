from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.models import ExportAllocation, ImportLot
from app.services.matching import run_matching, undo_export_matching
from tests.helpers import add_export_requirement, add_import_lot


def test_fifo_split_allocation(db_session):
    first = add_import_lot(
        db_session,
        declaration="A",
        accepted=date(2025, 1, 16),
        origin="CN",
        part="MTG011114",
        qty=1256,
        row_no="01",
    )
    second = add_import_lot(
        db_session,
        declaration="B",
        accepted=date(2025, 3, 16),
        origin="CN",
        part="MTG011114",
        qty=1256,
        row_no="02",
    )
    add_export_requirement(db_session, exported=date(2025, 8, 16), origin="CN", part="MTG011114", qty=800)
    add_export_requirement(db_session, exported=date(2025, 12, 16), origin="CN", part="MTG011114", qty=800)

    summary = run_matching(db_session)

    db_session.refresh(first)
    db_session.refresh(second)
    allocations = db_session.scalars(select(ExportAllocation).order_by(ExportAllocation.created_at)).all()
    assert summary.matched_count == 2
    assert summary.allocation_count == 3
    assert [allocation.matched_qty for allocation in allocations] == [800, 456, 344]
    assert first.remaining_qty == 0
    assert first.status == "used_up"
    assert second.remaining_qty == 912


def test_origin_mismatch_is_excluded(db_session):
    add_import_lot(db_session, declaration="A", accepted=date(2025, 1, 1), origin="KR", part="PN1", qty=100)
    export = add_export_requirement(db_session, exported=date(2025, 2, 1), origin="CN", part="PN1", qty=10)

    run_matching(db_session)

    db_session.refresh(export)
    allocation_count = db_session.scalar(select(func.count(ExportAllocation.id)))
    assert export.status == "insufficient_stock"
    assert allocation_count == 0


def test_720_day_policy_allows_lot_after_one_year(db_session):
    lot = add_import_lot(db_session, declaration="A", accepted=date(2025, 1, 1), origin="CN", part="PN1", qty=100)
    export = add_export_requirement(db_session, exported=date(2025, 12, 28), origin="CN", part="PN1", qty=10)

    run_matching(db_session)

    db_session.refresh(lot)
    db_session.refresh(export)
    assert lot.status == "available"
    assert lot.remaining_qty == 90
    assert export.status == "matched"


def test_720_day_expired_lot_is_excluded(db_session):
    lot = add_import_lot(db_session, declaration="A", accepted=date(2025, 1, 1), origin="CN", part="PN1", qty=100)
    export = add_export_requirement(db_session, exported=date(2027, 1, 1), origin="CN", part="PN1", qty=10)

    run_matching(db_session)

    db_session.refresh(lot)
    db_session.refresh(export)
    assert lot.status == "expired"
    assert lot.remaining_qty == 100
    assert export.status == "insufficient_stock"


def test_insufficient_stock_becomes_partial_when_some_qty_allocated(db_session):
    lot = add_import_lot(db_session, declaration="A", accepted=date(2025, 1, 1), origin="CN", part="PN1", qty=10)
    export = add_export_requirement(db_session, exported=date(2025, 2, 1), origin="CN", part="PN1", qty=25)

    run_matching(db_session)

    db_session.refresh(lot)
    db_session.refresh(export)
    assert export.status == "partial_matched"
    assert lot.remaining_qty == 0
    assert lot.status == "used_up"


def test_rerun_matching_does_not_duplicate_existing_allocations(db_session):
    add_import_lot(db_session, declaration="A", accepted=date(2025, 1, 1), origin="CN", part="PN1", qty=20)
    export = add_export_requirement(db_session, exported=date(2025, 2, 1), origin="CN", part="PN1", qty=10)

    first = run_matching(db_session)
    second = run_matching(db_session)

    db_session.refresh(export)
    allocation_count = db_session.scalar(select(func.count(ExportAllocation.id)))
    assert first.allocation_count == 1
    assert second.allocation_count == 0
    assert allocation_count == 1
    assert export.status == "matched"


def test_hs_code_warning_does_not_block_matching(db_session):
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

    allocation = db_session.scalar(select(ExportAllocation))
    assert allocation is not None
    assert "differs" in allocation.hs_code_warning


def test_zero_remaining_lot_is_excluded_from_matching(db_session):
    lot = add_import_lot(db_session, declaration="A", accepted=date(2025, 1, 1), origin="CN", part="PN1", qty=10)
    lot.used_qty = 10
    lot.remaining_qty = 0
    lot.status = "used_up"
    db_session.commit()
    export = add_export_requirement(db_session, exported=date(2025, 2, 1), origin="CN", part="PN1", qty=5)

    run_matching(db_session)

    db_session.refresh(export)
    assert export.status == "insufficient_stock"
    assert db_session.scalar(select(func.count(ExportAllocation.id))) == 0


def test_undo_export_matching_restores_stock_and_pending_status(db_session):
    lot = add_import_lot(db_session, declaration="A", accepted=date(2025, 1, 1), origin="CN", part="PN1", qty=10)
    export = add_export_requirement(db_session, exported=date(2025, 2, 1), origin="CN", part="PN1", qty=7)
    run_matching(db_session)

    db_session.refresh(lot)
    db_session.refresh(export)
    assert lot.remaining_qty == 3
    assert export.status == "matched"
    assert db_session.scalar(select(func.count(ExportAllocation.id))) == 1

    undone = undo_export_matching(db_session, export.id)

    db_session.refresh(lot)
    db_session.refresh(export)
    assert undone == 1
    assert lot.used_qty == 0
    assert lot.remaining_qty == 10
    assert lot.status == "available"
    assert export.status == "pending"
    assert db_session.scalar(select(func.count(ExportAllocation.id))) == 0

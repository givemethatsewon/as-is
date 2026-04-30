from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExportAllocation, ImportLot


def dashboard_summary(db: Session) -> dict[str, int]:
    today = date.today()
    lots = list(db.scalars(select(ImportLot)))
    total_import_qty = sum(lot.import_qty for lot in lots)
    total_matched_qty = int(db.scalar(select(func.coalesce(func.sum(ExportAllocation.matched_qty), 0))) or 0)
    total_remaining_qty = sum(lot.remaining_qty for lot in lots)
    available_qty = sum(
        lot.remaining_qty for lot in lots if lot.remaining_qty > 0 and 0 <= (today - lot.import_accepted_date).days <= 360
    )
    expired_qty = sum(lot.remaining_qty for lot in lots if lot.remaining_qty > 0 and (today - lot.import_accepted_date).days > 360)
    used_up_lots_count = sum(1 for lot in lots if lot.remaining_qty == 0 or lot.status == "used_up")
    expiring_soon_lots_count = sum(
        1 for lot in lots if lot.remaining_qty > 0 and 330 <= (today - lot.import_accepted_date).days <= 360
    )
    return {
        "total_import_qty": total_import_qty,
        "total_matched_qty": total_matched_qty,
        "total_remaining_qty": total_remaining_qty,
        "available_qty": available_qty,
        "expired_qty": expired_qty,
        "used_up_lots_count": used_up_lots_count,
        "expiring_soon_lots_count": expiring_soon_lots_count,
    }


def inventory_query(db: Session, part_number: str | None = None, origin: str | None = None, status: str | None = None):
    stmt = select(ImportLot)
    if part_number:
        stmt = stmt.where(ImportLot.part_number.contains(part_number.upper()))
    if origin:
        stmt = stmt.where(ImportLot.origin == origin.upper())
    if status:
        stmt = stmt.where(ImportLot.status == status)
    return list(
        db.scalars(
            stmt.order_by(
                ImportLot.part_number,
                ImportLot.origin,
                ImportLot.import_accepted_date,
                ImportLot.import_declaration_no,
            )
        )
    )


def inventory_summary(db: Session, part_number: str | None = None, origin: str | None = None) -> dict[str, object]:
    lots = inventory_query(db, part_number, origin)
    total_imported_qty = sum(lot.import_qty for lot in lots)
    total_exported_qty = sum(lot.used_qty for lot in lots)
    remaining_qty = sum(lot.remaining_qty for lot in lots)
    available_qty = sum(lot.remaining_qty for lot in lots if lot.status in {"available", "expiring_soon"})
    expired_qty = sum(lot.remaining_qty for lot in lots if lot.status == "expired")
    used_up_lots_count = sum(1 for lot in lots if lot.status == "used_up" or lot.remaining_qty == 0)
    expiring_soon_lots_count = sum(1 for lot in lots if lot.status == "expiring_soon")
    return {
        "part_number": part_number or "",
        "origin": origin or "",
        "total_imported_qty": total_imported_qty,
        "total_exported_qty": total_exported_qty,
        "remaining_qty": remaining_qty,
        "available_qty": available_qty,
        "expired_qty": expired_qty,
        "used_up_lots_count": used_up_lots_count,
        "expiring_soon_lots_count": expiring_soon_lots_count,
        "lots": lots,
    }


from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExportAllocation, ExportRequirement, ImportLot


STATUS_LABELS = {
    "pending": "매칭 대기",
    "matched": "매칭 완료",
    "partial_matched": "일부 매칭",
    "insufficient_stock": "재고 부족",
}


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


def dashboard_insights(db: Session) -> dict[str, object]:
    today = date.today()
    return {
        "expiring_import_lots": expiring_import_lots(db, today),
        "matching_status_distribution": matching_status_distribution(db),
        "hs_code_warning_rows": hs_code_warning_rows(db),
    }


def expiring_import_lots(db: Session, today: date, limit: int = 10) -> list[dict[str, object]]:
    lots = db.scalars(
        select(ImportLot)
        .where(ImportLot.remaining_qty > 0)
        .order_by(ImportLot.import_accepted_date, ImportLot.part_number, ImportLot.import_declaration_no)
    )
    rows = []
    for lot in lots:
        expiry_date = lot.import_accepted_date + timedelta(days=360)
        days_left = (expiry_date - today).days
        if 0 <= days_left <= 30:
            rows.append(
                {
                    "import_declaration_no": lot.import_declaration_no,
                    "import_accepted_date": lot.import_accepted_date.isoformat(),
                    "expiry_date": expiry_date.isoformat(),
                    "days_left": days_left,
                    "part_number": lot.part_number,
                    "origin": lot.origin,
                    "remaining_qty": lot.remaining_qty,
                    "line_no": lot.line_no,
                    "row_no": lot.row_no,
                }
            )
    return sorted(rows, key=lambda row: (row["days_left"], row["import_accepted_date"], row["part_number"]))[:limit]


def matching_status_distribution(db: Session) -> list[dict[str, object]]:
    status_order = ["matched", "partial_matched", "insufficient_stock", "pending"]
    counts = dict(
        db.execute(select(ExportRequirement.status, func.count()).group_by(ExportRequirement.status)).all()
    )
    total = sum(int(value) for value in counts.values())
    rows = []
    for status in status_order:
        count = int(counts.get(status, 0))
        percent = round((count / total) * 100) if total else 0
        rows.append(
            {
                "status": status,
                "label": STATUS_LABELS.get(status, status),
                "count": count,
                "percent": percent,
            }
        )
    return rows


def hs_code_warning_rows(db: Session, limit: int = 10) -> list[dict[str, object]]:
    rows = db.execute(
        select(ExportRequirement, ExportAllocation, ImportLot)
        .join(ExportAllocation, ExportAllocation.export_requirement_id == ExportRequirement.id)
        .join(ImportLot, ExportAllocation.import_lot_id == ImportLot.id)
        .where(ExportAllocation.hs_code_warning.is_not(None))
        .order_by(ExportRequirement.export_date.desc(), ExportRequirement.part_number, ImportLot.import_accepted_date)
        .limit(limit)
    ).all()
    return [
        {
            "export_date": export.export_date.isoformat(),
            "part_number": export.part_number,
            "origin": export.origin,
            "export_hs_code": export.hs_code or "",
            "import_hs_code": lot.hs_code,
            "import_declaration_no": lot.import_declaration_no,
            "line_no": lot.line_no,
            "row_no": lot.row_no,
            "matched_qty": allocation.matched_qty,
        }
        for export, allocation, lot in rows
    ]


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

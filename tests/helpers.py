from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import ExportRequirement, ImportLot


def add_import_lot(
    db: Session,
    *,
    declaration: str,
    accepted: date,
    origin: str,
    part: str,
    qty: int,
    hs_code: str = "8708309000",
    line_no: str = "004",
    row_no: str = "01",
) -> ImportLot:
    lot = ImportLot(
        import_declaration_no=declaration,
        import_accepted_date=accepted,
        origin=origin,
        hs_code=hs_code,
        line_no=line_no,
        row_no=row_no,
        part_number=part,
        spec="TEST",
        import_qty=qty,
        qty_unit="PC",
        used_qty=0,
        remaining_qty=qty,
        status="available",
    )
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return lot


def add_export_requirement(
    db: Session,
    *,
    exported: date,
    origin: str,
    part: str,
    qty: int,
    hs_code: str | None = None,
) -> ExportRequirement:
    export = ExportRequirement(
        export_date=exported,
        origin=origin,
        part_number=part,
        hs_code=hs_code,
        description="TEST EXPORT",
        unit_price=1,
        required_qty=qty,
        amount=qty,
        status="pending",
    )
    db.add(export)
    db.commit()
    db.refresh(export)
    return export


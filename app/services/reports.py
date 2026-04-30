from __future__ import annotations

import csv
from io import BytesIO, StringIO
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExportAllocation, ExportRequirement, ImportLot
from app.services.summaries import dashboard_summary


def import_lot_rows(db: Session) -> list[dict[str, Any]]:
    lots = db.scalars(
        select(ImportLot).order_by(ImportLot.part_number, ImportLot.origin, ImportLot.import_accepted_date)
    )
    return [
        {
            "import_declaration_no": lot.import_declaration_no,
            "import_accepted_date": lot.import_accepted_date.isoformat(),
            "origin": lot.origin,
            "hs_code": lot.hs_code,
            "line_no": lot.line_no,
            "row_no": lot.row_no,
            "part_number": lot.part_number,
            "spec": lot.spec,
            "import_qty": lot.import_qty,
            "used_qty": lot.used_qty,
            "remaining_qty": lot.remaining_qty,
            "qty_unit": lot.qty_unit,
            "status": lot.status,
        }
        for lot in lots
    ]


def allocation_rows(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ExportRequirement, ExportAllocation, ImportLot)
        .join(ExportAllocation, ExportAllocation.export_requirement_id == ExportRequirement.id)
        .join(ImportLot, ExportAllocation.import_lot_id == ImportLot.id)
        .order_by(ExportRequirement.export_date, ExportRequirement.part_number, ImportLot.import_accepted_date)
    ).all()
    return [
        {
            "export_date": export.export_date.isoformat(),
            "part_number": export.part_number,
            "description": export.description,
            "unit_price": export.unit_price,
            "required_qty": export.required_qty,
            "amount": export.amount,
            "matched_qty": allocation.matched_qty,
            "import_declaration_no": lot.import_declaration_no,
            "import_accepted_date": lot.import_accepted_date.isoformat(),
            "origin": lot.origin,
            "hs_code": lot.hs_code,
            "line_no": lot.line_no,
            "row_no": lot.row_no,
            "remaining_qty_after": allocation.remaining_qty_after,
            "match_status": export.status,
            "hs_code_warning": allocation.hs_code_warning,
            "expected_refund_amount": allocation.expected_refund_amount,
        }
        for export, allocation, lot in rows
    ]


def dashboard_rows(db: Session) -> list[dict[str, Any]]:
    summary = dashboard_summary(db)
    return [{"metric": key, "value": value} for key, value in summary.items()]


def inventory_summary_rows(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            ImportLot.part_number,
            ImportLot.origin,
            func.coalesce(func.sum(ImportLot.import_qty), 0),
            func.coalesce(func.sum(ImportLot.used_qty), 0),
            func.coalesce(func.sum(ImportLot.remaining_qty), 0),
        )
        .group_by(ImportLot.part_number, ImportLot.origin)
        .order_by(ImportLot.part_number, ImportLot.origin)
    )
    return [
        {
            "part_number": part_number,
            "origin": origin,
            "total_imported_qty": imported,
            "total_exported_qty": exported,
            "remaining_qty": remaining,
        }
        for part_number, origin, imported, exported, remaining in rows
    ]


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    output = StringIO()
    if not rows:
        return ""
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def refund_report_xlsx(db: Session) -> bytes:
    output = BytesIO()
    sheets = {
        "import_lots_with_remaining": import_lot_rows(db),
        "export_match_allocations": allocation_rows(db),
        "dashboard_summary": dashboard_rows(db),
        "inventory_summary": inventory_summary_rows(db),
    }
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            frame = pd.DataFrame(rows)
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    output.seek(0)
    return output.read()


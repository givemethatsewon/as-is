from __future__ import annotations

import csv
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import ExportAllocation, ExportRequirement, ImportLot, UploadBatch
from app.services.summaries import dashboard_summary


STATUS_LABELS = {
    "available": "사용 가능",
    "expiring_soon": "만료 예정",
    "expired": "기한 초과",
    "used_up": "소진",
    "blocked": "사용 보류",
    "pending": "매칭 대기",
    "matched": "매칭 완료",
    "partial_matched": "일부 매칭",
    "insufficient_stock": "재고 부족",
}

def import_lot_rows(db: Session) -> list[dict[str, Any]]:
    lots = db.scalars(
        select(ImportLot)
        .outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id)
        .where((ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        .order_by(ImportLot.part_number, ImportLot.origin, ImportLot.import_accepted_date)
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
            "status": STATUS_LABELS.get(lot.status, lot.status),
        }
        for lot in lots
    ]


def allocation_rows(db: Session) -> list[dict[str, Any]]:
    import_batch = aliased(UploadBatch)
    export_batch = aliased(UploadBatch)
    allocation_records = db.execute(
        select(ExportRequirement, ExportAllocation, ImportLot)
        .join(ExportAllocation, ExportAllocation.export_requirement_id == ExportRequirement.id)
        .join(ImportLot, ExportAllocation.import_lot_id == ImportLot.id)
        .outerjoin(import_batch, ImportLot.upload_batch_id == import_batch.id)
        .outerjoin(export_batch, ExportRequirement.upload_batch_id == export_batch.id)
        .where((ImportLot.upload_batch_id.is_(None)) | (import_batch.invalidated_at.is_(None)))
        .where((ExportRequirement.upload_batch_id.is_(None)) | (export_batch.invalidated_at.is_(None)))
        .order_by(ExportRequirement.export_date, ExportRequirement.part_number, ImportLot.import_accepted_date)
    ).all()
    allocations_by_export: dict[str, list[tuple[ExportAllocation, ImportLot]]] = {}
    for export, allocation, lot in allocation_records:
        allocations_by_export.setdefault(export.id, []).append((allocation, lot))

    active_exports = db.scalars(
        select(ExportRequirement)
        .outerjoin(UploadBatch, ExportRequirement.upload_batch_id == UploadBatch.id)
        .where((ExportRequirement.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        .order_by(ExportRequirement.export_date, ExportRequirement.part_number, ExportRequirement.id)
    ).all()

    rows: list[dict[str, Any]] = []
    for export in active_exports:
        matched_qty = 0
        for allocation, lot in allocations_by_export.get(export.id, []):
            matched_qty += allocation.matched_qty
            rows.append(_allocation_report_row(export, allocation, lot))

        shortage_qty = max(export.required_qty - matched_qty, 0)
        if shortage_qty > 0 and export.status in {"partial_matched", "insufficient_stock"}:
            rows.append(_no_match_report_row(export, shortage_qty))

    return rows


def _base_export_report_row(export: ExportRequirement) -> dict[str, Any]:
    return {
        "export_date": export.export_date.isoformat(),
        "order_no": export.order_no,
        "seq_no": export.seq_no,
        "export_origin": export.origin,
        "export_hs_code": export.hs_code,
        "export_line_no": export.line_no,
        "part_number": export.part_number,
        "description": export.description,
        "export_qty_unit": export.qty_unit,
        "unit_price": export.unit_price,
        "required_qty": export.required_qty,
        "amount": export.amount,
    }


def _allocation_report_row(export: ExportRequirement, allocation: ExportAllocation, lot: ImportLot) -> dict[str, Any]:
    row = _base_export_report_row(export)
    row.update(
        {
            "matched_qty": allocation.matched_qty,
            "import_declaration_no": lot.import_declaration_no,
            "import_accepted_date": lot.import_accepted_date.isoformat(),
            "origin": lot.origin,
            "import_origin": lot.origin,
            "hs_code": lot.hs_code,
            "line_no": lot.line_no,
            "row_no": lot.row_no,
            "import_part_number": lot.part_number,
            "import_spec": lot.spec,
            "import_qty": lot.import_qty,
            "import_qty_unit": lot.qty_unit,
            "remaining_qty_before": allocation.remaining_qty_after + allocation.matched_qty,
            "remaining_qty_after": allocation.remaining_qty_after,
            "shortage_qty": 0,
            "match_status": STATUS_LABELS.get(export.status, export.status),
            "hs_code_warning": allocation.hs_code_warning,
            "expected_refund_amount": allocation.expected_refund_amount,
        }
    )
    return row


def _no_match_report_row(export: ExportRequirement, shortage_qty: int) -> dict[str, Any]:
    row = _base_export_report_row(export)
    row.update(
        {
            "matched_qty": 0,
            "import_declaration_no": "NO MATCH",
            "import_accepted_date": "",
            "origin": export.origin,
            "import_origin": "",
            "hs_code": "",
            "line_no": "",
            "row_no": "",
            "import_part_number": "",
            "import_spec": "",
            "import_qty": None,
            "import_qty_unit": "",
            "remaining_qty_before": None,
            "remaining_qty_after": "",
            "shortage_qty": shortage_qty,
            "match_status": "NO MATCH",
            "hs_code_warning": "",
            "expected_refund_amount": None,
        }
    )
    return row


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
        .outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id)
        .where((ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
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
    latest_batch = db.scalar(
        select(UploadBatch)
        .where(
            UploadBatch.upload_type == "exports",
            UploadBatch.confirmed_at.is_not(None),
            UploadBatch.invalidated_at.is_(None),
        )
        .order_by(UploadBatch.confirmed_at.desc(), UploadBatch.created_at.desc())
        .limit(1)
    )
    if latest_batch is not None:
        return matching_run_workbook(db, latest_batch.id)
    return video_style_export_result_xlsx(db)


def _append_matching_headers(result_sheet) -> None:
    source_export_headers = [
        "수출신고번호",
        "신고일자",
        "원산지",
        "세번",
        "란번호2",
        "행번호",
        "규격1",
        "규격2",
        "수량_1",
        "수량단위_1",
    ]
    source_import_headers = [
        "수입신고번호",
        "신고일자",
        "원산지",
        "세번",
        "란번호2",
        "행번호",
        "규격1",
        "규격2",
        "수량_1",
        "수량단위_1",
    ]
    deduction_headers = ["차감 전 수량", "차감 수량", "차감 후 잔량", "미배정 수량"]
    result_sheet.append(
        ["수출 문서", *(None for _ in range(9)), "차감 대상 수입 문서", *(None for _ in range(9)), "차감 결과", None, None, None]
    )
    result_sheet.append([*source_export_headers, *source_import_headers, *deduction_headers])
    result_sheet.merge_cells("A1:J1")
    result_sheet.merge_cells("K1:T1")
    result_sheet.merge_cells("U1:X1")


def _append_inventory_sheet(workbook: Workbook, db: Session) -> None:
    inventory_sheet = workbook.create_sheet("원상태잔량")
    inventory_sheet.append(
        [
            "수입신고번호",
            "신고일자",
            "원산지",
            "세번",
            "란번호2",
            "행번호",
            "규격1",
            "규격2",
            "수량_1",
            "수량단위_1",
            "차감 수량",
            "차감 후 잔량",
        ]
    )
    lots = list(
        db.scalars(
            select(ImportLot)
            .outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id)
            .where((ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
            .order_by(
                ImportLot.import_accepted_date,
                ImportLot.import_declaration_no,
                ImportLot.line_no,
                ImportLot.row_no,
            )
        )
    )
    for lot in lots:
        inventory_sheet.append(
            [
                lot.import_declaration_no,
                lot.import_accepted_date.strftime("%Y%m%d"),
                lot.origin,
                lot.hs_code,
                lot.line_no,
                lot.row_no,
                lot.part_number,
                lot.spec,
                lot.import_qty,
                lot.qty_unit,
                lot.used_qty,
                lot.remaining_qty,
            ]
        )
    _style_report_sheet(inventory_sheet)


def video_style_export_result_xlsx(db: Session) -> bytes:
    workbook = Workbook()
    result_sheet = workbook.active
    result_sheet.title = "수출 결과"
    _append_matching_headers(result_sheet)
    for row in allocation_rows(db):
        result_sheet.append(
            [
                row.get("order_no"),
                str(row.get("export_date") or "").replace("-", ""),
                row.get("export_origin"),
                row.get("export_hs_code"),
                row.get("export_line_no"),
                row.get("seq_no"),
                row.get("part_number"),
                row.get("description"),
                row.get("required_qty"),
                row.get("export_qty_unit"),
                row.get("import_declaration_no"),
                str(row.get("import_accepted_date") or "").replace("-", ""),
                row.get("import_origin"),
                row.get("hs_code"),
                row.get("line_no"),
                row.get("row_no"),
                row.get("import_part_number"),
                row.get("import_spec"),
                row.get("import_qty"),
                row.get("import_qty_unit"),
                row.get("remaining_qty_before"),
                row.get("matched_qty"),
                row.get("remaining_qty_after"),
                row.get("shortage_qty"),
            ]
        )
    _append_inventory_sheet(workbook, db)
    _style_matching_result_sheet(result_sheet)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def matching_run_workbook(db: Session, batch_id: str) -> bytes:
    batch = db.get(UploadBatch, batch_id)
    if batch is None or batch.upload_type != "exports":
        raise ValueError("수출 매칭 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is None:
        raise ValueError("확정한 수출 매칭 파일만 다운로드할 수 있습니다.")

    workbook = Workbook()
    result_sheet = workbook.active
    result_sheet.title = "수출 결과"
    _append_matching_headers(result_sheet)

    requirements = list(
        db.scalars(
            select(ExportRequirement)
            .where(ExportRequirement.upload_batch_id == batch.id)
            .order_by(ExportRequirement.created_at, ExportRequirement.id)
        )
    )
    for export in requirements:
        allocations = sorted(
            export.allocations,
            key=lambda allocation: (
                allocation.import_lot.import_accepted_date,
                allocation.import_lot.import_declaration_no,
                allocation.import_lot.line_no,
                allocation.import_lot.row_no,
            ),
        )
        for allocation in allocations:
            lot = allocation.import_lot
            result_sheet.append(
                _matching_result_values(
                    export,
                    declaration=lot.import_declaration_no,
                    accepted_date=lot.import_accepted_date.strftime("%Y%m%d"),
                    import_origin=lot.origin,
                    hs_code=lot.hs_code,
                    line_no=lot.line_no,
                    row_no=lot.row_no,
                    import_spec=lot.spec,
                    import_qty=lot.import_qty,
                    import_qty_unit=lot.qty_unit,
                    matched_qty=allocation.matched_qty,
                    remaining_qty_after=allocation.remaining_qty_after,
                    shortage_qty=0,
                )
            )

        matched_qty = sum(allocation.matched_qty for allocation in allocations)
        shortage_qty = max(export.required_qty - matched_qty, 0)
        if shortage_qty:
            result_sheet.append(
                _matching_result_values(
                    export,
                    declaration="NO MATCH",
                    accepted_date=None,
                    import_origin=None,
                    hs_code=None,
                    line_no=None,
                    row_no=None,
                    import_spec=None,
                    import_qty=None,
                    import_qty_unit=None,
                    matched_qty=0,
                    remaining_qty_after=None,
                    shortage_qty=shortage_qty,
                )
            )

    _append_inventory_sheet(workbook, db)
    _style_matching_result_sheet(result_sheet)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _matching_result_values(
    export: ExportRequirement,
    *,
    declaration: str,
    accepted_date: str | None,
    import_origin: str | None,
    hs_code: str | None,
    line_no: str | None,
    row_no: str | None,
    import_spec: str | None,
    import_qty: int | None,
    import_qty_unit: str | None,
    matched_qty: int,
    remaining_qty_after: int | None,
    shortage_qty: int,
) -> list[Any]:
    return [
        export.order_no,
        export.export_date.strftime("%Y%m%d"),
        export.origin,
        export.hs_code,
        export.line_no,
        export.seq_no,
        export.part_number,
        export.description,
        export.required_qty,
        export.qty_unit,
        declaration,
        accepted_date,
        import_origin,
        hs_code,
        line_no,
        row_no,
        export.part_number if declaration != "NO MATCH" else None,
        import_spec,
        import_qty,
        import_qty_unit,
        remaining_qty_after + matched_qty if remaining_qty_after is not None else None,
        matched_qty,
        remaining_qty_after,
        shortage_qty,
    ]


def contest_example_report_xlsx(db: Session) -> bytes:
    return refund_report_xlsx(db)


def _style_report_sheet(worksheet) -> None:
    header_fill = PatternFill("solid", fgColor="0F5F50")
    header_font = Font(bold=True, color="FFFFFF")
    header_alignment = Alignment(horizontal="center", vertical="center")
    body_alignment = Alignment(vertical="top")

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.sheet_view.showGridLines = False

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = body_alignment
            if isinstance(cell.value, (int, float, Decimal)):
                cell.number_format = "#,##0"

    for column_cells in worksheet.columns:
        column_letter = get_column_letter(column_cells[0].column)
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        worksheet.column_dimensions[column_letter].width = min(max(max_length + 4, 12), 38)

    worksheet.row_dimensions[1].height = 24


def _style_matching_result_sheet(worksheet) -> None:
    group_fills = {
        "A1:J1": "173F5F",
        "K1:T1": "0F5F50",
        "U1:X1": "7A4A0B",
    }
    header_font = Font(bold=True, color="FFFFFF")
    centered = Alignment(horizontal="center", vertical="center")
    for cell_range, color in group_fills.items():
        fill = PatternFill("solid", fgColor=color)
        for row in worksheet[cell_range]:
            for cell in row:
                cell.fill = fill
                cell.font = header_font
                cell.alignment = centered

    second_header_fill = PatternFill("solid", fgColor="264653")
    for cell in worksheet[2]:
        cell.fill = second_header_fill
        cell.font = header_font
        cell.alignment = centered

    for row in worksheet.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = Alignment(vertical="top")
            if isinstance(cell.value, (int, float, Decimal)):
                cell.number_format = "#,##0"

    for column_cells in worksheet.columns:
        column_letter = get_column_letter(column_cells[0].column)
        max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        worksheet.column_dimensions[column_letter].width = min(max(max_length + 4, 12), 38)

    worksheet.freeze_panes = "A3"
    worksheet.sheet_view.showGridLines = False
    worksheet.row_dimensions[1].height = 24
    worksheet.row_dimensions[2].height = 24

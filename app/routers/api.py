from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExportRequirement, UploadBatch
from app.schemas import MatchingRunResponse, UploadConfirmResponse, UploadPreviewResponse
from app.services.matching import run_matching
from app.services.parsing import ParseError, read_upload_rows
from app.services.reports import allocation_rows, refund_report_xlsx, rows_to_csv
from app.services.summaries import inventory_summary
from app.services.uploads import confirm_batch, preview_exports, preview_imports

router = APIRouter(prefix="/api")


@router.post("/imports/preview", response_model=UploadPreviewResponse)
async def api_preview_imports(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        rows = await read_upload_rows(file)
        result = preview_imports(db, rows, file.filename or "upload")
    except (ParseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _preview_response(result.batch, result.warnings, result.column_mapping)


@router.post("/imports/confirm", response_model=UploadConfirmResponse)
def api_confirm_imports(batch_id: str = Form(...), db: Session = Depends(get_db)):
    return _confirm(batch_id, "imports", db)


@router.post("/exports/preview", response_model=UploadPreviewResponse)
async def api_preview_exports(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        rows = await read_upload_rows(file)
        result = preview_exports(db, rows, file.filename or "upload")
    except (ParseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _preview_response(result.batch, result.warnings, result.column_mapping)


@router.post("/exports/confirm", response_model=UploadConfirmResponse)
def api_confirm_exports(batch_id: str = Form(...), db: Session = Depends(get_db)):
    return _confirm(batch_id, "exports", db)


@router.post("/matching/run", response_model=MatchingRunResponse)
def api_run_matching(export_date: date | None = None, db: Session = Depends(get_db)):
    summary = run_matching(db, export_date)
    return summary.__dict__


@router.get("/inventory")
def api_inventory(part_number: str | None = None, origin: str | None = None, db: Session = Depends(get_db)):
    summary = inventory_summary(db, part_number, origin)
    lots = [
        {
            "id": lot.id,
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
            "status": lot.status,
        }
        for lot in summary.pop("lots")
    ]
    summary["lots"] = lots
    return jsonable_encoder(summary)


@router.get("/reports/export-allocations")
def api_report_allocations(db: Session = Depends(get_db)):
    return jsonable_encoder(allocation_rows(db))


@router.get("/reports/export-allocations.csv")
def api_report_allocations_csv(db: Session = Depends(get_db)):
    return Response(
        content=rows_to_csv(allocation_rows(db)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="export_match_allocations.csv"'},
    )


@router.get("/reports/download.xlsx")
def api_report_xlsx(db: Session = Depends(get_db)):
    return Response(
        content=refund_report_xlsx(db),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="refund_report.xlsx"'},
    )


def _preview_response(batch: UploadBatch, warnings: list[str], column_mapping: dict[str, str]) -> dict[str, object]:
    return {
        "batch_id": batch.id,
        "uploaded_count": batch.total_rows,
        "error_count": batch.error_count,
        "warnings": warnings,
        "column_mapping": column_mapping,
        "new_count": batch.new_count,
        "duplicate_count": batch.duplicate_count,
        "conflict_count": batch.conflict_count,
    }


def _confirm(batch_id: str, expected_type: str, db: Session) -> dict[str, object]:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Upload batch not found.")
    if batch.upload_type != expected_type:
        raise HTTPException(status_code=400, detail=f"Batch is for {batch.upload_type}, not {expected_type}.")
    try:
        return confirm_batch(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

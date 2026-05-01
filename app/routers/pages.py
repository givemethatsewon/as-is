from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExportRequirement, UploadBatch
from app.services.matching import run_matching
from app.services.parsing import ParseError, read_upload_rows
from app.services.reports import allocation_rows
from app.services.summaries import dashboard_summary, inventory_summary
from app.services.uploads import CANONICAL_FIELD_DESCRIPTIONS, confirm_batch, preview_exports, preview_imports
from app.templating import templates

router = APIRouter()


@router.get("/")
def home():
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"summary": dashboard_summary(db), "active": "dashboard"},
    )


@router.get("/upload")
def upload_page(request: Request, message: str | None = None, db: Session = Depends(get_db)):
    batches = db.scalars(select(UploadBatch).order_by(UploadBatch.created_at.desc()).limit(8)).all()
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"active": "upload", "batches": batches, "message": message},
    )


@router.post("/upload/imports/preview")
async def import_preview_page(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        rows = await read_upload_rows(file)
        result = preview_imports(db, rows, file.filename or "upload")
    except (ParseError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"active": "upload", "error": str(exc), "batches": []},
            status_code=400,
        )
    return _preview_template(request, result.batch, result.column_mapping)


@router.post("/upload/exports/preview")
async def export_preview_page(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        rows = await read_upload_rows(file)
        result = preview_exports(db, rows, file.filename or "upload")
    except (ParseError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"active": "upload", "error": str(exc), "batches": []},
            status_code=400,
        )
    return _preview_template(request, result.batch, result.column_mapping)


@router.post("/upload/confirm")
def confirm_upload_page(batch_id: str = Form(...), db: Session = Depends(get_db)):
    try:
        result = confirm_batch(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = f"Inserted {result['inserted_count']} rows. Skipped {result['skipped_count']} rows."
    return RedirectResponse(url=f"/upload?message={message}", status_code=303)


@router.get("/inventory")
def inventory_page(
    request: Request,
    part_number: str | None = None,
    origin: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    summary = inventory_summary(db, part_number, origin)
    lots = summary["lots"]
    if status:
        lots = [lot for lot in lots if lot.status == status]
    summary["lots"] = lots
    return templates.TemplateResponse(
        request,
        "inventory.html",
        {
            "active": "inventory",
            "summary": summary,
            "part_number": part_number or "",
            "origin": origin or "",
            "status": status or "",
        },
    )


@router.get("/exports")
def exports_page(request: Request, db: Session = Depends(get_db)):
    exports = db.scalars(select(ExportRequirement).order_by(ExportRequirement.export_date.desc())).all()
    return templates.TemplateResponse(
        request,
        "exports.html",
        {"active": "exports", "exports": exports, "message": None},
    )


@router.post("/exports/matching/run")
def run_matching_page(
    request: Request,
    export_date: date | None = Form(None),
    db: Session = Depends(get_db),
):
    summary = run_matching(db, export_date)
    exports = db.scalars(select(ExportRequirement).order_by(ExportRequirement.export_date.desc())).all()
    message = (
        f"Matched {summary.matched_count}, partial {summary.partial_matched_count}, "
        f"insufficient {summary.insufficient_stock_count}, allocations {summary.allocation_count}."
    )
    return templates.TemplateResponse(
        request,
        "exports.html",
        {"active": "exports", "exports": exports, "message": message},
    )


@router.get("/reports")
def reports_page(request: Request, db: Session = Depends(get_db)):
    rows = allocation_rows(db)
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"active": "reports", "allocations": rows},
    )


def _preview_template(request: Request, batch: UploadBatch, column_mapping: dict[str, str]):
    return templates.TemplateResponse(
        request,
        "upload_preview.html",
        {
            "active": "upload",
            "batch": batch,
            "rows": batch.rows,
            "column_mapping": column_mapping,
            "field_descriptions": CANONICAL_FIELD_DESCRIPTIONS,
        },
    )

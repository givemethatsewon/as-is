from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExportRequirement, UploadBatch
from app.services.matching import run_matching, undo_export_matching
from app.services.parsing import ParseError, read_upload_rows
from app.services.summaries import dashboard_insights, dashboard_summary, inventory_summary
from app.services.uploads import (
    confirm_batch,
    delete_unconfirmed_upload,
    invalidate_confirmed_upload,
    preview_exports,
    preview_imports,
)
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
        {"summary": dashboard_summary(db), "insights": dashboard_insights(db), "active": "dashboard"},
    )


@router.get("/upload")
def upload_page(request: Request, message: str | None = None):
    return templates.TemplateResponse(request, "upload.html", {"active": "upload", "message": message})


@router.post("/upload/imports/preview")
async def import_preview_page(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        rows = await read_upload_rows(file, upload_type="imports")
        result = preview_imports(db, rows, file.filename or "upload")
    except (ParseError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"active": "upload", "error": str(exc)},
            status_code=400,
        )
    return _preview_template(request, result.batch)


@router.post("/upload/exports/preview")
async def export_preview_page(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        rows = await read_upload_rows(file, upload_type="exports")
        result = preview_exports(db, rows, file.filename or "upload")
    except (ParseError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"active": "upload", "error": str(exc)},
            status_code=400,
        )
    return _preview_template(request, result.batch)


@router.get("/upload/reviews/{batch_id}")
def upload_review_detail_page(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="검토한 파일을 찾을 수 없습니다.")
    return _preview_template(request, batch)


@router.post("/upload/confirm")
def confirm_upload_page(batch_id: str = Form(...), db: Session = Depends(get_db)):
    try:
        result = confirm_batch(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = (
        f"반영 완료 {result['inserted_count']}건, "
        f"재활성화 {result.get('reactivated_count', 0)}건, "
        f"건너뜀 {result['skipped_count']}건"
    )
    return _upload_redirect(message)


@router.post("/upload/delete")
def delete_upload_page(batch_id: str = Form(...), db: Session = Depends(get_db)):
    try:
        delete_unconfirmed_upload(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _upload_redirect("업로드를 취소했습니다.")


@router.post("/upload/invalidate")
def invalidate_upload_page(batch_id: str = Form(...), reason: str | None = Form(None), db: Session = Depends(get_db)):
    try:
        invalidate_confirmed_upload(db, batch_id, reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _upload_redirect("무효 처리했습니다.")


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
    exports = db.scalars(
        select(ExportRequirement)
        .outerjoin(UploadBatch, ExportRequirement.upload_batch_id == UploadBatch.id)
        .where((ExportRequirement.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        .order_by(ExportRequirement.export_date.desc())
    ).all()
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
    exports = db.scalars(
        select(ExportRequirement)
        .outerjoin(UploadBatch, ExportRequirement.upload_batch_id == UploadBatch.id)
        .where((ExportRequirement.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        .order_by(ExportRequirement.export_date.desc())
    ).all()
    message = (
        f"매칭 완료 {summary.matched_count}건, 일부 매칭 {summary.partial_matched_count}건, "
        f"재고 부족 {summary.insufficient_stock_count}건"
    )
    return templates.TemplateResponse(
        request,
        "exports.html",
        {"active": "exports", "exports": exports, "message": message},
    )


@router.post("/exports/matching/undo")
def undo_matching_page(
    request: Request,
    export_requirement_id: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        undone_count = undo_export_matching(db, export_requirement_id)
        message = f"매칭 되돌리기 완료: {undone_count}개 수입근거를 원복했습니다."
    except ValueError as exc:
        message = str(exc)
    exports = db.scalars(
        select(ExportRequirement)
        .outerjoin(UploadBatch, ExportRequirement.upload_batch_id == UploadBatch.id)
        .where((ExportRequirement.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        .order_by(ExportRequirement.export_date.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "exports.html",
        {"active": "exports", "exports": exports, "message": message},
    )


@router.get("/reports")
def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html", {"active": "reports"})


def _preview_template(request: Request, batch: UploadBatch):
    reactivate_count = sum(1 for row in batch.rows if row.row_status == "reactivate")
    return templates.TemplateResponse(
        request,
        "upload_preview.html",
        {
            "active": "upload",
            "batch": batch,
            "rows": batch.rows,
            "reactivate_count": reactivate_count,
        },
    )


def _upload_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/upload?{urlencode({'message': message})}", status_code=303)

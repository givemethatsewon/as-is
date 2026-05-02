from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExportRequirement, UploadBatch
from app.services.matching import MATCHING_RULES_KO, run_matching
from app.services.parsing import ParseError, read_upload_rows
from app.services.reports import allocation_rows, import_lot_rows
from app.services.summaries import dashboard_insights, dashboard_summary, inventory_summary
from app.services.uploads import (
    CANONICAL_FIELD_DESCRIPTIONS,
    column_mapping_for_batch,
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


@router.get("/upload/reviews/{batch_id}")
def upload_review_detail_page(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="검토한 파일을 찾을 수 없습니다.")
    return _preview_template(request, batch, column_mapping_for_batch(batch))


@router.post("/upload/confirm")
def confirm_upload_page(batch_id: str = Form(...), db: Session = Depends(get_db)):
    try:
        result = confirm_batch(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = f"신규 행 {result['inserted_count']}개를 저장했고, {result['skipped_count']}개는 건너뛰었습니다."
    return _upload_redirect(message)


@router.post("/upload/delete")
def delete_upload_page(batch_id: str = Form(...), db: Session = Depends(get_db)):
    try:
        delete_unconfirmed_upload(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _upload_redirect("미확정 파일 검토 기록을 삭제했습니다.")


@router.post("/upload/invalidate")
def invalidate_upload_page(batch_id: str = Form(...), reason: str | None = Form(None), db: Session = Depends(get_db)):
    try:
        invalidate_confirmed_upload(db, batch_id, reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _upload_redirect("저장된 파일을 무효 처리했습니다. 이 업로드에서 저장된 자료는 이후 집계와 매칭에서 제외됩니다.")


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
        {"active": "exports", "exports": exports, "message": None, "matching_rules": MATCHING_RULES_KO},
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
        f"재고 부족 {summary.insufficient_stock_count}건입니다. 수입 재고 연결은 {summary.allocation_count}건 생성됐습니다."
    )
    return templates.TemplateResponse(
        request,
        "exports.html",
        {"active": "exports", "exports": exports, "message": message, "matching_rules": MATCHING_RULES_KO},
    )


@router.get("/reports")
def reports_page(request: Request, db: Session = Depends(get_db)):
    allocation_preview = allocation_rows(db)
    import_lot_preview = import_lot_rows(db)
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"active": "reports", "allocations": allocation_preview, "import_lots": import_lot_preview},
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


def _upload_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/upload?{urlencode({'message': message})}", status_code=303)

from __future__ import annotations

import json
import secrets
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    auth_config,
    clear_login_failures,
    client_key,
    csrf_token,
    login_is_throttled,
    record_login_failure,
    verify_password,
)
from app.db import get_db
from app.models import ExportRequirement, ImportLot, UploadBatch, UploadPreviewRow
from app.services.matching import run_matching, undo_export_matching
from app.services.parsing import ParseError, read_upload_rows
from app.services.summaries import dashboard_insights, dashboard_summary, inventory_summary
from app.services.uploads import (
    confirm_match_run,
    confirm_batch,
    delete_unconfirmed_upload,
    invalidate_confirmed_upload,
    preview_exports,
    preview_imports,
    revert_match_run,
)
from app.services.settings import get_eligibility_days, set_eligibility_days
from app.templating import templates

router = APIRouter()


@router.get("/login")
def login_page(request: Request, next: str = "/"):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"csrf_token": csrf_token(request), "next": next, "error": None},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token_value: str = Form(..., alias="csrf_token"),
    next: str = Form("/"),
):
    token = csrf_token(request)
    if not secrets.compare_digest(csrf_token_value, token):
        raise HTTPException(status_code=403, detail="CSRF token validation failed.")
    key = client_key(request)
    if login_is_throttled(key):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"csrf_token": token, "next": next, "error": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요."},
            status_code=429,
        )
    config = auth_config()
    if not config.configured:
        raise HTTPException(status_code=503, detail="공용 계정이 아직 설정되지 않았습니다.")
    if username != config.username or not verify_password(password, config.password_hash):
        record_login_failure(key)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"csrf_token": token, "next": next, "error": "아이디 또는 비밀번호가 올바르지 않습니다."},
            status_code=401,
        )
    clear_login_failures(key)
    request.session.clear()
    request.session.update({"authenticated": True, "username": config.username, "csrf_token": token})
    destination = next if next.startswith("/") and not next.startswith("//") else "/"
    return RedirectResponse(url=destination, status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"active": "settings", "eligibility_days": get_eligibility_days(db), "message": None},
    )


@router.post("/settings")
def update_settings_page(request: Request, eligibility_days: int = Form(...), db: Session = Depends(get_db)):
    try:
        set_eligibility_days(db, eligibility_days)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"active": "settings", "eligibility_days": eligibility_days, "error": str(exc)},
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"active": "settings", "eligibility_days": eligibility_days, "message": "설정을 저장했습니다."},
    )


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    recent_batches = list(db.scalars(select(UploadBatch).order_by(UploadBatch.created_at.desc()).limit(8)))
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "workbench",
            "summary": dashboard_summary(db),
            "recent_batches": recent_batches,
        },
    )


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url="/", status_code=303)


@router.get("/batches/{batch_id}")
def batch_review_page(
    request: Request,
    batch_id: str,
    page: int = 1,
    message: str | None = None,
    db: Session = Depends(get_db),
):
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="업로드 파일을 찾을 수 없습니다.")
    page = max(1, page)
    page_size = 50
    rows = list(
        db.scalars(
            select(UploadPreviewRow)
            .where(UploadPreviewRow.batch_id == batch.id)
            .order_by(UploadPreviewRow.row_number)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    review_rows = []
    for row in rows:
        plans = []
        for plan in sorted(row.planned_allocations, key=lambda item: item.sequence):
            plans.append({"plan": plan, "lot": db.get(ImportLot, plan.import_lot_id) if plan.import_lot_id else None})
        review_rows.append({"row": row, "payload": json.loads(row.payload_json), "plans": plans})
    total_pages = max(1, (batch.total_rows + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request,
        "batch_review.html",
        {
            "active": "workbench",
            "batch": batch,
            "review_rows": review_rows,
            "page": page,
            "total_pages": total_pages,
            "message": message,
        },
    )


@router.post("/batches/{batch_id}/confirm")
def confirm_batch_page(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="업로드 파일을 찾을 수 없습니다.")
    try:
        result = confirm_batch(db, batch_id) if batch.upload_type == "imports" else confirm_match_run(db, batch_id)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/batches/{batch_id}?{urlencode({'message': str(exc)})}",
            status_code=303,
        )
    message = "수입 재고를 반영했습니다." if batch.upload_type == "imports" else "수출 매칭을 확정하고 재고를 차감했습니다."
    return RedirectResponse(url=f"/batches/{batch_id}?{urlencode({'message': message})}", status_code=303)


@router.post("/batches/{batch_id}/revert")
def revert_batch_page(batch_id: str, db: Session = Depends(get_db)):
    try:
        result = revert_match_run(db, batch_id)
        message = f"파일 전체를 되돌려 재고 {result['restored_qty']}개를 복구했습니다."
    except ValueError as exc:
        message = str(exc)
    return RedirectResponse(url=f"/history?{urlencode({'message': message})}", status_code=303)


@router.get("/history")
def history_page(request: Request, page: int = 1, message: str | None = None, db: Session = Depends(get_db)):
    page = max(1, page)
    page_size = 50
    all_batches = list(db.scalars(select(UploadBatch).order_by(UploadBatch.created_at.desc())))
    total_pages = max(1, (len(all_batches) + page_size - 1) // page_size)
    batches = all_batches[(page - 1) * page_size : page * page_size]
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "active": "history",
            "batches": batches,
            "page": page,
            "total_pages": total_pages,
            "message": message,
        },
    )


@router.get("/upload")
def upload_page(request: Request, message: str | None = None):
    return templates.TemplateResponse(request, "upload.html", {"active": "upload", "message": message})


@router.post("/upload/match")
async def upload_and_match_page(
    request: Request,
    import_file: UploadFile = File(...),
    export_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    batches: list[UploadBatch] = []
    try:
        import_rows = await read_upload_rows(import_file, upload_type="imports")
        export_rows = await read_upload_rows(export_file, upload_type="exports")

        import_result = preview_imports(db, import_rows, import_file.filename or "수입 파일")
        batches.append(import_result.batch)
        _raise_for_preview_errors("수입 파일", import_result.batch)

        export_result = preview_exports(
            db,
            export_rows,
            export_file.filename or "수출 파일",
            additional_origins=_preview_origins(import_result.batch),
        )
        batches.append(export_result.batch)
        _raise_for_preview_errors("수출 파일", export_result.batch)

        import_confirmed = confirm_batch(db, import_result.batch.id)
        export_confirmed = confirm_batch(db, export_result.batch.id)
        summary = run_matching(db)
    except (ParseError, ValueError) as exc:
        _discard_direct_upload_batches(db, batches)
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"active": "upload", "error": str(exc)},
            status_code=400,
        )

    exports = db.scalars(
        select(ExportRequirement)
        .outerjoin(UploadBatch, ExportRequirement.upload_batch_id == UploadBatch.id)
        .where((ExportRequirement.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        .order_by(ExportRequirement.export_date.desc())
    ).all()
    message = (
        f"업로드 및 매칭 완료: 수입 {import_confirmed['inserted_count']}건, "
        f"수출 {export_confirmed['inserted_count']}건, 매칭 {summary.matched_count}건, "
        f"일부 매칭 {summary.partial_matched_count}건, 재고 부족 {summary.insufficient_stock_count}건"
    )
    return templates.TemplateResponse(
        request,
        "exports.html",
        {"active": "exports", "exports": exports, "message": message},
    )


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


def _preview_origins(batch: UploadBatch) -> dict[str, set[str]]:
    origins: dict[str, set[str]] = {}
    for row in batch.rows:
        if row.row_status not in {"new", "reactivate"}:
            continue
        payload = json.loads(row.payload_json)
        part_number = payload.get("part_number")
        origin = payload.get("origin")
        if part_number and origin:
            origins.setdefault(part_number, set()).add(origin)
    return origins


def _raise_for_preview_errors(label: str, batch: UploadBatch) -> None:
    if batch.error_count == 0:
        return
    messages = list(dict.fromkeys(row.message for row in batch.rows if row.row_status == "error"))
    detail = "; ".join(messages[:3])
    raise ValueError(f"{label}에 오류 {batch.error_count}건이 있습니다. {detail}")


def _discard_direct_upload_batches(db: Session, batches: list[UploadBatch]) -> None:
    for batch in reversed(batches):
        db.refresh(batch)
        if batch.confirmed_at is None:
            delete_unconfirmed_upload(db, batch.id)
        elif batch.invalidated_at is None:
            invalidate_confirmed_upload(db, batch.id, "바로 매칭 실행 중 오류로 자동 취소")

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExportRequirement, ProcessingJob, UploadBatch, UploadPreviewRow
from app.schemas import MatchingRunResponse, UploadConfirmResponse, UploadPreviewResponse
from app.services.matching import run_matching, undo_export_matching
from app.services.parsing import ParseError, read_upload_rows
from app.services.file_storage import UploadTooLargeError, store_upload
from app.services.jobs import enqueue_upload_job, submit_upload_preview_job
from app.services.reports import (
    allocation_rows,
    contest_example_report_xlsx,
    matching_run_workbook,
    refund_report_xlsx,
    rows_to_csv,
)
from app.services.summaries import inventory_summary
from app.services.uploads import (
    confirm_batch,
    confirm_match_run,
    preview_exports,
    preview_imports,
    revert_match_run,
)

router = APIRouter(prefix="/api")


@router.post("/upload-batches/{upload_type}", status_code=status.HTTP_202_ACCEPTED)
async def api_create_upload_batch(
    upload_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if upload_type not in {"imports", "exports"}:
        raise HTTPException(status_code=404, detail="지원하지 않는 업로드 종류입니다.")
    try:
        stored = store_upload(file.file, file.filename or "upload")
    except (ValueError, UploadTooLargeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    batch = UploadBatch(
        upload_type=upload_type,
        filename=file.filename or stored.safe_filename,
        source_path=str(stored.path),
        source_sha256=stored.sha256,
        source_size_bytes=stored.size_bytes,
        status="queued",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    job = enqueue_upload_job(db, batch.id)
    submit_upload_preview_job(job.id)
    return {"batch_id": batch.id, "job_id": job.id, "status": job.status}


@router.get("/upload-batches/{batch_id}")
def api_upload_batch_status(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="업로드 파일을 찾을 수 없습니다.")
    job = db.scalar(
        select(ProcessingJob).where(ProcessingJob.batch_id == batch.id).order_by(ProcessingJob.created_at.desc())
    )
    return {
        "batch_id": batch.id,
        "upload_type": batch.upload_type,
        "filename": batch.filename,
        "status": batch.status,
        "processed_rows": batch.processed_rows,
        "total_rows": batch.total_rows,
        "new_count": batch.new_count,
        "duplicate_count": batch.duplicate_count,
        "conflict_count": batch.conflict_count,
        "error_count": batch.error_count,
        "error_message": batch.error_message,
        "job_id": job.id if job else None,
    }


@router.get("/upload-batches/{batch_id}/rows")
def api_upload_batch_rows(
    batch_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="업로드 파일을 찾을 수 없습니다.")
    rows = list(
        db.scalars(
            select(UploadPreviewRow)
            .where(UploadPreviewRow.batch_id == batch.id)
            .order_by(UploadPreviewRow.row_number)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return {
        "page": page,
        "page_size": page_size,
        "total_rows": batch.total_rows,
        "rows": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "status": row.row_status,
                "message": row.message,
                "payload": json.loads(row.payload_json),
                "allocations": [
                    {
                        "sequence": plan.sequence,
                        "import_lot_id": plan.import_lot_id,
                        "matched_qty": plan.matched_qty,
                        "remaining_qty_after": plan.remaining_qty_after,
                        "shortage_qty": plan.shortage_qty,
                        "hs_code": plan.hs_code,
                        "spec": plan.spec,
                    }
                    for plan in sorted(row.planned_allocations, key=lambda plan: plan.sequence)
                ],
            }
            for row in rows
        ],
    }


@router.get("/upload-batches/{batch_id}/original")
def api_download_original_upload(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(UploadBatch, batch_id)
    if batch is None or not batch.source_path:
        raise HTTPException(status_code=404, detail="원본 파일을 찾을 수 없습니다.")
    source = Path(batch.source_path)
    if not source.is_file():
        raise HTTPException(status_code=404, detail="보관된 원본 파일이 없습니다.")
    return FileResponse(source, filename=batch.filename, media_type="application/octet-stream")


@router.post("/import-batches/{batch_id}/confirm")
def api_confirm_import_batch(batch_id: str, db: Session = Depends(get_db)):
    return _confirm(batch_id, "imports", db)


@router.post("/match-runs/{batch_id}/confirm")
def api_confirm_match_run(batch_id: str, db: Session = Depends(get_db)):
    try:
        return confirm_match_run(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/match-runs/{batch_id}/revert")
def api_revert_match_run(batch_id: str, db: Session = Depends(get_db)):
    try:
        return revert_match_run(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/match-runs/{batch_id}/result.xlsx")
def api_download_match_run_result(batch_id: str, db: Session = Depends(get_db)):
    try:
        content = matching_run_workbook(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="matching-result-{batch_id}.xlsx"'},
    )


@router.post("/imports/preview", response_model=UploadPreviewResponse)
async def api_preview_imports(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        rows = await read_upload_rows(file, upload_type="imports")
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
        rows = await read_upload_rows(file, upload_type="exports")
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


@router.post("/exports/{export_requirement_id}/matching/undo")
def api_undo_export_matching(export_requirement_id: str, db: Session = Depends(get_db)):
    try:
        undone_count = undo_export_matching(db, export_requirement_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"export_requirement_id": export_requirement_id, "undone_allocation_count": undone_count}


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
        headers={"Content-Disposition": 'attachment; filename="video_style_export_result.xlsx"'},
    )


@router.get("/reports/contest-example.xlsx")
def api_report_contest_example_xlsx(db: Session = Depends(get_db)):
    return Response(
        content=contest_example_report_xlsx(db),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="contest_example_report.xlsx"'},
    )


def _preview_response(batch: UploadBatch, warnings: list[str], column_mapping: dict[str, str]) -> dict[str, object]:
    reactivate_count = sum(1 for row in batch.rows if row.row_status == "reactivate")
    return {
        "batch_id": batch.id,
        "uploaded_count": batch.total_rows,
        "error_count": batch.error_count,
        "warnings": warnings,
        "column_mapping": column_mapping,
        "new_count": batch.new_count,
        "reactivate_count": reactivate_count,
        "duplicate_count": batch.duplicate_count,
        "conflict_count": batch.conflict_count,
    }


def _confirm(batch_id: str, expected_type: str, db: Session) -> dict[str, object]:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="검토한 파일을 찾을 수 없습니다.")
    if batch.upload_type != expected_type:
        raise HTTPException(status_code=400, detail=f"이 파일은 {expected_type}용이 아닙니다.")
    try:
        return confirm_batch(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

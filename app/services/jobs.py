from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal
from app.models import ProcessingJob, UploadBatch, now_utc
from app.services.parsing import iter_file_rows


RowHandler = Callable[[Session, UploadBatch, int, dict[str, Any]], None]
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="upload-worker")


def enqueue_upload_job(db: Session, batch_id: str) -> ProcessingJob:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise ValueError("Upload batch was not found.")
    job = ProcessingJob(batch_id=batch.id, status="queued", total_rows=batch.total_rows)
    batch.status = "queued"
    batch.error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def submit_job(job_id: str, row_handler: RowHandler | None = None) -> Future[None]:
    return _executor.submit(process_job, job_id, session_factory=SessionLocal, row_handler=row_handler)


def submit_upload_preview_job(job_id: str) -> Future[None]:
    return _executor.submit(process_upload_preview_job, job_id, session_factory=SessionLocal)


def process_upload_preview_job(
    job_id: str,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
) -> None:
    from app.services.uploads import preview_export_run, preview_imports

    with session_factory() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError("Processing job was not found.")
        batch = db.get(UploadBatch, job.batch_id)
        if batch is None or not batch.source_path:
            raise ValueError("Stored upload was not found.")
        job.status = "processing"
        job.started_at = now_utc()
        batch.status = "processing"
        db.commit()

        try:
            rows = []
            for processed, row in enumerate(iter_file_rows(batch.source_path, batch.upload_type), start=1):
                rows.append(row)
                if processed % 100 == 0:
                    job.processed_rows = processed
                    batch.processed_rows = processed
                    db.commit()
            if batch.upload_type == "imports":
                preview_imports(db, rows, batch.filename, batch=batch)
            elif batch.upload_type == "exports":
                preview_export_run(
                    db,
                    rows,
                    batch.filename,
                    eligibility_days=batch.eligibility_days,
                    batch=batch,
                )
            else:
                raise ValueError("Unsupported upload type.")
            db.refresh(job)
            job.processed_rows = len(rows)
            job.total_rows = len(rows)
            job.status = "review_ready"
            job.finished_at = now_utc()
            batch.status = "review_ready"
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ProcessingJob, job_id)
            batch = db.get(UploadBatch, job.batch_id) if job is not None else None
            message = str(exc)[:2000]
            if job is not None:
                job.status = "failed"
                job.error_message = message
                job.finished_at = now_utc()
            if batch is not None:
                batch.status = "failed"
                batch.error_message = message
            db.commit()
            raise


def process_job(
    job_id: str,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    row_handler: RowHandler | None = None,
) -> None:
    with session_factory() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError("Processing job was not found.")
        batch = db.get(UploadBatch, job.batch_id)
        if batch is None or not batch.source_path:
            raise ValueError("Stored upload was not found.")

        job.status = "processing"
        job.started_at = now_utc()
        batch.status = "processing"
        db.commit()

        try:
            processed = 0
            for row_number, row in enumerate(iter_file_rows(batch.source_path, batch.upload_type), start=2):
                if row_handler is not None:
                    row_handler(db, batch, row_number, row)
                processed += 1
                if processed % 100 == 0:
                    job.processed_rows = processed
                    batch.processed_rows = processed
                    db.commit()

            job.processed_rows = processed
            job.total_rows = processed
            job.status = "review_ready"
            job.finished_at = now_utc()
            batch.processed_rows = processed
            batch.total_rows = processed
            batch.status = "review_ready"
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(ProcessingJob, job_id)
            batch = db.get(UploadBatch, job.batch_id) if job is not None else None
            message = str(exc)[:2000]
            if job is not None:
                job.status = "failed"
                job.error_message = message
                job.finished_at = now_utc()
            if batch is not None:
                batch.status = "failed"
                batch.error_message = message
            db.commit()
            raise

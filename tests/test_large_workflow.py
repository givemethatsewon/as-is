from __future__ import annotations

import time
import tracemalloc

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import ProcessingJob, UploadBatch
from app.services.jobs import enqueue_upload_job, process_upload_preview_job


def test_100k_import_runs_in_background_and_http_review_is_paginated(client, tmp_path) -> None:
    row_count = 100_000
    source = tmp_path / "large-import.csv"
    with source.open("w", encoding="utf-8", newline="") as output:
        output.write(
            "import_declaration_no,import_accepted_date,origin,hs_code,line_no,row_no,part_number,spec,import_qty,qty_unit\n"
        )
        for index in range(row_count):
            output.write(f"IMP-{index},2026-01-01,CN,8501,1,{index},PN-{index},ITEM,1,PC\n")

    engine = create_engine(f"sqlite:///{tmp_path / 'large.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions() as db:
        batch = UploadBatch(
            upload_type="imports",
            filename=source.name,
            source_path=str(source),
            source_size_bytes=source.stat().st_size,
            status="queued",
        )
        db.add(batch)
        db.commit()
        job_id = enqueue_upload_job(db, batch.id).id
        batch_id = batch.id

    tracemalloc.start()
    started = time.perf_counter()
    process_upload_preview_job(job_id, session_factory=sessions)
    duration_seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    with sessions() as db:
        job = db.get(ProcessingJob, job_id)
        batch = db.get(UploadBatch, batch_id)
        assert job.status == "review_ready"
        assert job.processed_rows == row_count
        assert batch.total_rows == row_count
        assert batch.new_count == row_count

    def override_get_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    response = client.get(f"/api/upload-batches/{batch_id}/rows?page=2&page_size=50")

    assert response.status_code == 200
    assert response.json()["total_rows"] == row_count
    assert len(response.json()["rows"]) == 50
    assert len(response.content) < 100_000
    assert duration_seconds < 90
    assert peak_bytes < 250 * 1024 * 1024
    print(f"100k import: {duration_seconds:.2f}s, peak traced memory {peak_bytes / 1024 / 1024:.1f} MiB")

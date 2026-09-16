from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import ProcessingJob, UploadBatch
from app.services.file_storage import UploadTooLargeError, read_stored_upload, store_upload
from app.services.jobs import enqueue_upload_job, process_job
from app.services.parsing import iter_file_rows


def test_store_upload_uses_safe_name_hash_and_can_be_read_back(tmp_path) -> None:
    content = b"alpha,beta\n1,2\n"

    stored = store_upload(BytesIO(content), "../../unsafe export.csv", storage_root=tmp_path, max_bytes=100)

    assert stored.safe_filename == "unsafe_export.csv"
    assert stored.size_bytes == len(content)
    assert stored.sha256 == sha256(content).hexdigest()
    assert stored.path.parent.parent == tmp_path
    assert read_stored_upload(stored.path, storage_root=tmp_path) == content


def test_store_upload_rejects_oversize_and_removes_partial_file(tmp_path) -> None:
    with pytest.raises(UploadTooLargeError, match="maximum"):
        store_upload(BytesIO(b"123456"), "large.csv", storage_root=tmp_path, max_bytes=5)

    assert list(tmp_path.rglob("*.*")) == []


def test_iter_file_rows_selects_import_sheet_and_does_not_execute_formulas(tmp_path) -> None:
    workbook = Workbook()
    workbook.active.title = "안내"
    workbook.active.append(["설명용 시트"])
    stock = workbook.create_sheet("원상태진행")
    stock.append(["수입신고번호", "신고일자", "원산지", "세번", "란번호", "행번호", "판매부번", "규격", "수량", "수량단위", "잔량"])
    stock.append(["A", "20260101", "CN", "8501", "1", "1", "PN-1", "MOTOR", 10, "PC", 7])
    stock.append(["B", "20260101", "CN", "8501", "1", "2", "=1+1", "FORMULA", 10, "PC", 10])
    path = tmp_path / "stock.xlsm"
    workbook.save(path)

    rows = list(iter_file_rows(path, "imports"))

    assert rows[0]["판매부번"] == "PN-1"
    assert rows[0]["잔량"] == 7
    assert rows[1]["판매부번"] is None


def test_job_progress_and_completion_persist_across_sessions(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    source = tmp_path / "imports.csv"
    source.write_text("part,qty\nA,1\nB,2\n", encoding="utf-8")
    with sessions() as session:
        batch = UploadBatch(upload_type="imports", filename="imports.csv", source_path=str(source), status="queued")
        session.add(batch)
        session.commit()
        job = enqueue_upload_job(session, batch.id)
        job_id = job.id

    seen: list[str] = []
    process_job(job_id, session_factory=sessions, row_handler=lambda _db, _batch, _number, row: seen.append(row["part"]))

    with Session(engine) as session:
        job = session.get(ProcessingJob, job_id)
        batch = session.get(UploadBatch, job.batch_id)
        assert seen == ["A", "B"]
        assert job.status == "review_ready"
        assert job.processed_rows == 2
        assert batch.status == "review_ready"
        assert batch.processed_rows == 2


def test_job_failure_is_persisted_and_safe_to_inspect_after_restart(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fail.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    source = tmp_path / "imports.csv"
    source.write_text("part\nA\n", encoding="utf-8")
    with sessions() as session:
        batch = UploadBatch(upload_type="imports", filename="imports.csv", source_path=str(source), status="queued")
        session.add(batch)
        session.commit()
        job_id = enqueue_upload_job(session, batch.id).id

    def fail(*_args) -> None:
        raise ValueError("bad uploaded row")

    with pytest.raises(ValueError, match="bad uploaded row"):
        process_job(job_id, session_factory=sessions, row_handler=fail)

    with Session(engine) as session:
        job = session.get(ProcessingJob, job_id)
        batch = session.get(UploadBatch, job.batch_id)
        assert job.status == "failed"
        assert batch.status == "failed"
        assert job.error_message == "bad uploaded row"
        assert batch.error_message == "bad uploaded row"


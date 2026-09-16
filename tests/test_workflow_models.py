from datetime import date

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db import Base, migrate_sqlite_schema
from app.models import ImportLot, PlannedAllocation, ProcessingJob, UploadBatch, UploadPreviewRow


EXPECTED_BATCH_COLUMNS = {
    "source_path",
    "source_sha256",
    "source_size_bytes",
    "status",
    "processed_rows",
    "eligibility_days",
    "inventory_fingerprint",
    "error_message",
    "result_path",
    "reverted_at",
}


def test_fresh_schema_has_durable_workflow_tables_and_fields() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert {"processing_jobs", "planned_allocations"} <= set(inspector.get_table_names())
    assert EXPECTED_BATCH_COLUMNS <= {column["name"] for column in inspector.get_columns("upload_batches")}


def test_existing_sqlite_schema_is_migrated_idempotently() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE upload_batches (
                    id VARCHAR(36) PRIMARY KEY,
                    upload_type VARCHAR(20) NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    total_rows INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_count INTEGER NOT NULL DEFAULT 0,
                    conflict_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    confirmed_at DATETIME,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )

    migrate_sqlite_schema(engine)
    migrate_sqlite_schema(engine)
    inspector = inspect(engine)

    assert EXPECTED_BATCH_COLUMNS <= {column["name"] for column in inspector.get_columns("upload_batches")}
    assert {"processing_jobs", "planned_allocations"} <= set(inspector.get_table_names())


def test_job_and_plan_records_are_persisted() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        batch = UploadBatch(upload_type="exports", filename="exports.xlsx", eligibility_days=720)
        session.add(batch)
        session.flush()
        preview_row = UploadPreviewRow(
            batch_id=batch.id,
            row_number=2,
            row_status="new",
            payload_json="{}",
        )
        lot = ImportLot(
            import_declaration_no="A",
            import_accepted_date=date(2026, 1, 1),
            origin="CN",
            hs_code="8501",
            line_no="1",
            row_no="1",
            part_number="PN-1",
            import_qty=10,
            remaining_qty=10,
        )
        session.add_all([preview_row, lot])
        session.flush()
        job = ProcessingJob(batch_id=batch.id, status="queued", total_rows=1)
        plan = PlannedAllocation(
            batch_id=batch.id,
            preview_row_id=preview_row.id,
            import_lot_id=lot.id,
            sequence=1,
            matched_qty=4,
            remaining_qty_after=6,
            shortage_qty=0,
            hs_code=lot.hs_code,
        )
        session.add_all([job, plan])
        session.commit()

        assert session.get(ProcessingJob, job.id).status == "queued"
        assert session.get(PlannedAllocation, plan.id).matched_qty == 4


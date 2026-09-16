from collections.abc import Generator
from os import getenv

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = getenv("DATABASE_URL", "sqlite:///./as_is.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    migrate_sqlite_schema(engine)


def migrate_sqlite_schema(bind) -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=bind)
    _ensure_upload_batch_columns(bind)
    _ensure_batch_owner_columns(bind)


def _ensure_upload_batch_columns(bind) -> None:
    if bind.dialect.name != "sqlite":
        return

    inspector = inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("upload_batches")}
    columns = {
        "column_mapping_json": "TEXT",
        "invalidated_at": "DATETIME",
        "invalidated_reason": "VARCHAR(255)",
        "source_path": "VARCHAR(500)",
        "source_sha256": "VARCHAR(64)",
        "source_size_bytes": "INTEGER",
        "status": "VARCHAR(30) NOT NULL DEFAULT 'review_ready'",
        "processed_rows": "INTEGER NOT NULL DEFAULT 0",
        "eligibility_days": "INTEGER NOT NULL DEFAULT 720",
        "inventory_fingerprint": "VARCHAR(64)",
        "error_message": "TEXT",
        "result_path": "VARCHAR(500)",
        "reverted_at": "DATETIME",
    }
    missing = [(name, column_type) for name, column_type in columns.items() if name not in existing]
    if not missing:
        return

    with bind.begin() as connection:
        for name, column_type in missing:
            connection.execute(text(f"ALTER TABLE upload_batches ADD COLUMN {name} {column_type}"))


def _ensure_batch_owner_columns(bind) -> None:
    if bind.dialect.name != "sqlite":
        return

    inspector = inspect(bind)
    table_columns = {
        "import_lots": {"upload_batch_id": "VARCHAR(36)"},
        "export_requirements": {
            "upload_batch_id": "VARCHAR(36)",
            "order_no": "VARCHAR(120)",
            "seq_no": "VARCHAR(40)",
        },
    }
    with bind.begin() as connection:
        for table_name, columns in table_columns.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for name, column_type in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {column_type}"))

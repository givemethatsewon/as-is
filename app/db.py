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
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_upload_batch_columns()
    _ensure_batch_owner_columns()


def _ensure_upload_batch_columns() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    existing = {column["name"] for column in inspector.get_columns("upload_batches")}
    columns = {
        "column_mapping_json": "TEXT",
        "invalidated_at": "DATETIME",
        "invalidated_reason": "VARCHAR(255)",
    }
    missing = [(name, column_type) for name, column_type in columns.items() if name not in existing]
    if not missing:
        return

    with engine.begin() as connection:
        for name, column_type in missing:
            connection.execute(text(f"ALTER TABLE upload_batches ADD COLUMN {name} {column_type}"))


def _ensure_batch_owner_columns() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_columns = {
        "import_lots": {"upload_batch_id": "VARCHAR(36)"},
        "export_requirements": {
            "upload_batch_id": "VARCHAR(36)",
            "order_no": "VARCHAR(120)",
            "seq_no": "VARCHAR(40)",
        },
    }
    with engine.begin() as connection:
        for table_name, columns in table_columns.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for name, column_type in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {column_type}"))

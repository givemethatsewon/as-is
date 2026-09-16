from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


TABLES_IN_DELETE_ORDER = (
    "export_allocations",
    "planned_allocations",
    "export_requirements",
    "import_lots",
    "upload_preview_rows",
    "processing_jobs",
    "upload_batches",
)


def sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Demo reset supports only an explicit SQLite DATABASE_URL.")
    path = Path(database_url.removeprefix(prefix)).resolve()
    if path.name != "as_is.db":
        raise ValueError(f"Refusing to reset unexpected database file: {path}")
    return path


def reset_demo(*, backup: bool, purge_uploads: bool) -> tuple[Path | None, dict[str, int]]:
    database = sqlite_path(os.environ.get("DATABASE_URL", "sqlite:////data/as_is.db"))
    if not database.is_file():
        raise FileNotFoundError(f"Database does not exist: {database}")

    backup_path = None
    with sqlite3.connect(database) as connection:
        if backup:
            backup_dir = database.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"as_is-{timestamp}.db"
            with sqlite3.connect(backup_path) as backup_connection:
                connection.backup(backup_connection)

        existing_tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        deleted: dict[str, int] = {}
        connection.execute("BEGIN IMMEDIATE")
        for table in TABLES_IN_DELETE_ORDER:
            if table not in existing_tables:
                continue
            before = connection.total_changes
            connection.execute(f'DELETE FROM "{table}"')
            deleted[table] = connection.total_changes - before
        connection.commit()

    if purge_uploads:
        upload_root = Path(os.environ.get("UPLOAD_DIR", "/data/uploads")).resolve()
        if upload_root.is_dir():
            for child in upload_root.iterdir():
                resolved = child.resolve()
                resolved.relative_to(upload_root)
                if child.is_dir():
                    shutil.rmtree(resolved)
                else:
                    child.unlink()

    return backup_path, deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up and clear As-Is demo workflow data.")
    parser.add_argument("--yes", action="store_true", help="Required confirmation for the destructive reset.")
    parser.add_argument("--no-backup", action="store_true", help="Skip the recoverable SQLite backup.")
    parser.add_argument("--purge-uploads", action="store_true", help="Remove stored original upload files.")
    args = parser.parse_args()
    if not args.yes:
        parser.error("--yes is required")
    backup_path, deleted = reset_demo(backup=not args.no_backup, purge_uploads=args.purge_uploads)
    print(f"backup={backup_path or 'skipped'}")
    print("deleted=" + ", ".join(f"{table}:{count}" for table, count in deleted.items()))


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4


ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xlsm"}
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class UploadTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    safe_filename: str
    size_bytes: int
    sha256: str


def upload_root() -> Path:
    return Path(os.getenv("UPLOAD_DIR", "./data/uploads"))


def max_upload_bytes() -> int:
    return int(os.getenv("MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES)))


def safe_upload_filename(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name.strip()
    stem = Path(basename).stem
    suffix = Path(basename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError("Only CSV, XLSX, and XLSM files are supported.")
    safe_stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", stem).strip("._-") or "upload"
    return f"{safe_stem}{suffix}"


def store_upload(
    stream: BinaryIO,
    filename: str,
    *,
    storage_root: Path | None = None,
    max_bytes: int | None = None,
) -> StoredUpload:
    root = (storage_root or upload_root()).resolve()
    safe_filename = safe_upload_filename(filename)
    limit = max_upload_bytes() if max_bytes is None else max_bytes
    upload_dir = root / str(uuid4())
    upload_dir.mkdir(parents=True, exist_ok=False)
    destination = upload_dir / safe_filename
    digest = hashlib.sha256()
    size = 0

    try:
        with destination.open("xb") as output:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise UploadTooLargeError(f"Upload exceeds the maximum size of {limit} bytes.")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        upload_dir.rmdir()
        raise

    if size == 0:
        destination.unlink(missing_ok=True)
        upload_dir.rmdir()
        raise ValueError("Uploaded file is empty.")

    return StoredUpload(
        path=destination,
        safe_filename=safe_filename,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )


def read_stored_upload(path: str | Path, *, storage_root: Path | None = None) -> bytes:
    root = (storage_root or upload_root()).resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Stored upload path is outside the upload directory.") from exc
    return resolved.read_bytes()

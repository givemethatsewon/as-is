from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from typing import Any

import pandas as pd
from fastapi import UploadFile


class ParseError(ValueError):
    pass


async def read_upload_rows(file: UploadFile) -> list[dict[str, Any]]:
    filename = file.filename or ""
    content = await file.read()
    if not content:
        raise ParseError("Uploaded file is empty.")

    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig")
        frame = pd.read_csv(StringIO(text), dtype=str).fillna("")
    elif filename.lower().endswith((".xlsx", ".xls")):
        frame = pd.read_excel(BytesIO(content), dtype=str).fillna("")
    else:
        raise ParseError("Only CSV and XLSX files are supported.")

    frame.columns = [str(column).strip() for column in frame.columns]
    return frame.to_dict(orient="records")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def optional_text(value: Any) -> str | None:
    text = clean_text(value)
    return text or None


def parse_date(value: Any, field: str) -> date:
    text = clean_text(value)
    if not text:
        raise ValueError(f"{field} is required.")
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"{field} must be a valid date.")
    return parsed.date()


def parse_positive_int(value: Any, field: str) -> int:
    text = clean_text(value).replace(",", "")
    if not text:
        raise ValueError(f"{field} is required.")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if number <= 0 or number != number.to_integral_value():
        raise ValueError(f"{field} must be a positive integer.")
    return int(number)


def parse_decimal(value: Any, field: str) -> Decimal | None:
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be numeric.") from exc


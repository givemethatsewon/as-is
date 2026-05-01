from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExportRequirement, ImportLot, UploadBatch, UploadPreviewRow, now_utc
from app.services.parsing import clean_text, optional_text, parse_date, parse_decimal, parse_positive_int


IMPORT_REQUIRED_COLUMNS = {
    "import_declaration_no",
    "import_accepted_date",
    "origin",
    "hs_code",
    "line_no",
    "row_no",
    "part_number",
    "spec",
    "import_qty",
    "qty_unit",
}
EXPORT_REQUIRED_COLUMNS = {"export_date", "origin", "part_number", "required_qty"}
EXPORT_OPTIONAL_COLUMNS = {
    "hs_code",
    "description",
    "unit_price",
}
IMPORT_COLUMN_ALIASES = {
    "import_declaration_no": ["import_declaration_no", "declaration_no", "수입신고번호", "신고번호"],
    "import_accepted_date": [
        "import_accepted_date",
        "declaration_date",
        "accepted_date",
        "import_date",
        "신고일자",
        "수리일",
        "수입신고일자",
        "수입신고 수리일",
    ],
    "origin": ["origin", "원산지"],
    "hs_code": ["hs_code", "HS Code", "세번", "세번코드"],
    "line_no": ["line_no", "란번호", "란번", "란번호2"],
    "row_no": ["row_no", "행번호", "행번", "행번호2"],
    "part_number": ["part_number", "Part Number", "판매부번", "품번"],
    "spec": ["spec", "규격", "규격2", "description", "Description"],
    "import_qty": ["import_qty", "quantity", "qty", "수량", "수량_1"],
    "qty_unit": ["qty_unit", "unit", "수량단위", "수량단위_1"],
}
EXPORT_COLUMN_ALIASES = {
    "export_date": ["export_date", "수출일", "수출일자", "수출예정일"],
    "origin": ["origin", "원산지"],
    "part_number": ["part_number", "Part Number", "판매부번", "품번"],
    "hs_code": ["hs_code", "HS Code", "세번", "세번코드"],
    "required_qty": ["required_qty", "수출요청수량", "필요수량", "필요 수량", "매칭필요수량"],
    "description": ["description", "Description", "품명", "규격", "설명"],
    "unit_price": ["unit_price", "단가"],
}
CANONICAL_FIELD_DESCRIPTIONS = {
    "export_date": "수출 예정일 또는 수출일",
    "required_qty": "수출 요청 수량",
    "import_declaration_no": "수입신고번호",
    "import_accepted_date": "수입신고 수리일",
    "origin": "원산지",
    "hs_code": "HS 코드 / 세번",
    "line_no": "수입신고 란번호",
    "row_no": "수입신고 행번호",
    "part_number": "품번 / Part Number",
    "spec": "규격 또는 품명",
    "import_qty": "수입 수량",
    "qty_unit": "수량 단위",
}


@dataclass(frozen=True)
class PreviewResult:
    batch: UploadBatch
    warnings: list[str]
    column_mapping: dict[str, str]


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def normalize_import_columns(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not rows:
        return rows, {}

    alias_lookup = _alias_lookup(IMPORT_COLUMN_ALIASES)
    columns = list(rows[0].keys())
    canonical_by_source: dict[str, str] = {}
    source_by_canonical: dict[str, str] = {}

    for source in columns:
        normalized = normalize_column_name(source)
        canonical = alias_lookup.get(normalized, normalized)
        if canonical in source_by_canonical:
            raise ValueError(
                "Multiple columns map to the same canonical field "
                f"{canonical}: {source_by_canonical[canonical]}, {source}. "
                f"Found columns: {', '.join(columns)}"
            )
        canonical_by_source[source] = canonical
        source_by_canonical[canonical] = source

    normalized_rows = [{canonical_by_source[source]: value for source, value in row.items()} for row in rows]
    missing = sorted(IMPORT_REQUIRED_COLUMNS - set(source_by_canonical))
    if missing:
        raise ValueError(
            "Missing required canonical columns: "
            f"{', '.join(missing)}. Found columns: {', '.join(columns)}"
        )
    mapping_preview = {canonical: source_by_canonical[canonical] for canonical in sorted(IMPORT_REQUIRED_COLUMNS)}
    return normalized_rows, mapping_preview


def normalize_export_columns(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not rows:
        return rows, {}

    alias_lookup = _alias_lookup(EXPORT_COLUMN_ALIASES)
    columns = list(rows[0].keys())
    canonical_by_source: dict[str, str] = {}
    source_by_canonical: dict[str, str] = {}

    for source in columns:
        normalized = normalize_column_name(source)
        canonical = alias_lookup.get(normalized, normalized)
        if canonical in source_by_canonical:
            raise ValueError(
                "Multiple columns map to the same canonical field "
                f"{canonical}: {source_by_canonical[canonical]}, {source}. "
                f"Found columns: {', '.join(columns)}"
            )
        canonical_by_source[source] = canonical
        source_by_canonical[canonical] = source

    normalized_rows = [{canonical_by_source[source]: value for source, value in row.items()} for row in rows]
    missing = sorted(EXPORT_REQUIRED_COLUMNS - set(source_by_canonical))
    if missing:
        raise ValueError(
            "Missing required canonical columns: "
            f"{', '.join(missing)}. Found columns: {', '.join(columns)}"
        )
    mapped_columns = sorted((EXPORT_REQUIRED_COLUMNS | EXPORT_OPTIONAL_COLUMNS) & set(source_by_canonical))
    mapping_preview = {canonical: source_by_canonical[canonical] for canonical in mapped_columns}
    return normalized_rows, mapping_preview


def normalize_column_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\r", " ").replace("\n", " ").strip()).casefold()


def _alias_lookup(alias_map: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in alias_map.items():
        lookup[normalize_column_name(canonical)] = canonical
        for alias in aliases:
            lookup[normalize_column_name(alias)] = canonical
    return lookup


def normalize_import_row(row: dict[str, Any]) -> dict[str, Any]:
    import_qty = parse_positive_int(row.get("import_qty"), "import_qty")
    return {
        "import_declaration_no": clean_text(row.get("import_declaration_no")),
        "import_accepted_date": parse_date(row.get("import_accepted_date"), "import_accepted_date").isoformat(),
        "origin": clean_text(row.get("origin")).upper(),
        "hs_code": clean_text(row.get("hs_code")),
        "line_no": clean_text(row.get("line_no")),
        "row_no": clean_text(row.get("row_no")),
        "part_number": clean_text(row.get("part_number")).upper(),
        "spec": optional_text(row.get("spec")),
        "import_qty": import_qty,
        "qty_unit": optional_text(row.get("qty_unit")),
        "duty_per_unit": parse_decimal(row.get("duty_per_unit"), "duty_per_unit"),
    }


def normalize_export_row(row: dict[str, Any]) -> dict[str, Any]:
    required_qty = parse_positive_int(row.get("required_qty"), "required_qty")
    unit_price = parse_decimal(row.get("unit_price"), "unit_price")
    amount = unit_price * required_qty if unit_price is not None else None
    return {
        "export_date": parse_date(row.get("export_date"), "export_date").isoformat(),
        "origin": clean_text(row.get("origin")).upper(),
        "part_number": clean_text(row.get("part_number")).upper(),
        "hs_code": optional_text(row.get("hs_code")),
        "required_qty": required_qty,
        "description": optional_text(row.get("description")),
        "unit_price": unit_price,
        "amount": amount,
    }


def import_business_key(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        payload["import_declaration_no"],
        payload["line_no"],
        payload["row_no"],
        payload["part_number"],
        payload["origin"],
    )


def _existing_import_by_key(db: Session, payload: dict[str, Any]) -> ImportLot | None:
    stmt = select(ImportLot).where(
        ImportLot.import_declaration_no == payload["import_declaration_no"],
        ImportLot.line_no == payload["line_no"],
        ImportLot.row_no == payload["row_no"],
        ImportLot.part_number == payload["part_number"],
        ImportLot.origin == payload["origin"],
    )
    return db.scalar(stmt)


def _classify_existing_import(existing: ImportLot, payload: dict[str, Any]) -> tuple[str, str]:
    same = (
        existing.import_accepted_date.isoformat() == payload["import_accepted_date"]
        and existing.hs_code == payload["hs_code"]
        and existing.import_qty == payload["import_qty"]
        and (existing.qty_unit or None) == payload["qty_unit"]
    )
    if same:
        return "duplicate", "Existing lot with the same business key and values."
    return "conflict", "Existing lot has the same business key but different values."


def preview_imports(db: Session, rows: list[dict[str, Any]], filename: str) -> PreviewResult:
    rows, column_mapping = normalize_import_columns(rows)
    batch = UploadBatch(
        upload_type="imports",
        filename=filename,
        total_rows=len(rows),
        column_mapping_json=json.dumps(column_mapping, ensure_ascii=False),
    )
    db.add(batch)
    db.flush()
    statuses: Counter[str] = Counter()
    seen_payloads: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    for index, row in enumerate(rows, start=2):
        try:
            payload = normalize_import_row(row)
            key = import_business_key(payload)
            if key in seen_payloads:
                if _payload_values_match(seen_payloads[key], payload):
                    status, message = "duplicate", "Duplicate lot inside uploaded file."
                else:
                    status, message = "conflict", "Uploaded file has the same business key with different values."
            else:
                seen_payloads[key] = payload
                existing = _existing_import_by_key(db, payload)
                status, message = _classify_existing_import(existing, payload) if existing else ("new", "Ready to insert.")
        except ValueError as exc:
            payload = {key: clean_text(value) for key, value in row.items()}
            status, message = "error", str(exc)

        statuses[status] += 1
        db.add(
            UploadPreviewRow(
                batch_id=batch.id,
                row_number=index,
                row_status=status,
                message=message,
                payload_json=json.dumps(payload, default=_json_default, ensure_ascii=False),
            )
        )

    _apply_status_counts(batch, statuses)
    db.commit()
    db.refresh(batch)
    return PreviewResult(batch=batch, warnings=[], column_mapping=column_mapping)


def preview_exports(db: Session, rows: list[dict[str, Any]], filename: str) -> PreviewResult:
    rows, column_mapping = normalize_export_columns(rows)
    batch = UploadBatch(
        upload_type="exports",
        filename=filename,
        total_rows=len(rows),
        column_mapping_json=json.dumps(column_mapping, ensure_ascii=False),
    )
    db.add(batch)
    db.flush()
    statuses: Counter[str] = Counter()

    for index, row in enumerate(rows, start=2):
        try:
            payload = normalize_export_row(row)
            status, message = "new", "Ready to insert."
        except ValueError as exc:
            payload = {key: clean_text(value) for key, value in row.items()}
            status, message = "error", str(exc)

        statuses[status] += 1
        db.add(
            UploadPreviewRow(
                batch_id=batch.id,
                row_number=index,
                row_status=status,
                message=message,
                payload_json=json.dumps(payload, default=_json_default, ensure_ascii=False),
            )
        )

    _apply_status_counts(batch, statuses)
    db.commit()
    db.refresh(batch)
    return PreviewResult(batch=batch, warnings=[], column_mapping=column_mapping)


def _apply_status_counts(batch: UploadBatch, statuses: Counter[str]) -> None:
    batch.new_count = statuses["new"]
    batch.duplicate_count = statuses["duplicate"]
    batch.conflict_count = statuses["conflict"]
    batch.error_count = statuses["error"]


def _payload_values_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return json.dumps(left, default=_json_default, sort_keys=True) == json.dumps(
        right, default=_json_default, sort_keys=True
    )


def confirm_batch(db: Session, batch_id: str) -> dict[str, int | str]:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise ValueError("검토한 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is not None:
        raise ValueError("이미 저장한 파일입니다.")
    if batch.invalidated_at is not None:
        raise ValueError("무효 처리된 파일은 저장할 수 없습니다.")

    inserted_count = 0
    skipped_count = 0
    error_count = 0
    for row in batch.rows:
        if row.row_status != "new":
            skipped_count += 1
            if row.row_status == "error":
                error_count += 1
            continue
        payload = json.loads(row.payload_json)
        if batch.upload_type == "imports":
            db.add(
                ImportLot(
                    import_declaration_no=payload["import_declaration_no"],
                    import_accepted_date=parse_date(payload["import_accepted_date"], "import_accepted_date"),
                    origin=payload["origin"],
                    hs_code=payload["hs_code"],
                    line_no=payload["line_no"],
                    row_no=payload["row_no"],
                    part_number=payload["part_number"],
                    spec=payload.get("spec"),
                    import_qty=payload["import_qty"],
                    qty_unit=payload.get("qty_unit"),
                    used_qty=0,
                    remaining_qty=payload["import_qty"],
                    duty_per_unit=parse_decimal(payload.get("duty_per_unit"), "duty_per_unit"),
                    status="available",
                )
            )
        else:
            db.add(
                ExportRequirement(
                    export_date=parse_date(payload["export_date"], "export_date"),
                    origin=payload["origin"],
                    part_number=payload["part_number"],
                    hs_code=payload.get("hs_code"),
                    description=payload.get("description"),
                    unit_price=parse_decimal(payload.get("unit_price"), "unit_price"),
                    required_qty=payload["required_qty"],
                    amount=parse_decimal(payload.get("amount"), "amount"),
                    status="pending",
                )
            )
        inserted_count += 1

    batch.confirmed_at = now_utc()
    db.commit()
    return {
        "batch_id": batch.id,
        "inserted_count": inserted_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
    }


def delete_unconfirmed_upload(db: Session, batch_id: str) -> None:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise ValueError("검토한 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is not None:
        raise ValueError("이미 저장한 파일은 삭제할 수 없습니다. 필요한 경우 무효 처리하세요.")
    db.delete(batch)
    db.commit()


def invalidate_confirmed_upload(db: Session, batch_id: str, reason: str | None = None) -> None:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise ValueError("검토한 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is None:
        raise ValueError("아직 저장하지 않은 파일은 삭제할 수 있습니다.")
    if batch.invalidated_at is not None:
        raise ValueError("이미 무효 처리된 파일입니다.")
    batch.invalidated_at = now_utc()
    batch.invalidated_reason = reason or "사용자가 파일 검토 화면에서 무효 처리했습니다."
    db.commit()


def column_mapping_for_batch(batch: UploadBatch) -> dict[str, str]:
    if not batch.column_mapping_json:
        return {}
    try:
        value = json.loads(batch.column_mapping_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}

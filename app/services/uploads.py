from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExportAllocation, ExportRequirement, ImportLot, UploadBatch, UploadPreviewRow, now_utc
from app.services.matching import update_lot_status
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
    "amount",
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
    "export_date": ["export_date", "수출일", "수출일자", "수출예정일", "Ready to Ship"],
    "origin": ["origin", "원산지"],
    "part_number": ["part_number", "Part Number", "판매부번", "품번"],
    "hs_code": ["hs_code", "HS Code", "세번", "세번코드", "HS코드", "세번부호"],
    "required_qty": ["required_qty", "수출요청수량", "필요수량", "필요 수량", "매칭필요수량", "Qty", "Quantity"],
    "description": ["description", "Description", "품명", "규격", "설명"],
    "unit_price": ["unit_price", "단가", "U/Price", "Unit Price"],
    "amount": ["amount", "Amount", "금액", "합계금액"],
}
CANONICAL_FIELD_DESCRIPTIONS = {
    "export_date": "수출 예정일 또는 수출일",
    "required_qty": "수출 파일 수량",
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
    "description": "수출 품명 또는 설명",
    "unit_price": "수출 단가",
    "amount": "수출 금액",
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
        missing_labels = [CANONICAL_FIELD_DESCRIPTIONS.get(column, column) for column in missing]
        raise ValueError(
            "필수 컬럼이 누락됐습니다: "
            f"{', '.join(missing_labels)} ({', '.join(missing)}). "
            f"업로드 파일 컬럼: {', '.join(columns)}"
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
    uploaded_amount = parse_decimal(row.get("amount"), "amount")
    amount = uploaded_amount if uploaded_amount is not None else unit_price * required_qty if unit_price is not None else None
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
    stmt = _import_by_key_stmt(payload).outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id).where(
        (ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None))
    )
    return db.scalar(stmt)


def _any_existing_import_by_key(db: Session, payload: dict[str, Any]) -> ImportLot | None:
    return db.scalar(_import_by_key_stmt(payload))


def _import_by_key_stmt(payload: dict[str, Any]):
    stmt = (
        select(ImportLot)
        .where(
            ImportLot.import_declaration_no == payload["import_declaration_no"],
            ImportLot.line_no == payload["line_no"],
            ImportLot.row_no == payload["row_no"],
            ImportLot.part_number == payload["part_number"],
            ImportLot.origin == payload["origin"],
        )
    )
    return stmt


def _is_from_invalidated_batch(db: Session, lot: ImportLot) -> bool:
    if lot.upload_batch_id is None:
        return False
    batch = db.get(UploadBatch, lot.upload_batch_id)
    return bool(batch and batch.invalidated_at is not None)


def _classify_existing_import(existing: ImportLot, payload: dict[str, Any]) -> tuple[str, str]:
    same = _existing_import_values(existing) == _payload_import_values(payload)
    if same:
        return "duplicate", "기존 반영 데이터와 동일한 수입 건입니다."
    return "conflict", "같은 수입 건이 이미 있지만 값이 달라 확인이 필요합니다."


def _classify_import_for_preview(db: Session, payload: dict[str, Any]) -> tuple[str, str]:
    existing = _existing_import_by_key(db, payload)
    if existing:
        return _classify_existing_import(existing, payload)

    invalidated_existing = _any_existing_import_by_key(db, payload)
    if invalidated_existing and _is_from_invalidated_batch(db, invalidated_existing):
        return "reactivate", "반영 취소된 기존 수입 건을 새 업로드 기준으로 다시 활성화합니다."

    return "new", "새로 반영할 수 있는 수입 건입니다."


def _existing_import_values(existing: ImportLot) -> tuple[str, str, str | None, int, str | None, str | None]:
    return (
        existing.import_accepted_date.isoformat(),
        existing.hs_code,
        existing.spec or None,
        existing.import_qty,
        existing.qty_unit or None,
        str(existing.duty_per_unit) if existing.duty_per_unit is not None else None,
    )


def _payload_import_values(payload: dict[str, Any]) -> tuple[str, str, str | None, int, str | None, str | None]:
    duty_per_unit = parse_decimal(payload.get("duty_per_unit"), "duty_per_unit")
    return (
        payload["import_accepted_date"],
        payload["hs_code"],
        payload.get("spec"),
        payload["import_qty"],
        payload.get("qty_unit"),
        str(duty_per_unit) if duty_per_unit is not None else None,
    )


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
                    status, message = "duplicate", "업로드 파일 안에 동일한 수입 건이 중복되어 있습니다."
                else:
                    status, message = "conflict", "업로드 파일 안에 같은 수입 건이 있지만 값이 서로 다릅니다."
            else:
                seen_payloads[key] = payload
                status, message = _classify_import_for_preview(db, payload)
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
            status, message = "new", "새로 반영할 수 있는 수출 건입니다."
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
        raise ValueError("업로드한 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is not None:
        raise ValueError("이미 반영한 파일입니다.")
    if batch.invalidated_at is not None:
        raise ValueError("반영 취소된 파일은 다시 반영할 수 없습니다.")

    inserted_count = 0
    reactivated_count = 0
    skipped_count = 0
    error_count = 0
    for row in batch.rows:
        if row.row_status not in {"new", "reactivate"}:
            skipped_count += 1
            if row.row_status == "error":
                error_count += 1
            continue
        payload = json.loads(row.payload_json)
        if batch.upload_type == "imports":
            if row.row_status == "reactivate":
                _reactivate_import_lot(db, payload, batch.id)
                reactivated_count += 1
            else:
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
                        upload_batch_id=batch.id,
                    )
                )
                inserted_count += 1
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
                    upload_batch_id=batch.id,
                )
            )
            inserted_count += 1

    batch.confirmed_at = now_utc()
    db.commit()
    return {
        "batch_id": batch.id,
        "inserted_count": inserted_count,
        "reactivated_count": reactivated_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
    }


def _reactivate_import_lot(db: Session, payload: dict[str, Any], batch_id: str) -> None:
    lot = _any_existing_import_by_key(db, payload)
    if lot is None or not _is_from_invalidated_batch(db, lot):
        raise ValueError("재활성화할 반영 취소 수입 건을 찾을 수 없습니다.")

    import_qty = int(payload["import_qty"])
    lot.import_accepted_date = parse_date(payload["import_accepted_date"], "import_accepted_date")
    lot.hs_code = payload["hs_code"]
    lot.spec = payload.get("spec")
    lot.import_qty = import_qty
    lot.qty_unit = payload.get("qty_unit")
    lot.used_qty = 0
    lot.remaining_qty = import_qty
    lot.duty_per_unit = parse_decimal(payload.get("duty_per_unit"), "duty_per_unit")
    lot.status = "available"
    lot.upload_batch_id = batch_id


def delete_unconfirmed_upload(db: Session, batch_id: str) -> None:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise ValueError("업로드한 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is not None:
        raise ValueError("이미 반영한 파일은 업로드 취소할 수 없습니다. 필요한 경우 반영 취소하세요.")
    db.delete(batch)
    db.commit()


def invalidate_confirmed_upload(db: Session, batch_id: str, reason: str | None = None) -> None:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise ValueError("업로드한 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is None:
        raise ValueError("아직 반영하지 않은 파일은 업로드 취소할 수 있습니다.")
    if batch.invalidated_at is not None:
        raise ValueError("이미 반영 취소된 파일입니다.")
    batch.invalidated_at = now_utc()
    batch.invalidated_reason = reason or "사용자가 파일 업로드 화면에서 반영 취소했습니다."
    if batch.upload_type == "imports":
        _remove_allocations_for_invalidated_import_batch(db, batch.id)
    elif batch.upload_type == "exports":
        _remove_allocations_for_invalidated_export_batch(db, batch.id)
    db.commit()


def _remove_allocations_for_invalidated_import_batch(db: Session, batch_id: str) -> None:
    lots = list(db.scalars(select(ImportLot).where(ImportLot.upload_batch_id == batch_id)))
    affected_exports: dict[str, ExportRequirement] = {}
    for lot in lots:
        for allocation in list(lot.allocations):
            affected_exports[allocation.export_requirement_id] = allocation.export_requirement
            db.delete(allocation)
    db.flush()
    for export in affected_exports.values():
        _refresh_export_status_from_active_allocations(db, export)


def _remove_allocations_for_invalidated_export_batch(db: Session, batch_id: str) -> None:
    exports = list(db.scalars(select(ExportRequirement).where(ExportRequirement.upload_batch_id == batch_id)))
    for export in exports:
        for allocation in list(export.allocations):
            lot = allocation.import_lot
            lot.used_qty = max(0, lot.used_qty - allocation.matched_qty)
            lot.remaining_qty += allocation.matched_qty
            update_lot_status(lot, export.export_date)
            db.delete(allocation)
        export.status = "invalidated"


def _refresh_export_status_from_active_allocations(db: Session, export: ExportRequirement) -> None:
    matched_qty = sum(
        db.scalars(
            select(ExportAllocation.matched_qty).where(ExportAllocation.export_requirement_id == export.id)
        ).all()
    )
    if matched_qty >= export.required_qty:
        export.status = "matched"
    elif matched_qty > 0:
        export.status = "partial_matched"
    else:
        export.status = "pending"


def column_mapping_for_batch(batch: UploadBatch) -> dict[str, str]:
    if not batch.column_mapping_json:
        return {}
    try:
        value = json.loads(batch.column_mapping_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}

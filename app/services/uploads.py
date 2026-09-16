from __future__ import annotations

import json
import re
import hashlib
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ExportAllocation,
    ExportRequirement,
    ImportLot,
    PlannedAllocation,
    UploadBatch,
    UploadPreviewRow,
    now_utc,
)
from app.services.allocation_plans import clean_part_number, plan_export_rows
from app.services.matching import update_lot_status
from app.services.parsing import clean_text, optional_text, parse_date, parse_decimal, parse_non_negative_int, parse_positive_int


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
EXPORT_REQUIRED_COLUMNS = {"export_date", "part_number", "required_qty"}
EXPORT_OPTIONAL_COLUMNS = {
    "order_no",
    "seq_no",
    "origin",
    "hs_code",
    "line_no",
    "description",
    "qty_unit",
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
    "part_number": ["part_number", "Part Number", "판매부번", "품번", "규격1"],
    "spec": ["spec", "규격", "규격2", "description", "Description"],
    "import_qty": ["import_qty", "quantity", "qty", "수량", "수량_1"],
    "remaining_qty": ["remaining_qty", "remaining", "잔량", "잔량 수량", "잔량수량", "남은 수량"],
    "qty_unit": ["qty_unit", "unit", "수량단위", "수량단위_1"],
}
EXPORT_COLUMN_ALIASES = {
    "export_date": ["export_date", "수출일", "수출일자", "수출예정일", "신고일자", "Shipping Date", "Invoice Date"],
    "order_no": ["order_no", "Order No", "Order No.", "오더번호", "주문번호", "수출신고번호"],
    "seq_no": ["seq_no", "Seq No", "Seq No.", "Sys No", "Sys No.", "순번", "행번호"],
    "origin": ["origin", "원산지"],
    "part_number": ["part_number", "Part Number", "판매부번", "품번", "규격1"],
    "hs_code": ["hs_code", "HS Code", "세번", "세번코드", "HS코드", "세번부호"],
    "line_no": ["line_no", "란번호", "란번", "란번호2"],
    "required_qty": [
        "required_qty",
        "수출요청수량",
        "필요수량",
        "필요 수량",
        "매칭필요수량",
        "수출수량",
        "Ready to Ship Qty",
        "Ready to Ship\nQty",
        "Ready to Ship Qty ",
        "Qty",
        "Quantity",
        "수량_1",
    ],
    "description": ["description", "Description", "품명", "규격", "규격2", "설명"],
    "qty_unit": ["qty_unit", "unit", "수량단위", "수량단위_1"],
    "unit_price": ["unit_price", "단가", "U/Price", "Unit Price"],
    "amount": ["amount", "Amount", "금액", "합계금액"],
}
CANONICAL_FIELD_DESCRIPTIONS = {
    "export_date": "수출 예정일 또는 수출일",
    "order_no": "수출 원본 Order No",
    "seq_no": "수출 원본 순번",
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
    "remaining_qty": "잔량 수량",
    "description": "수출 품명 또는 설명",
    "qty_unit": "수량단위_1",
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
    mapped_columns = sorted((IMPORT_REQUIRED_COLUMNS | {"remaining_qty"}) & set(source_by_canonical))
    mapping_preview = {canonical: source_by_canonical[canonical] for canonical in mapped_columns}
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
    remaining_qty = (
        parse_non_negative_int(row.get("remaining_qty"), "remaining_qty")
        if clean_text(row.get("remaining_qty"))
        else import_qty
    )
    if remaining_qty > import_qty:
        raise ValueError("remaining_qty must be less than or equal to import_qty.")
    return {
        "import_declaration_no": clean_text(row.get("import_declaration_no")),
        "import_accepted_date": parse_date(row.get("import_accepted_date"), "import_accepted_date").isoformat(),
        "origin": clean_text(row.get("origin")).upper(),
        "hs_code": clean_text(row.get("hs_code")),
        "line_no": clean_text(row.get("line_no")),
        "row_no": clean_text(row.get("row_no")),
        "part_number": clean_part_number(row.get("part_number")),
        "spec": optional_text(row.get("spec")),
        "import_qty": import_qty,
        "remaining_qty": remaining_qty,
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
        "order_no": optional_text(row.get("order_no")),
        "seq_no": optional_text(row.get("seq_no")),
        "origin": clean_text(row.get("origin")).upper(),
        "part_number": clean_part_number(row.get("part_number")),
        "hs_code": optional_text(row.get("hs_code")),
        "line_no": optional_text(row.get("line_no")),
        "required_qty": required_qty,
        "description": optional_text(row.get("description")),
        "qty_unit": optional_text(row.get("qty_unit")),
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
        return "reactivate", "무효 처리된 기존 수입 건을 새 업로드 기준으로 다시 활성화합니다."

    return "new", "Ready to insert."


def _existing_import_values(existing: ImportLot) -> tuple[str, str, str | None, int, int, str | None, str | None]:
    return (
        existing.import_accepted_date.isoformat(),
        existing.hs_code,
        existing.spec or None,
        existing.import_qty,
        existing.remaining_qty,
        existing.qty_unit or None,
        str(existing.duty_per_unit) if existing.duty_per_unit is not None else None,
    )


def _payload_import_values(payload: dict[str, Any]) -> tuple[str, str, str | None, int, int, str | None, str | None]:
    duty_per_unit = parse_decimal(payload.get("duty_per_unit"), "duty_per_unit")
    return (
        payload["import_accepted_date"],
        payload["hs_code"],
        payload.get("spec"),
        payload["import_qty"],
        payload["remaining_qty"],
        payload.get("qty_unit"),
        str(duty_per_unit) if duty_per_unit is not None else None,
    )


def preview_imports(
    db: Session,
    rows: list[dict[str, Any]],
    filename: str,
    *,
    batch: UploadBatch | None = None,
) -> PreviewResult:
    rows, column_mapping = normalize_import_columns(rows)
    if batch is None:
        batch = UploadBatch(upload_type="imports", filename=filename)
        db.add(batch)
        db.flush()
    batch.total_rows = len(rows)
    batch.column_mapping_json = json.dumps(column_mapping, ensure_ascii=False)
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
    batch.processed_rows = len(rows)
    batch.status = "review_ready"
    db.commit()
    db.refresh(batch)
    return PreviewResult(batch=batch, warnings=[], column_mapping=column_mapping)


def preview_exports(
    db: Session,
    rows: list[dict[str, Any]],
    filename: str,
    *,
    batch: UploadBatch | None = None,
) -> PreviewResult:
    rows, column_mapping = normalize_export_columns(rows)
    if batch is None:
        batch = UploadBatch(upload_type="exports", filename=filename)
        db.add(batch)
        db.flush()
    batch.total_rows = len(rows)
    batch.column_mapping_json = json.dumps(column_mapping, ensure_ascii=False)
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
    batch.processed_rows = len(rows)
    batch.status = "review_ready"
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


class ImportPreviewAccumulator:
    """Classify and persist import rows incrementally for large background jobs."""

    def __init__(self, db: Session, batch: UploadBatch):
        if batch.upload_type != "imports":
            raise ValueError("Import preview accumulator requires an import batch.")
        self.db = db
        self.batch = batch
        self.statuses: Counter[str] = Counter()
        self.seen_hashes: dict[tuple[str, str, str, str, str], str] = {}
        self.source_by_canonical: dict[str, str] | None = None
        self.active_existing: dict[tuple[str, str, str, str, str], ImportLot] = {}
        self.invalidated_existing: dict[tuple[str, str, str, str, str], ImportLot] = {}

        for lot in db.scalars(select(ImportLot)):
            key = (
                lot.import_declaration_no,
                lot.line_no,
                lot.row_no,
                clean_part_number(lot.part_number),
                lot.origin,
            )
            owner = db.get(UploadBatch, lot.upload_batch_id) if lot.upload_batch_id else None
            if owner is not None and owner.invalidated_at is not None:
                self.invalidated_existing[key] = lot
            else:
                self.active_existing[key] = lot

    def process(self, row_number: int, source_row: dict[str, Any]) -> None:
        if self.source_by_canonical is None:
            normalized_rows, mapping = normalize_import_columns([source_row])
            self.source_by_canonical = mapping
            normalized_source = normalized_rows[0]
            self.batch.column_mapping_json = json.dumps(mapping, ensure_ascii=False)
        else:
            normalized_source = {
                canonical: source_row.get(source)
                for canonical, source in self.source_by_canonical.items()
            }

        try:
            payload = normalize_import_row(normalized_source)
            key = import_business_key(payload)
            payload_hash = hashlib.sha256(
                json.dumps(payload, default=_json_default, sort_keys=True).encode()
            ).hexdigest()
            if key in self.seen_hashes:
                if self.seen_hashes[key] == payload_hash:
                    status, message = "duplicate", "Duplicate lot inside uploaded file."
                else:
                    status, message = "conflict", "Uploaded file has the same business key with different values."
            else:
                self.seen_hashes[key] = payload_hash
                existing = self.active_existing.get(key)
                if existing is not None:
                    status, message = _classify_existing_import(existing, payload)
                elif key in self.invalidated_existing:
                    status, message = "reactivate", "무효 처리된 기존 수입 건을 새 업로드 기준으로 다시 활성화합니다."
                else:
                    status, message = "new", "Ready to insert."
        except ValueError as exc:
            payload = {key: clean_text(value) for key, value in source_row.items()}
            status, message = "error", str(exc)

        self.statuses[status] += 1
        self.db.add(
            UploadPreviewRow(
                batch_id=self.batch.id,
                row_number=row_number,
                row_status=status,
                message=message,
                payload_json=json.dumps(payload, default=_json_default, ensure_ascii=False),
            )
        )

    def finalize(self, total_rows: int) -> None:
        self.batch.total_rows = total_rows
        self.batch.processed_rows = total_rows
        self.batch.status = "review_ready"
        _apply_status_counts(self.batch, self.statuses)


def confirm_batch(db: Session, batch_id: str) -> dict[str, int | str]:
    batch = db.get(UploadBatch, batch_id)
    if batch is None:
        raise ValueError("검토한 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is not None:
        raise ValueError("이미 저장한 파일입니다.")
    if batch.invalidated_at is not None:
        raise ValueError("무효 처리된 파일은 저장할 수 없습니다.")
    if batch.upload_type == "imports" and (batch.conflict_count or batch.error_count):
        raise ValueError("충돌(conflict) 또는 오류가 있는 수입 파일은 전체를 저장할 수 없습니다.")

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
                        used_qty=payload["import_qty"] - payload["remaining_qty"],
                        remaining_qty=payload["remaining_qty"],
                        duty_per_unit=parse_decimal(payload.get("duty_per_unit"), "duty_per_unit"),
                        status="used_up" if payload["remaining_qty"] == 0 else "available",
                        upload_batch_id=batch.id,
                    )
                )
                inserted_count += 1
        else:
            db.add(
                    ExportRequirement(
                        export_date=parse_date(payload["export_date"], "export_date"),
                        order_no=payload.get("order_no"),
                        seq_no=payload.get("seq_no"),
                    origin=payload["origin"],
                    part_number=payload["part_number"],
                    hs_code=payload.get("hs_code"),
                    line_no=payload.get("line_no"),
                    description=payload.get("description"),
                    qty_unit=payload.get("qty_unit"),
                    unit_price=parse_decimal(payload.get("unit_price"), "unit_price"),
                    required_qty=payload["required_qty"],
                    amount=parse_decimal(payload.get("amount"), "amount"),
                    status="pending",
                    upload_batch_id=batch.id,
                )
            )
            inserted_count += 1

    batch.confirmed_at = now_utc()
    batch.status = "confirmed"
    db.commit()
    return {
        "batch_id": batch.id,
        "inserted_count": inserted_count,
        "reactivated_count": reactivated_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
    }


def inventory_fingerprint(db: Session) -> str:
    lots = list(
        db.scalars(
            select(ImportLot)
            .outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id)
            .where((ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
            .order_by(ImportLot.id)
        )
    )
    state = [
        (
            lot.id,
            lot.import_declaration_no,
            lot.import_accepted_date.isoformat(),
            lot.line_no,
            lot.row_no,
            clean_part_number(lot.part_number),
            lot.origin,
            lot.remaining_qty,
            lot.used_qty,
        )
        for lot in lots
    ]
    return hashlib.sha256(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def preview_export_run(
    db: Session,
    rows: list[dict[str, Any]],
    filename: str,
    *,
    batch: UploadBatch | None = None,
) -> PreviewResult:
    result = preview_exports(db, rows, filename, batch=batch)
    batch = result.batch
    batch.status = "review_ready"
    batch.inventory_fingerprint = inventory_fingerprint(db)

    preview_rows = sorted(
        (row for row in batch.rows if row.row_status == "new"),
        key=lambda row: row.row_number,
    )
    export_adapters = []
    for row in preview_rows:
        payload = json.loads(row.payload_json)
        export_adapters.append(
            _PlanExportRow(
                id=row.id,
                part_number=payload["part_number"],
                origin=payload["origin"],
                export_date=parse_date(payload["export_date"], "export_date"),
                required_qty=int(payload["required_qty"]),
            )
        )

    lots = list(
        db.scalars(
            select(ImportLot)
            .outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id)
            .where((ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        )
    )
    plans = plan_export_rows(export_adapters, lots)
    for plan in plans:
        sequence = 1
        for allocation in plan.allocations:
            db.add(
                PlannedAllocation(
                    batch_id=batch.id,
                    preview_row_id=plan.export_id,
                    import_lot_id=allocation.import_lot_id,
                    sequence=sequence,
                    matched_qty=allocation.quantity,
                    remaining_qty_after=allocation.remaining_qty_after,
                    shortage_qty=0,
                    hs_code=allocation.hs_code,
                    spec=allocation.spec,
                )
            )
            sequence += 1
        if plan.shortage_qty:
            db.add(
                PlannedAllocation(
                    batch_id=batch.id,
                    preview_row_id=plan.export_id,
                    import_lot_id=None,
                    sequence=sequence,
                    matched_qty=0,
                    remaining_qty_after=None,
                    shortage_qty=plan.shortage_qty,
                )
            )
    db.commit()
    db.refresh(batch)
    return result


@dataclass(frozen=True)
class _PlanExportRow:
    id: str
    part_number: str
    origin: str
    export_date: object
    required_qty: int


def confirm_match_run(db: Session, batch_id: str) -> dict[str, int | str]:
    batch = db.get(UploadBatch, batch_id)
    if batch is None or batch.upload_type != "exports":
        raise ValueError("수출 매칭 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is not None:
        raise ValueError("이미 확정한 수출 매칭 파일입니다.")
    if batch.reverted_at is not None:
        raise ValueError("되돌린 수출 매칭 파일은 다시 확정할 수 없습니다.")
    if batch.error_count:
        raise ValueError("오류가 있는 수출 파일은 확정할 수 없습니다.")
    if batch.inventory_fingerprint != inventory_fingerprint(db):
        raise ValueError("미리보기 이후 재고가 변경되었습니다. 파일을 다시 검토해 주세요.")

    allocation_count = 0
    shortage_count = 0
    export_count = 0
    try:
        for preview_row in sorted(batch.rows, key=lambda row: row.row_number):
            if preview_row.row_status != "new":
                continue
            payload = json.loads(preview_row.payload_json)
            plans = sorted(preview_row.planned_allocations, key=lambda plan: plan.sequence)
            matched_total = sum(plan.matched_qty for plan in plans)
            shortage_total = sum(plan.shortage_qty for plan in plans)
            requirement = ExportRequirement(
                export_date=parse_date(payload["export_date"], "export_date"),
                order_no=payload.get("order_no"),
                seq_no=payload.get("seq_no"),
                origin=payload["origin"],
                part_number=payload["part_number"],
                hs_code=payload.get("hs_code"),
                line_no=payload.get("line_no"),
                description=payload.get("description"),
                qty_unit=payload.get("qty_unit"),
                unit_price=parse_decimal(payload.get("unit_price"), "unit_price"),
                required_qty=payload["required_qty"],
                amount=parse_decimal(payload.get("amount"), "amount"),
                status="matched" if not shortage_total else "partial_matched" if matched_total else "insufficient_stock",
                upload_batch_id=batch.id,
            )
            db.add(requirement)
            db.flush()
            export_count += 1

            for plan in plans:
                plan.export_requirement_id = requirement.id
                if plan.shortage_qty:
                    shortage_count += 1
                    continue
                lot = db.get(ImportLot, plan.import_lot_id)
                if lot is None or lot.remaining_qty < plan.matched_qty:
                    raise ValueError("확정 중 재고가 변경되었습니다. 파일을 다시 검토해 주세요.")
                lot.remaining_qty -= plan.matched_qty
                lot.used_qty += plan.matched_qty
                update_lot_status(lot, requirement.export_date)
                expected_refund = (
                    lot.duty_per_unit * plan.matched_qty if lot.duty_per_unit is not None else None
                )
                db.add(
                    ExportAllocation(
                        export_requirement_id=requirement.id,
                        import_lot_id=lot.id,
                        matched_qty=plan.matched_qty,
                        remaining_qty_after=lot.remaining_qty,
                        expected_refund_amount=expected_refund,
                        match_status=requirement.status,
                    )
                )
                allocation_count += 1

        batch.confirmed_at = now_utc()
        batch.status = "confirmed"
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "batch_id": batch.id,
        "export_count": export_count,
        "allocation_count": allocation_count,
        "shortage_count": shortage_count,
    }


def revert_match_run(db: Session, batch_id: str) -> dict[str, int | str]:
    batch = db.get(UploadBatch, batch_id)
    if batch is None or batch.upload_type != "exports":
        raise ValueError("수출 매칭 파일을 찾을 수 없습니다.")
    if batch.confirmed_at is None:
        raise ValueError("아직 확정하지 않은 수출 매칭 파일입니다.")
    if batch.reverted_at is not None:
        raise ValueError("이미 되돌린 수출 매칭 파일입니다.")

    requirements = list(
        db.scalars(select(ExportRequirement).where(ExportRequirement.upload_batch_id == batch.id))
    )
    restored_qty = 0
    allocation_count = 0
    try:
        for requirement in requirements:
            for allocation in requirement.allocations:
                lot = allocation.import_lot
                lot.remaining_qty += allocation.matched_qty
                lot.used_qty = max(0, lot.used_qty - allocation.matched_qty)
                update_lot_status(lot, requirement.export_date)
                restored_qty += allocation.matched_qty
                allocation_count += 1
            requirement.status = "reverted"
        batch.reverted_at = now_utc()
        batch.status = "reverted"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "batch_id": batch.id,
        "restored_qty": restored_qty,
        "allocation_count": allocation_count,
    }


def _reactivate_import_lot(db: Session, payload: dict[str, Any], batch_id: str) -> None:
    lot = _any_existing_import_by_key(db, payload)
    if lot is None or not _is_from_invalidated_batch(db, lot):
        raise ValueError("재활성화할 무효 처리 수입 건을 찾을 수 없습니다.")

    import_qty = int(payload["import_qty"])
    remaining_qty = int(payload["remaining_qty"])
    lot.import_accepted_date = parse_date(payload["import_accepted_date"], "import_accepted_date")
    lot.hs_code = payload["hs_code"]
    lot.spec = payload.get("spec")
    lot.import_qty = import_qty
    lot.qty_unit = payload.get("qty_unit")
    lot.used_qty = import_qty - remaining_qty
    lot.remaining_qty = remaining_qty
    lot.duty_per_unit = parse_decimal(payload.get("duty_per_unit"), "duty_per_unit")
    lot.status = "used_up" if remaining_qty == 0 else "available"
    lot.upload_batch_id = batch_id


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

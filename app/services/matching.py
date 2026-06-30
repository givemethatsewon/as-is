from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExportAllocation, ExportRequirement, ImportLot, UploadBatch
from app.services.policy import EXPIRING_SOON_START_DAYS, MATCH_WINDOW_DAYS


MATCHABLE_EXPORT_STATUSES = {"pending", "partial_matched", "insufficient_stock"}


@dataclass(frozen=True)
class MatchingSummary:
    matched_count: int
    partial_matched_count: int
    insufficient_stock_count: int
    allocation_count: int


def update_lot_status(lot: ImportLot, reference_date: date | None = None) -> None:
    if lot.remaining_qty <= 0:
        lot.status = "used_up"
        return
    if reference_date is None:
        lot.status = "available"
        return

    age_days = (reference_date - lot.import_accepted_date).days
    if age_days > MATCH_WINDOW_DAYS:
        lot.status = "expired"
    elif age_days >= EXPIRING_SOON_START_DAYS:
        lot.status = "expiring_soon"
    else:
        lot.status = "available"


def run_matching(db: Session, export_date: date | None = None) -> MatchingSummary:
    stmt = (
        select(ExportRequirement)
        .outerjoin(UploadBatch, ExportRequirement.upload_batch_id == UploadBatch.id)
        .where(ExportRequirement.status.in_(MATCHABLE_EXPORT_STATUSES))
        .where((ExportRequirement.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)))
        .order_by(ExportRequirement.export_date, ExportRequirement.part_number, ExportRequirement.origin, ExportRequirement.id)
    )
    if export_date is not None:
        stmt = stmt.where(ExportRequirement.export_date == export_date)

    exports = list(db.scalars(stmt))
    matched_count = 0
    partial_matched_count = 0
    insufficient_stock_count = 0
    allocation_count = 0

    for export in exports:
        created = allocate_export(db, export)
        allocation_count += created
        if export.status == "matched":
            matched_count += 1
        elif export.status == "partial_matched":
            partial_matched_count += 1
        elif export.status == "insufficient_stock":
            insufficient_stock_count += 1

    db.commit()
    return MatchingSummary(
        matched_count=matched_count,
        partial_matched_count=partial_matched_count,
        insufficient_stock_count=insufficient_stock_count,
        allocation_count=allocation_count,
    )


def undo_export_matching(db: Session, export_requirement_id: str) -> int:
    export = db.get(ExportRequirement, export_requirement_id)
    if export is None:
        raise ValueError("수출 요청을 찾을 수 없습니다.")

    allocations = list(export.allocations)
    for allocation in allocations:
        lot = allocation.import_lot
        lot.used_qty = max(0, lot.used_qty - allocation.matched_qty)
        lot.remaining_qty += allocation.matched_qty
        update_lot_status(lot, export.export_date)
        db.delete(allocation)

    export.status = "pending"
    db.commit()
    return len(allocations)


def allocate_export(db: Session, export: ExportRequirement) -> int:
    existing_matched = db.scalar(
        select(func.coalesce(func.sum(ExportAllocation.matched_qty), 0)).where(
            ExportAllocation.export_requirement_id == export.id
        )
    )
    required = export.required_qty - int(existing_matched or 0)
    if required <= 0:
        export.status = "matched"
        return 0

    mark_expired_lots(db, export)
    candidates = list(
        db.scalars(
            select(ImportLot)
            .outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id)
            .where(
                # 핵심 조건: 품번 동일 + 원산지 동일 + 정책 기간 이내 후보 중 잔량이 있는 건만 FIFO로 차감합니다.
                ImportLot.part_number == export.part_number,
                ImportLot.origin == export.origin,
                ImportLot.remaining_qty > 0,
                ImportLot.import_accepted_date <= export.export_date,
                (ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)),
            )
            .order_by(
                ImportLot.import_accepted_date.asc(),
                ImportLot.import_declaration_no.asc(),
                ImportLot.line_no.asc(),
                ImportLot.row_no.asc(),
            )
        )
    )

    created = 0
    for lot in candidates:
        age_days = (export.export_date - lot.import_accepted_date).days
        if age_days > MATCH_WINDOW_DAYS:
            lot.status = "expired"
            continue
        if required <= 0:
            break

        matched_qty = min(required, lot.remaining_qty)
        lot.remaining_qty -= matched_qty
        lot.used_qty += matched_qty
        required -= matched_qty
        update_lot_status(lot, export.export_date)

        warning = None
        if export.hs_code and export.hs_code != lot.hs_code:
            warning = f"Export HS code {export.hs_code} differs from import HS code {lot.hs_code}."

        db.add(
            ExportAllocation(
                export_requirement_id=export.id,
                import_lot_id=lot.id,
                matched_qty=matched_qty,
                remaining_qty_after=lot.remaining_qty,
                expected_refund_amount=_expected_refund(matched_qty, lot.duty_per_unit),
                match_status="allocated",
                hs_code_warning=warning,
            )
        )
        created += 1

    total_matched = export.required_qty - required
    if required == 0:
        export.status = "matched"
    elif total_matched > 0:
        export.status = "partial_matched"
    else:
        export.status = "insufficient_stock"

    for allocation in export.allocations:
        allocation.match_status = export.status

    return created


def mark_expired_lots(db: Session, export: ExportRequirement) -> None:
    lots = db.scalars(
        select(ImportLot)
        .outerjoin(UploadBatch, ImportLot.upload_batch_id == UploadBatch.id)
        .where(
            ImportLot.part_number == export.part_number,
            ImportLot.origin == export.origin,
            ImportLot.remaining_qty > 0,
            ImportLot.import_accepted_date <= export.export_date,
            (ImportLot.upload_batch_id.is_(None)) | (UploadBatch.invalidated_at.is_(None)),
        )
    )
    for lot in lots:
        update_lot_status(lot, export.export_date)


def _expected_refund(matched_qty: int, duty_per_unit: Decimal | None) -> Decimal | None:
    if duty_per_unit is None:
        return None
    return duty_per_unit * matched_qty

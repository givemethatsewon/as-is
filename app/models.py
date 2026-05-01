from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_uuid() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class ImportLot(Base):
    __tablename__ = "import_lots"
    __table_args__ = (
        UniqueConstraint(
            "import_declaration_no",
            "line_no",
            "row_no",
            "part_number",
            "origin",
            name="uq_import_lot_business_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    import_declaration_no: Mapped[str] = mapped_column(String(80), nullable=False)
    import_accepted_date: Mapped[date] = mapped_column(Date, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    hs_code: Mapped[str] = mapped_column(String(20), nullable=False)
    line_no: Mapped[str] = mapped_column(String(20), nullable=False)
    row_no: Mapped[str] = mapped_column(String(20), nullable=False)
    part_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    spec: Mapped[str | None] = mapped_column(String(255))
    import_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_unit: Mapped[str | None] = mapped_column(String(20))
    used_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    duty_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="available", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    allocations: Mapped[list[ExportAllocation]] = relationship(back_populates="import_lot")


class ExportRequirement(Base):
    __tablename__ = "export_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    export_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    part_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    hs_code: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(String(255))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    required_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    allocations: Mapped[list[ExportAllocation]] = relationship(back_populates="export_requirement")


class ExportAllocation(Base):
    __tablename__ = "export_allocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    export_requirement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("export_requirements.id"), nullable=False, index=True
    )
    import_lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("import_lots.id"), nullable=False, index=True)
    matched_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_qty_after: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    match_status: Mapped[str] = mapped_column(String(40), nullable=False)
    hs_code_warning: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    export_requirement: Mapped[ExportRequirement] = relationship(back_populates="allocations")
    import_lot: Mapped[ImportLot] = relationship(back_populates="allocations")


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    upload_type: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_mapping_json: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    rows: Mapped[list[UploadPreviewRow]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class UploadPreviewRow(Base):
    __tablename__ = "upload_preview_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("upload_batches.id"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    row_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(String(500))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    batch: Mapped[UploadBatch] = relationship(back_populates="rows")

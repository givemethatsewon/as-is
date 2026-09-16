from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


_PART_NUMBER_WHITESPACE = str.maketrans("", "", " \u00a0\t\r\n")


class ExportRow(Protocol):
    id: str
    part_number: str
    origin: str
    export_date: object
    required_qty: int


class InventoryLot(Protocol):
    id: str
    part_number: str
    origin: str
    import_accepted_date: object
    import_declaration_no: str
    line_no: str
    row_no: str
    remaining_qty: int
    hs_code: str
    spec: str | None


@dataclass(frozen=True)
class PlannedAllocation:
    import_lot_id: str
    quantity: int
    remaining_qty_after: int
    hs_code: str
    spec: str | None


@dataclass(frozen=True)
class PlannedExport:
    export_id: str
    required_qty: int
    allocations: tuple[PlannedAllocation, ...]
    shortage_qty: int


def clean_part_number(value: object) -> str:
    """Apply the exact whitespace removal and case rule used by the VBA macro."""
    if value is None:
        return ""
    return str(value).translate(_PART_NUMBER_WHITESPACE).upper()


def plan_export_rows(
    exports: Iterable[ExportRow],
    lots: Iterable[InventoryLot],
    eligibility_days: int,
) -> list[PlannedExport]:
    """Plan allocations in memory without mutating inventory or ORM objects."""
    if eligibility_days < 0:
        raise ValueError("eligibility_days must be zero or greater")

    ordered_lots = sorted(
        lots,
        key=lambda lot: (
            lot.import_accepted_date,
            str(lot.import_declaration_no),
            str(lot.line_no),
            str(lot.row_no),
        ),
    )
    available = {lot.id: max(0, int(lot.remaining_qty)) for lot in ordered_lots}
    plans: list[PlannedExport] = []

    for export in exports:
        needed = max(0, int(export.required_qty))
        allocations: list[PlannedAllocation] = []

        for lot in ordered_lots:
            if needed == 0:
                break
            remaining = available[lot.id]
            if remaining <= 0:
                continue
            if clean_part_number(lot.part_number) != clean_part_number(export.part_number):
                continue
            if lot.origin != export.origin:
                continue

            age_days = (export.export_date - lot.import_accepted_date).days
            if age_days < 0 or age_days > eligibility_days:
                continue

            quantity = min(needed, remaining)
            available[lot.id] -= quantity
            needed -= quantity
            allocations.append(
                PlannedAllocation(
                    import_lot_id=lot.id,
                    quantity=quantity,
                    remaining_qty_after=available[lot.id],
                    hs_code=lot.hs_code,
                    spec=lot.spec,
                )
            )

        plans.append(
            PlannedExport(
                export_id=export.id,
                required_qty=max(0, int(export.required_qty)),
                allocations=tuple(allocations),
                shortage_qty=needed,
            )
        )

    return plans

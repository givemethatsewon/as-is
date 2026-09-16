from dataclasses import dataclass
from datetime import date, timedelta

from app.services.allocation_plans import clean_part_number, plan_export_rows


@dataclass(frozen=True)
class Lot:
    id: str
    part_number: str
    origin: str
    import_accepted_date: date
    import_declaration_no: str
    line_no: str
    row_no: str
    remaining_qty: int
    hs_code: str = ""
    spec: str | None = None


@dataclass(frozen=True)
class Export:
    id: str
    part_number: str
    origin: str
    export_date: date
    required_qty: int
    hs_code: str | None = None


def lot(
    lot_id: str,
    *,
    accepted: date,
    remaining: int,
    part: str = "AB-100",
    origin: str = "CN",
    declaration: str = "IMP-001",
    line: str = "1",
    row: str = "1",
    hs_code: str = "8501",
    spec: str | None = "SPEC-A",
) -> Lot:
    return Lot(
        id=lot_id,
        part_number=part,
        origin=origin,
        import_accepted_date=accepted,
        import_declaration_no=declaration,
        line_no=line,
        row_no=row,
        remaining_qty=remaining,
        hs_code=hs_code,
        spec=spec,
    )


def export(
    export_id: str,
    *,
    on: date,
    required: int,
    part: str = "AB-100",
    origin: str = "CN",
    hs_code: str | None = "DIFFERENT-HS",
) -> Export:
    return Export(
        id=export_id,
        part_number=part,
        origin=origin,
        export_date=on,
        required_qty=required,
        hs_code=hs_code,
    )


def test_clean_part_number_matches_vba_whitespace_rules() -> None:
    assert clean_part_number(" ab\u00a0-\t1\r\n00 ") == "AB-100"


def test_origin_mismatch_is_excluded_but_hs_mismatch_is_not() -> None:
    exported_on = date(2026, 9, 16)
    plans = plan_export_rows(
        [export("E1", on=exported_on, required=4)],
        [
            lot("WRONG-ORIGIN", accepted=exported_on, remaining=10, origin="VN"),
            lot("RIGHT", accepted=exported_on, remaining=10, hs_code="9999"),
        ],
        eligibility_days=720,
    )

    assert [(item.import_lot_id, item.quantity, item.hs_code) for item in plans[0].allocations] == [
        ("RIGHT", 4, "9999")
    ]
    assert plans[0].shortage_qty == 0


def test_720_days_is_inclusive_and_721_days_is_excluded() -> None:
    exported_on = date(2026, 9, 16)
    plans = plan_export_rows(
        [export("E1", on=exported_on, required=8)],
        [
            lot("OLD", accepted=exported_on - timedelta(days=721), remaining=10),
            lot("BOUNDARY", accepted=exported_on - timedelta(days=720), remaining=10),
        ],
        eligibility_days=720,
    )

    assert [(item.import_lot_id, item.quantity) for item in plans[0].allocations] == [("BOUNDARY", 8)]


def test_import_after_export_and_zero_balance_are_excluded() -> None:
    exported_on = date(2026, 9, 16)
    plans = plan_export_rows(
        [export("E1", on=exported_on, required=2)],
        [
            lot("FUTURE", accepted=exported_on + timedelta(days=1), remaining=10),
            lot("EMPTY", accepted=exported_on, remaining=0),
        ],
        eligibility_days=720,
    )

    assert plans[0].allocations == ()
    assert plans[0].shortage_qty == 2


def test_fifo_ties_use_declaration_line_then_row() -> None:
    exported_on = date(2026, 9, 16)
    accepted = exported_on - timedelta(days=10)
    plans = plan_export_rows(
        [export("E1", on=exported_on, required=4)],
        [
            lot("ROW-2", accepted=accepted, remaining=1, declaration="A", line="1", row="2"),
            lot("DECL-B", accepted=accepted, remaining=1, declaration="B", line="1", row="1"),
            lot("LINE-2", accepted=accepted, remaining=1, declaration="A", line="2", row="1"),
            lot("ROW-1", accepted=accepted, remaining=1, declaration="A", line="1", row="1"),
        ],
        eligibility_days=720,
    )

    assert [item.import_lot_id for item in plans[0].allocations] == ["ROW-1", "ROW-2", "LINE-2", "DECL-B"]


def test_split_allocation_and_shortage_reserve_stock_across_export_rows() -> None:
    exported_on = date(2026, 9, 16)
    plans = plan_export_rows(
        [
            export("E1", on=exported_on, required=7, part=" ab-100 "),
            export("E2", on=exported_on, required=6),
        ],
        [
            lot("L1", accepted=exported_on - timedelta(days=2), remaining=5),
            lot("L2", accepted=exported_on - timedelta(days=1), remaining=5),
        ],
        eligibility_days=720,
    )

    assert [(item.import_lot_id, item.quantity) for item in plans[0].allocations] == [("L1", 5), ("L2", 2)]
    assert plans[0].shortage_qty == 0
    assert [(item.import_lot_id, item.quantity) for item in plans[1].allocations] == [("L2", 3)]
    assert plans[1].shortage_qty == 3


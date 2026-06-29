from __future__ import annotations

import json
from typing import Any

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")


STATUS_LABELS = {
    "available": "사용 가능",
    "expiring_soon": "만료 예정",
    "expired": "기한 초과",
    "used_up": "소진",
    "blocked": "사용 보류",
    "pending": "매칭 대기",
    "matched": "매칭 완료",
    "partial_matched": "일부 매칭",
    "insufficient_stock": "재고 부족",
    "NO MATCH": "NO MATCH",
    "invalidated": "무효 처리",
    "new": "신규",
    "reactivate": "재활성화",
    "duplicate": "중복",
    "conflict": "확인 필요",
    "error": "오류",
}

UPLOAD_TYPE_LABELS = {
    "imports": "수입 데이터",
    "exports": "수출 요청",
}


def display_status(value: str | None) -> str:
    if not value:
        return ""
    return STATUS_LABELS.get(value, value)


def upload_type_label(value: str | None) -> str:
    if not value:
        return ""
    return UPLOAD_TYPE_LABELS.get(value, value)


def payload_items(value: str | None) -> list[tuple[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [("원문", value)]
    if not isinstance(parsed, dict):
        return [("원문", parsed)]
    return list(parsed.items())


templates.env.filters["display_status"] = display_status
templates.env.filters["upload_type_label"] = upload_type_label
templates.env.filters["payload_items"] = payload_items

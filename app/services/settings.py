from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.services.policy import MATCH_WINDOW_DAYS


ELIGIBILITY_DAYS_KEY = "matching_eligibility_days"


def get_eligibility_days(db: Session) -> int:
    setting = db.get(AppSetting, ELIGIBILITY_DAYS_KEY)
    if setting is None:
        return MATCH_WINDOW_DAYS
    try:
        value = int(setting.value)
    except ValueError:
        return MATCH_WINDOW_DAYS
    return value if value >= 0 else MATCH_WINDOW_DAYS


def set_eligibility_days(db: Session, days: int) -> int:
    if days < 0 or days > 3650:
        raise ValueError("매칭 인정 기간은 0일 이상 3650일 이하여야 합니다.")
    setting = db.get(AppSetting, ELIGIBILITY_DAYS_KEY)
    if setting is None:
        setting = AppSetting(key=ELIGIBILITY_DAYS_KEY, value=str(days))
        db.add(setting)
    else:
        setting.value = str(days)
    db.commit()
    return days

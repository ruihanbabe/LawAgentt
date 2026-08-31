"""法规版本对案件事件日期的确定性半开区间判断。"""

from __future__ import annotations

from datetime import date
from typing import Any


ACCEPTED_VALIDITY_STATUSES = frozenset({"active", "current", "effective", "valid", "现行有效"})


def parse_iso_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def is_law_effective_on(item: dict[str, Any], event_date: date | None) -> bool:
    """只有版本、效力状态和 `[from,to)` 全部支持事件日期时返回 True。"""

    if event_date is None:
        return False
    if not item.get("law_family_id") or not item.get("law_version_id"):
        return False
    if str(item.get("validity_status", "")).lower() not in ACCEPTED_VALIDITY_STATUSES:
        return False
    effective_from = parse_iso_date(item.get("effective_from"))
    effective_to = parse_iso_date(item.get("effective_to"))
    if effective_from is None or event_date < effective_from:
        return False
    return effective_to is None or event_date < effective_to

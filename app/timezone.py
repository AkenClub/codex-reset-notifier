from __future__ import annotations

from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_FALLBACKS: dict[str, tzinfo] = {
    "UTC": timezone.utc,
    "Etc/UTC": timezone.utc,
    "Asia/Shanghai": timezone(timedelta(hours=8), name="CST"),
}


def get_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        fallback = _FALLBACKS.get(name)
        if fallback is not None:
            return fallback
        raise


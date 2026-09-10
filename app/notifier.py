from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .http_client import TransportError, UrlLibClient
from .models import Record
from .rules import Notification
from .timezone import get_timezone


HISTORY_URL = "https://www.codexrunway.com/zh/history.html"
MAX_TEXT_BYTES = 2048
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class NotificationError(RuntimeError):
  """Raised when a WeCom webhook request is not confirmed successful."""


@dataclass(frozen=True)
class MessageChunk:
    content: str
    notifications: tuple[Notification, ...]


def _pick(mapping: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if value is not None and value != "":
            return value
    return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        value = str(value).strip()
        return value or None
    return None


def _parse_datetime(value: Any) -> datetime | date | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = _as_text(value)
    if not text:
        return None
    if _DATE_ONLY.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_time(value: Any, timezone_name: str) -> str:
    if isinstance(value, Mapping):
        start = _pick(value, ("startAt", "start", "from", "date"))
        end = _pick(value, ("endAt", "end", "to"))
        if start is not None and end is not None:
            start_text = _format_time(start, timezone_name)
            end_text = _format_time(end, timezone_name)
            return start_text if start_text == end_text else f"{start_text} - {end_text}"
        if start is not None:
            return _format_time(start, timezone_name)
        if end is not None:
            return _format_time(end, timezone_name)
        return "未公布"
    text = _as_text(value)
    if text and not _DATE_ONLY.fullmatch(text):
        parsed = _parse_datetime(value)
    else:
        parsed = _parse_datetime(value)
    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        return parsed.isoformat()
    if isinstance(parsed, datetime):
        local = parsed.astimezone(get_timezone(timezone_name))
        return local.strftime("%Y-%m-%d %H:%M")
    return text or "未公布"


def _format_date(value: Any, timezone_name: str) -> str:
    if isinstance(value, Mapping):
        start = _pick(value, ("startAt", "start", "from", "date"))
        end = _pick(value, ("endAt", "end", "to"))
        if start is not None and end is not None:
            start_text = _format_date(start, timezone_name)
            end_text = _format_date(end, timezone_name)
            return start_text if start_text == end_text else f"{start_text} 至 {end_text}"
        return _format_date(start if start is not None else end, timezone_name)
    parsed = _parse_datetime(value)
    if isinstance(parsed, datetime):
        return parsed.astimezone(get_timezone(timezone_name)).date().isoformat()
    if isinstance(parsed, date):
        return parsed.isoformat()
    text = _as_text(value)
    return text or "未公布"


def _scheduled_value(record: Record) -> Any:
    raw = record.raw
    direct = _pick(
        raw,
        (
          "effectiveAt",
          "scheduledAt",
          "scheduled_at",
          "scheduleAt",
          "expectedAt",
          "expected_at",
          "resetAt",
          "scheduledFor",
          "scheduledDate",
          "date",
          "timeWindow",
          "window",
        ),
    )
    if direct is not None:
        return direct
    schedule = raw.get("schedule")
    if isinstance(schedule, Mapping):
        return _pick(
            schedule,
            ("scheduledAt", "at", "startAt", "start", "date", "timeWindow", "window"),
        )
    return None


def _display_time(notification: Notification, timezone_name: str) -> str:
    if notification.kind == "completed":
        return _format_time(notification.record.completed_at, timezone_name)
    if notification.record.raw.get("schedulePrecision") == "date":
        return _format_date(notification.record.raw.get("scheduleWindow") or _scheduled_value(notification.record), timezone_name)
    return _format_time(_scheduled_value(notification.record), timezone_name)


def _display_plans(record: Record) -> str:
    raw = record.raw
    value = _pick(
        raw,
        ("plans", "plan", "applicablePlans", "eligiblePlans", "subscriptions", "planNames"),
    )
    scope = raw.get("scope")
    if value is None and isinstance(scope, Mapping):
        value = _pick(scope, ("plans", "plan", "names"))
    values: list[str] = []
    labels = {
      "plus": "Plus",
      "pro": "Pro",
      "team": "Team",
      "business": "Business",
      "enterprise": "Enterprise",
      "all": "全部套餐",
    }
    if isinstance(value, (list, tuple)):
        iterable = value
    else:
        iterable = [value] if value is not None else []
    for item in iterable:
        if isinstance(item, Mapping):
            item = _pick(item, ("name", "label", "plan", "id"))
        item_text = _as_text(item)
        item_text = labels.get(item_text.lower(), item_text) if item_text else None
        if item_text and item_text not in values:
            values.append(item_text)
    return "、".join(values) if values else "未公布"


def _source_url(record: Record) -> str:
    source = record.raw.get("source")
    value = source.get("url") if isinstance(source, Mapping) else None
    value = value or record.raw.get("sourceUrl") or record.raw.get("url")
    value = _as_text(value)
    if value:
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
    return HISTORY_URL


def _title(record: Record, kind: str) -> str:
    reset_type = record.reset_type
    if reset_type == "banked":
        if kind == "scheduled":
            return "⏳ Codex 重置卡发放已安排"
        return "🎟️ Codex 重置卡已发放"
    if reset_type == "global_and_banked":
        if kind == "scheduled":
            return "⏳ Codex 额度重置及重置卡发放已安排"
        return "✅ Codex 额度重置及重置卡发放已完成"
    if kind == "scheduled":
        return "⏳ Codex 额度重置已安排"
    return "✅ Codex 额度重置已完成"


def _confidence_line(record: Record) -> str:
    if record.confidence is not None:
        return f"信号可信度：{record.confidence:.0%}"
    return "确认方式：运营人工确认"


def format_notification(notification: Notification, timezone_name: str) -> str:
    record = notification.record
    label = "预计时间" if notification.kind == "scheduled" else "完成时间"
    lines = [
        _title(record, notification.kind),
      "",
        f"{label}：{_display_time(notification, timezone_name)}",
        f"适用套餐：{_display_plans(record)}",
        f"{_confidence_line(record)}",
      "数据来源：CodexRunway",
    ]
    if notification.kind == "completed" and record.reset_type == "banked":
        lines.extend(["", "请在账号中查看重置卡到账情况。"])
    lines.extend(["", f"查看原公告：{_source_url(record)}"])
    return "\n".join(lines)


def _truncate_utf8(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = "\n（内容已截断）"
    suffix_bytes = len(suffix.encode("utf-8"))
    clipped = encoded[: max(0, limit - suffix_bytes)]
    while True:
        try:
            return clipped.decode("utf-8") + suffix
        except UnicodeDecodeError:
            clipped = clipped[:-1]


def build_message_chunks(
    notifications: Iterable[Notification], timezone_name: str
) -> tuple[MessageChunk, ...]:
    entries = [
        (notification, _truncate_utf8(format_notification(notification, timezone_name), MAX_TEXT_BYTES))
        for notification in notifications
    ]
    chunks: list[MessageChunk] = []
    current_notifications: list[Notification] = []
    current_contents: list[str] = []

    for notification, content in entries:
        candidate = "\n\n".join([*current_contents, content])
        if current_contents and len(candidate.encode("utf-8")) > MAX_TEXT_BYTES:
            chunks.append(
                MessageChunk(
                    content="\n\n".join(current_contents),
                    notifications=tuple(current_notifications),
                )
            )
            current_notifications = []
            current_contents = []
            candidate = content
        current_notifications.append(notification)
        current_contents.append(candidate if not current_contents else content)

    if current_contents:
        chunks.append(
            MessageChunk(
                content="\n\n".join(current_contents),
                notifications=tuple(current_notifications),
            )
        )
    return tuple(chunks)


class WeComNotifier:
    def __init__(
        self,
        webhook_url: str,
        timeout_seconds: float,
        client: Any | None = None,
    ):
        cleaned = webhook_url.strip()
        while cleaned.endswith((",", "，")):
            cleaned = cleaned[:-1].rstrip()
        if not cleaned:
            raise ValueError("WECOM_WEBHOOK_URL cannot be empty")
        self.webhook_url = cleaned
        self.timeout_seconds = timeout_seconds
        self._client = client or UrlLibClient()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def send_text(self, content: str) -> None:
        if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
            raise NotificationError("text message exceeds WeCom's 2048-byte limit")
        try:
            response = self._client.post(
                self.webhook_url,
                json={"msgtype": "text", "text": {"content": content}},
                timeout=self.timeout_seconds,
            )
        except (TransportError, OSError) as exc:
            raise NotificationError(f"WeCom request failed: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise NotificationError(f"WeCom returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise NotificationError("WeCom returned invalid JSON") from exc
        if not isinstance(payload, Mapping) or payload.get("errcode") != 0:
            errcode = payload.get("errcode") if isinstance(payload, Mapping) else "unknown"
            errmsg = payload.get("errmsg") if isinstance(payload, Mapping) else "invalid response"
            raise NotificationError(f"WeCom business error errcode={errcode}: {errmsg}")

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


def _first(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return None


def _string_id(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _id_list(value: Any) -> tuple[str, ...]:
    if value is None or isinstance(value, (str, bytes)):
        item = _string_id(value)
        return (item,) if item else ()
    if not isinstance(value, (list, tuple, set)):
        item = _string_id(value)
        return (item,) if item else ()

    result: list[str] = []
    for entry in value:
        if isinstance(entry, Mapping):
            entry = _first(entry, "id", "recordId", "record_id", "value")
        item = _string_id(entry)
        if item and item not in result:
            result.append(item)
    return tuple(result)


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (int, float)):
        try:
            value = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


@dataclass(frozen=True)
class Record:
    """Normalized view of one CodexRunway record while retaining the raw payload."""

    raw: dict[str, Any]
    record_id: str
    kind: str
    reset_type: str | None
    schedule_state: str | None
    confidence: float | None
    source_origin: str | None
    fulfillment_origin: str | None
    completed_at: Any
    completion_record_id: str | None
    related_record_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "Record":
        if not isinstance(payload, Mapping):
            raise ValueError("record is not an object")
        raw = dict(payload)
        record_id = _string_id(_first(raw, "id", "recordId", "record_id", "uuid"))
        if not record_id:
            raise ValueError("record has no stable id")

        source = raw.get("source")
        source_origin = None
        if isinstance(source, Mapping):
            source_origin = _string_id(_first(source, "origin"))

        kind = _string_id(_first(raw, "kind")) or ""
        schedule_state = _string_id(_first(raw, "scheduleState", "schedule_state"))
        reset_type = _string_id(_first(raw, "resetType", "reset_type"))
        completion_record_id = _string_id(
            _first(raw, "completionRecordId", "completion_record_id")
        )
        related_ids = _id_list(_first(raw, "relatedRecordIds", "related_record_ids"))

        return cls(
            raw=raw,
            record_id=record_id,
            kind=kind.lower(),
            reset_type=reset_type.lower() if reset_type else None,
            schedule_state=schedule_state.lower() if schedule_state else None,
            confidence=_confidence(_first(raw, "confidence")),
            source_origin=source_origin.lower() if source_origin else None,
            fulfillment_origin=(
                _string_id(_first(raw, "fulfillmentOrigin", "fulfillment_origin")) or ""
            ).lower()
            or None,
            completed_at=_first(raw, "completedAt", "completed_at"),
            completion_record_id=completion_record_id,
            related_record_ids=related_ids,
        )


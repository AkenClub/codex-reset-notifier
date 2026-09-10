from __future__ import annotations

from typing import Any


def record(
    record_id: str,
    *,
    kind: str = "reset_scheduled",
    reset_type: str = "global",
    schedule_state: str | None = "pending",
    confidence: Any = 0.96,
    completion_record_id: str | None = None,
    related_record_ids: list[str] | None = None,
    completed_at: Any = None,
    source_origin: str | None = None,
    fulfillment_origin: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": record_id,
        "kind": kind,
        "resetType": reset_type,
        "scheduleState": schedule_state,
        "confidence": confidence,
        "source": {"origin": source_origin or "signal", "url": "https://example.com/event"},
        "fulfillmentOrigin": fulfillment_origin,
        "completedAt": completed_at,
        "relatedRecordIds": related_record_ids or [],
        "plans": ["Plus", "Pro", "Business"],
        "scheduledAt": "2026-09-09T02:00:00Z",
    }
    if completion_record_id is not None:
        payload["completionRecordId"] = completion_record_id
    payload.update(extra)
    return payload


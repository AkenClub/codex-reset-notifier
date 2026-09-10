from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Record
from .state import State


@dataclass(frozen=True)
class Notification:
    key: str
    kind: str
    record: Record
    schedule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssociationIndex:
    schedule_to_completion: dict[str, set[str]]
    completion_to_schedule: dict[str, set[str]]

    def completion_ids_for_schedule(self, schedule_id: str) -> set[str]:
        return set(self.schedule_to_completion.get(schedule_id, set()))

    def schedule_ids_for_completion(self, completion_id: str) -> set[str]:
        return set(self.completion_to_schedule.get(completion_id, set()))


@dataclass(frozen=True)
class Evaluation:
    notifications: tuple[Notification, ...]
    skipped: tuple[str, ...]


def build_association_index(records: Iterable[Record]) -> AssociationIndex:
    schedule_to_completion: dict[str, set[str]] = {}
    completion_to_schedule: dict[str, set[str]] = {}

    for record in records:
        if record.kind == "reset_scheduled" and record.completion_record_id:
            schedule_to_completion.setdefault(record.record_id, set()).add(
                record.completion_record_id
            )
            completion_to_schedule.setdefault(record.completion_record_id, set()).add(
                record.record_id
            )
        if record.kind == "reset_completed":
            related = completion_to_schedule.setdefault(record.record_id, set())
            related.update(record.related_record_ids)
            for schedule_id in record.related_record_ids:
                schedule_to_completion.setdefault(schedule_id, set()).add(record.record_id)

    return AssociationIndex(schedule_to_completion, completion_to_schedule)


def is_trusted(record: Record, threshold: float) -> bool:
    if record.confidence is not None and record.confidence >= threshold:
        return True
    return (
        record.kind == "reset_completed"
        and record.source_origin == "operator"
        and record.fulfillment_origin == "manual"
        and bool(record.completed_at)
    )


def _sent_completion_keys(state: State) -> set[str]:
    return {key for key in state.sent if key.startswith("completed:")}


def evaluate(records: Iterable[Record], state: State, threshold: float) -> Evaluation:
    records = tuple(records)
    index = build_association_index(records)
    notifications: list[Notification] = []
    skipped: list[str] = []
    seen_keys: set[str] = set()
    current_completed_schedule_ids: set[str] = set()
    current_completion_keys: set[str] = set()
    sent_completion_keys = _sent_completion_keys(state)

    # Completion records win over fulfilled schedule records in the same response.
    for record in records:
        if record.kind != "reset_completed":
            continue
        if not is_trusted(record, threshold):
            skipped.append(f"{record.record_id}: low-confidence completion")
            continue

        schedule_ids = set(index.schedule_ids_for_completion(record.record_id))
        schedule_ids.update(record.related_record_ids)
        if schedule_ids & state.completed_schedule_ids:
            skipped.append(f"{record.record_id}: completion already represented by a schedule")
            continue

        key = f"completed:{record.record_id}"
        if key in state.sent or key in seen_keys:
            skipped.append(f"{record.record_id}: completion already sent")
            continue
        if schedule_ids & current_completed_schedule_ids:
            skipped.append(f"{record.record_id}: duplicate completion association")
            continue

        notification = Notification(
            key=key,
            kind="completed",
            record=record,
            schedule_ids=tuple(sorted(schedule_ids)),
        )
        notifications.append(notification)
        seen_keys.add(key)
        current_completion_keys.add(key)
        current_completed_schedule_ids.update(schedule_ids)

    for record in records:
        if record.kind != "reset_scheduled":
            continue
        state_name = record.schedule_state
        completion_ids = index.completion_ids_for_schedule(record.record_id)
        if record.completion_record_id:
            completion_ids.add(record.completion_record_id)
        associated_schedule_ids = {record.record_id}

        if not is_trusted(record, threshold):
            skipped.append(f"{record.record_id}: low-confidence schedule")
            continue
        if record.record_id in state.completed_schedule_ids:
            skipped.append(f"{record.record_id}: schedule already completed")
            continue
        if any(f"completed:{completion_id}" in sent_completion_keys for completion_id in completion_ids):
            skipped.append(f"{record.record_id}: linked completion already sent")
            continue
        if any(f"completed:{completion_id}" in current_completion_keys for completion_id in completion_ids):
            skipped.append(f"{record.record_id}: linked completion returned in same response")
            continue

        if state_name == "pending":
            key = f"scheduled:{record.record_id}"
            if key in state.sent or key in seen_keys:
                skipped.append(f"{record.record_id}: schedule already sent")
                continue
            notifications.append(
                Notification(key=key, kind="scheduled", record=record, schedule_ids=())
            )
            seen_keys.add(key)
        elif state_name == "fulfilled":
            if completion_ids:
                completion_id = sorted(completion_ids)[0]
                key = f"completed:{completion_id}"
            else:
                key = f"fulfilled-schedule:{record.record_id}"
            if key in state.sent or key in seen_keys:
                skipped.append(f"{record.record_id}: fulfilled completion already sent")
                continue
            notifications.append(
                Notification(
                    key=key,
                    kind="completed",
                    record=record,
                    schedule_ids=tuple(sorted(associated_schedule_ids)),
                )
            )
            seen_keys.add(key)
        else:
            skipped.append(f"{record.record_id}: schedule state is {state_name or 'unknown'}")

    return Evaluation(tuple(notifications), tuple(skipped))


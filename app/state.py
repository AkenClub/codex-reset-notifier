from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


STATE_VERSION = 1


class StateError(RuntimeError):
    """Raised when the state cannot be safely read or persisted."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class State:
    sent: dict[str, dict[str, str]] = field(default_factory=dict)
    completed_schedule_ids: set[str] = field(default_factory=set)

    def is_sent(self, key: str) -> bool:
        return key in self.sent

    def mark_sent(self, key: str, schedule_ids: tuple[str, ...] = ()) -> None:
        self.sent[key] = {"sentAt": utc_now_iso()}
        self.completed_schedule_ids.update(schedule_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "sent": {key: self.sent[key] for key in sorted(self.sent)},
            "completedScheduleIds": sorted(self.completed_schedule_ids),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "State":
        if not isinstance(payload, Mapping):
            raise StateError("state root must be an object")
        if payload.get("version") != STATE_VERSION:
            raise StateError("unsupported state version")

        sent_payload = payload.get("sent")
        if not isinstance(sent_payload, Mapping):
            raise StateError("state.sent must be an object")
        sent: dict[str, dict[str, str]] = {}
        for key, value in sent_payload.items():
            if not isinstance(key, str) or not key:
                raise StateError("state.sent contains an invalid key")
            if not isinstance(value, Mapping) or not isinstance(value.get("sentAt"), str):
                raise StateError(f"state.sent[{key!r}] is invalid")
            sent[key] = {"sentAt": value["sentAt"]}

        schedule_ids = payload.get("completedScheduleIds", [])
        if not isinstance(schedule_ids, list) or any(
            not isinstance(item, str) or not item for item in schedule_ids
        ):
            raise StateError("state.completedScheduleIds must be a list of non-empty strings")
        return cls(sent=sent, completed_schedule_ids=set(schedule_ids))


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> State:
        if not self.path.exists():
            return State()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"cannot read state file {self.path}: {exc}") from exc
        return State.from_mapping(payload)

    def save(self, state: State) -> None:
        parent = self.path.parent
        temporary_path: str | None = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=parent
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(state.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise StateError(f"cannot atomically save state file {self.path}: {exc}") from exc
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass


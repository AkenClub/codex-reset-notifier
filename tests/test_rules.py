from __future__ import annotations

import unittest

from app.models import Record
from app.rules import evaluate
from app.state import State

from helpers import record


def normalized(*payloads: dict) -> tuple[Record, ...]:
    return tuple(Record.from_mapping(payload) for payload in payloads)


class RulesTests(unittest.TestCase):
    def test_high_confidence_pending_schedule_is_notified_once(self) -> None:
        records = normalized(record("schedule-1"))
        first = evaluate(records, State(), 0.90)
        self.assertEqual([item.key for item in first.notifications], ["scheduled:schedule-1"])

        state = State()
        state.mark_sent(first.notifications[0].key)
        second = evaluate(records, state, 0.90)
        self.assertEqual(second.notifications, ())

    def test_low_confidence_record_is_skipped(self) -> None:
        result = evaluate(normalized(record("low", confidence=0.89)), State(), 0.90)
        self.assertEqual(result.notifications, ())
        self.assertIn("low-confidence", result.skipped[0])

    def test_manual_completion_without_confidence_is_accepted(self) -> None:
        payload = record(
            "completion-1",
            kind="reset_completed",
            schedule_state=None,
            confidence=None,
            completed_at="2026-09-09T02:05:00Z",
            source_origin="operator",
            fulfillment_origin="manual",
        )
        result = evaluate(normalized(payload), State(), 0.90)
        self.assertEqual([item.key for item in result.notifications], ["completed:completion-1"])

    def test_completion_record_wins_over_fulfilled_schedule(self) -> None:
        schedule = record(
            "schedule-1",
            schedule_state="fulfilled",
            completion_record_id="completion-1",
            confidence=0.96,
        )
        completion = record(
            "completion-1",
            kind="reset_completed",
            schedule_state=None,
            related_record_ids=["schedule-1"],
            completed_at="2026-09-09T02:05:00Z",
            confidence=0.98,
        )
        result = evaluate(normalized(schedule, completion), State(), 0.90)
        self.assertEqual([item.key for item in result.notifications], ["completed:completion-1"])

    def test_multiple_schedules_with_same_completion_are_deduplicated(self) -> None:
        schedules = normalized(
            record("schedule-a", schedule_state="fulfilled", completion_record_id="completion-1"),
            record("schedule-b", schedule_state="fulfilled", completion_record_id="completion-1"),
        )
        result = evaluate(schedules, State(), 0.90)
        self.assertEqual([item.key for item in result.notifications], ["completed:completion-1"])
        self.assertEqual(result.notifications[0].schedule_ids, ("schedule-a",))

    def test_completed_schedule_suppresses_late_completion_record(self) -> None:
        state = State()
        state.mark_sent("completed:completion-1", ("schedule-1",))
        completion = record(
            "completion-1",
            kind="reset_completed",
            schedule_state=None,
            related_record_ids=["schedule-1"],
            completed_at="2026-09-09T02:05:00Z",
            confidence=0.98,
        )
        result = evaluate(normalized(completion), state, 0.90)
        self.assertEqual(result.notifications, ())

    def test_meta_only_change_does_not_change_dedupe_key(self) -> None:
        first = evaluate(normalized(record("schedule-1")), State(), 0.90)
        changed = record("schedule-1", meta={"generatedAt": "2026-09-10T00:00:00Z"})
        state = State()
        state.mark_sent(first.notifications[0].key)
        result = evaluate(normalized(changed), state, 0.90)
        self.assertEqual(result.notifications, ())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.state import State, StateError, StateStore


class StateTests(unittest.TestCase):
    def test_round_trip_and_atomic_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "state.json"
            store = StateStore(path)
            state = State()
            state.mark_sent("completed:event-1", ("schedule-1",))
            store.save(state)

            loaded = store.load()
            self.assertTrue(loaded.is_sent("completed:event-1"))
            self.assertEqual(loaded.completed_schedule_ids, {"schedule-1"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_corrupt_state_stops_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(StateError):
                StateStore(path).load()

    def test_invalid_schema_is_not_treated_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"version": 1, "sent": []}), encoding="utf-8")
            with self.assertRaises(StateError):
                StateStore(path).load()


if __name__ == "__main__":
    unittest.main()


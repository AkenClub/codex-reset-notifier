from __future__ import annotations

import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from app.config import Settings
from app.main import FatalServiceError, NotificationService, run_service
from app.notifier import NotificationError
from app.state import StateStore

from helpers import record


class FakeApi:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = 0

    def fetch_records(self):
        self.calls += 1
        return self.payloads


class FakeNotifier:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.messages: list[str] = []

    def send_text(self, content: str) -> None:
        if self.fail:
            raise NotificationError("simulated failure")
        self.messages.append(content)


def settings(path: Path, dry_run: bool = False) -> Settings:
    return Settings(
        webhook_url="https://example.com/hook",
        state_file=path,
        dry_run=dry_run,
    )


class ServiceTests(unittest.TestCase):
    def test_env_switch_controls_request_and_sent_body(self) -> None:
        for enabled in (True, False):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                cfg = Settings.from_env({
                    "WECOM_WEBHOOK_URL": "https://example.com/hook",
                    "STATE_FILE": str(Path(directory) / "state.json"),
                    "INCLUDE_TWEET_TRANSLATION": str(enabled).lower(),
                })
                api_http = Mock()
                api_http.get.return_value = Mock(
                    status_code=200, headers={},
                    json=Mock(return_value={"data": {"items": [record(
                        "translated", text="Original announcement.", translatedText="已完成重置。",
                    )]}}),
                )
                webhook_http = Mock()
                webhook_http.post.return_value = Mock(
                    status_code=200, json=Mock(return_value={"errcode": 0}),
                )
                with patch("app.api.UrlLibClient", return_value=api_http), patch(
                    "app.notifier.UrlLibClient", return_value=webhook_http
                ):
                    self.assertEqual(run_service(cfg, once=True), 0)
                params = api_http.get.call_args.kwargs["params"]
                content = webhook_http.post.call_args.kwargs["json"]["text"]["content"]
                self.assertEqual(params.get("lang"), "zh-CN" if enabled else None)
                self.assertEqual("已完成重置。" in content, enabled)
                self.assertNotIn("Original announcement.", content)
                self.assertIn("查看原公告：https://example.com/event", content)
                self.assertTrue(StateStore(cfg.state_file).load().is_sent("scheduled:translated"))

    def test_success_persists_and_next_poll_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            api = FakeApi([record("schedule-1")])
            notifier = FakeNotifier()
            service = NotificationService(
                settings(path), api, notifier, StateStore(path)
            )
            first = service.run_once()
            second = service.run_once()
            self.assertEqual(first.status, "sent")
            self.assertEqual(second.status, "no_notifications")
            self.assertEqual(len(notifier.messages), 1)
            self.assertTrue(StateStore(path).load().is_sent("scheduled:schedule-1"))

    def test_failed_send_does_not_mark_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            api = FakeApi([record("schedule-1")])
            notifier = FakeNotifier(fail=True)
            service = NotificationService(
                settings(path), api, notifier, StateStore(path)
            )
            result = service.run_once()
            self.assertEqual(result.status, "notification_error")
            self.assertFalse(path.exists())
            self.assertFalse(service.state.is_sent("scheduled:schedule-1"))

    def test_dry_run_never_sends_or_writes_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            api = FakeApi([record("schedule-1")])
            notifier = FakeNotifier()
            service = NotificationService(
                settings(path, dry_run=True), api, notifier, StateStore(path)
            )
            result = service.run_once()
            self.assertEqual(result.status, "dry_run")
            self.assertEqual(notifier.messages, [])
            self.assertFalse(path.exists())

    def test_corrupt_state_is_not_allowed_to_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(Exception):
                NotificationService(
                    settings(path), FakeApi([]), FakeNotifier(), StateStore(path)
                )

    def test_state_save_failure_stops_after_successful_webhook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(path)

            def fail_save(_state):
                from app.state import StateError

                raise StateError("disk full")

            store.save = fail_save
            notifier = FakeNotifier()
            service = NotificationService(
                settings(path), FakeApi([record("schedule-1")]), notifier, store
            )
            with self.assertRaises(FatalServiceError):
                service.run_once()
            self.assertEqual(len(notifier.messages), 1)


if __name__ == "__main__":
    unittest.main()

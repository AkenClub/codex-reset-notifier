from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.models import Record
from app.notifier import (
    MAX_TEXT_BYTES,
    NotificationError,
    WeComNotifier,
    build_message_chunks,
    format_notification,
)
from app.rules import Notification

from helpers import record


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"errcode": 0, "errmsg": "ok"}

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


class NotifierTests(unittest.TestCase):
    def test_formatting_converts_time_and_uses_manual_confirmation(self) -> None:
        parsed = Record.from_mapping(
            record(
                "completion-1",
                kind="reset_completed",
                schedule_state=None,
                confidence=None,
                completed_at="2026-09-09T02:05:00Z",
                source_origin="operator",
                fulfillment_origin="manual",
            )
        )
        notification = Notification("completed:completion-1", "completed", parsed)
        content = format_notification(notification, "Asia/Shanghai")
        self.assertIn("完成时间：2026-09-09 10:05", content)
        self.assertIn("确认方式：运营人工确认", content)
        self.assertNotIn("信号可信度：100%", content)
        self.assertNotIn("**", content)
        self.assertNotIn("[查看原公告]", content)
        self.assertIn("查看原公告：https://example.com/event", content)

    def test_translation_is_preferred_over_original(self) -> None:
        parsed = Record.from_mapping(record(
            "translated", text="Original announcement.",
            translatedText="  已完成重置。\n请查看账户。  ",
        ))
        content = format_notification(
            Notification("scheduled:translated", "scheduled", parsed), "Asia/Shanghai"
        )
        self.assertIn("公告译文：\n已完成重置。\n请查看账户。", content)
        self.assertNotIn("Original announcement.", content)
        self.assertIn("查看原公告：https://example.com/event", content)

    def test_missing_translation_falls_back_to_original(self) -> None:
        for translated in (None, "", "  ", {"invalid": "value"}):
            with self.subTest(translated=translated):
                parsed = Record.from_mapping(record(
                    "fallback", text="  Original announcement.  ", translatedText=translated,
                ))
                content = format_notification(
                    Notification("scheduled:fallback", "scheduled", parsed), "Asia/Shanghai"
                )
                self.assertIn("公告原文（暂无译文）：\nOriginal announcement.", content)
                self.assertNotIn("公告译文：", content)

    def test_absent_body_does_not_add_empty_section(self) -> None:
        parsed = Record.from_mapping(record("empty", text=None, translatedText=None))
        content = format_notification(
            Notification("scheduled:empty", "scheduled", parsed), "Asia/Shanghai"
        )
        self.assertNotIn("公告译文：", content)
        self.assertNotIn("公告原文", content)

    def test_disabled_translation_hides_both_bodies_in_chunks(self) -> None:
        parsed = Record.from_mapping(record(
            "disabled", text="Original announcement.", translatedText="已完成重置。",
        ))
        chunks = build_message_chunks(
            [Notification("scheduled:disabled", "scheduled", parsed)], "Asia/Shanghai",
            include_tweet_translation=False,
        )
        self.assertEqual(len(chunks), 1)
        self.assertNotIn("已完成重置。", chunks[0].content)
        self.assertNotIn("Original announcement.", chunks[0].content)
        self.assertIn("查看原公告：https://example.com/event", chunks[0].content)

    def test_long_translation_keeps_source_and_respects_byte_limit(self) -> None:
        parsed = Record.from_mapping(record("long-translation", translatedText="译文" * 2000))
        notification = Notification("scheduled:long-translation", "scheduled", parsed)
        chunks = build_message_chunks([notification], "Asia/Shanghai")
        self.assertEqual(len(chunks), 1)
        self.assertLessEqual(len(chunks[0].content.encode("utf-8")), MAX_TEXT_BYTES)
        self.assertIn("查看原公告：https://example.com/event", chunks[0].content)
        self.assertTrue(chunks[0].content.endswith("（内容已截断）"))
        self.assertEqual(chunks[0].notifications, (notification,))

    def test_banked_title_and_trailing_chinese_comma(self) -> None:
        parsed = Record.from_mapping(
            record(
                "completion-1",
                kind="reset_completed",
                reset_type="banked",
                schedule_state=None,
                completed_at="2026-09-09T02:05:00Z",
            )
        )
        notification = Notification("completed:completion-1", "completed", parsed)
        content = format_notification(notification, "Asia/Shanghai")
        self.assertIn("🎟️ Codex 重置卡已发放", content)

        client = FakeHttpClient(FakeResponse())
        notifier = WeComNotifier("https://example.com/hook?key=x，", 5, client=client)
        notifier.send_text(content)
        self.assertEqual(client.calls[0]["url"], "https://example.com/hook?key=x")
        self.assertEqual(client.calls[0]["json"], {"msgtype": "text", "text": {"content": content}})

    def test_text_byte_boundary(self) -> None:
        client = FakeHttpClient(FakeResponse())
        notifier = WeComNotifier("https://example.com/hook", 5, client=client)
        notifier.send_text("中" * 682 + "ab")
        with self.assertRaises(NotificationError):
            notifier.send_text("中" * 683)
        self.assertEqual(len(client.calls), 1)

    def test_business_error_is_not_success(self) -> None:
        client = FakeHttpClient(FakeResponse(payload={"errcode": 93000, "errmsg": "bad key"}))
        notifier = WeComNotifier("https://example.com/hook", 5, client=client)
        with self.assertRaises(NotificationError):
            notifier.send_text("hello")

    def test_message_chunks_respect_byte_limit(self) -> None:
        notifications = []
        for index in range(20):
            parsed = Record.from_mapping(
                record(
                    f"event-{index}",
                    source={"url": "https://example.com"},
                    plans=["Plus", "Pro", "Business"],
                )
            )
            notifications.append(Notification(f"scheduled:event-{index}", "scheduled", parsed))
        chunks = build_message_chunks(notifications, "Asia/Shanghai")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.content.encode("utf-8")) <= MAX_TEXT_BYTES for chunk in chunks))
        self.assertEqual([n.key for chunk in chunks for n in chunk.notifications], [n.key for n in notifications])

    def test_oversized_event_is_truncated_as_valid_utf8(self) -> None:
        parsed = Record.from_mapping(record("long", plans=["中" * 3000]))
        chunks = build_message_chunks([Notification("scheduled:long", "scheduled", parsed)], "Asia/Shanghai")
        self.assertEqual(len(chunks), 1)
        self.assertLessEqual(len(chunks[0].content.encode("utf-8")), 2048)
        self.assertTrue(chunks[0].content.endswith("（内容已截断）"))

    def test_real_scope_and_date_precision_are_formatted_safely(self) -> None:
        parsed = Record.from_mapping(
            record(
                "schedule-date",
                schedule_state="pending",
                confidence=0.96,
                scope={"plans": ["plus", "pro", "business"]},
                effectiveAt="2026-08-30T07:00:00Z",
                schedulePrecision="date",
                scheduleWindow={
                    "startAt": "2026-08-30T07:00:00Z",
                    "endAt": "2026-08-31T07:00:00Z",
                },
            )
        )
        notification = Notification("scheduled:schedule-date", "scheduled", parsed)
        content = format_notification(notification, "Asia/Shanghai")
        self.assertIn("预计时间：2026-08-30 至 2026-08-31", content)
        self.assertIn("适用套餐：Plus、Pro、Business", content)
        self.assertNotIn("15:00", content)


if __name__ == "__main__":
    unittest.main()

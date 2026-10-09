from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from typing import Any

from .api import ApiClient, ApiError, RateLimitError
from .config import ConfigError, Settings
from .models import Record
from .notifier import MessageChunk, NotificationError, WeComNotifier, build_message_chunks
from .rules import Evaluation, Notification, evaluate
from .state import StateError, StateStore


LOGGER = logging.getLogger("codex_reset_notifier")


class FatalServiceError(RuntimeError):
    """Raised when continuing could lose the deduplication guarantee."""


@dataclass(frozen=True)
class CycleResult:
    status: str
    notifications: tuple[Notification, ...] = ()
    sent: tuple[Notification, ...] = ()
    retry_after: float | None = None


class NotificationService:
    def __init__(
        self,
        settings: Settings,
        api_client: Any,
        notifier: Any | None,
        state_store: StateStore,
        logger: logging.Logger | None = None,
    ):
        self.settings = settings
        self.api_client = api_client
        self.notifier = notifier
        self.state_store = state_store
        self.logger = logger or LOGGER
        self.state = state_store.load()

    def _load_records(self, payloads: list[dict[str, Any]]) -> tuple[Record, ...]:
        records: list[Record] = []
        for payload in payloads:
            try:
                records.append(Record.from_mapping(payload))
            except ValueError as exc:
                self.logger.warning("skipping malformed record: %s", exc)
        return tuple(records)

    def _log_evaluation(self, evaluation: Evaluation) -> None:
        for reason in evaluation.skipped:
            self.logger.info("skipped event: %s", reason)
        self.logger.info(
            "evaluation complete: candidates=%d skipped=%d",
            len(evaluation.notifications),
            len(evaluation.skipped),
        )

    def _preview(self, chunks: tuple[MessageChunk, ...]) -> None:
        for index, chunk in enumerate(chunks, start=1):
            self.logger.info("DRY_RUN preview %d/%d:\n%s", index, len(chunks), chunk.content)

    def run_once(self) -> CycleResult:
        try:
            payloads = self.api_client.fetch_records()
        except RateLimitError as exc:
            self.logger.warning("API rate limited; skipping round: %s", exc)
            return CycleResult(status="rate_limited", retry_after=exc.retry_after)
        except ApiError as exc:
            self.logger.error("API check failed; skipping round: %s", exc)
            return CycleResult(status="api_error")

        records = self._load_records(payloads)
        evaluation = evaluate(records, self.state, self.settings.confidence_threshold)
        self._log_evaluation(evaluation)
        if not evaluation.notifications:
            return CycleResult(status="no_notifications")

        chunks = build_message_chunks(
            evaluation.notifications,
            self.settings.display_timezone,
            include_tweet_translation=self.settings.include_tweet_translation,
        )
        if self.settings.dry_run:
            self._preview(chunks)
            return CycleResult(status="dry_run", notifications=evaluation.notifications)
        if self.notifier is None:
            raise FatalServiceError("notifier is required when DRY_RUN=false")

        sent: list[Notification] = []
        for chunk in chunks:
            try:
                self.notifier.send_text(chunk.content)
            except NotificationError as exc:
                self.logger.error("WeCom send failed; events remain eligible: %s", exc)
                return CycleResult(
                    status="notification_error",
                    notifications=evaluation.notifications,
                    sent=tuple(sent),
                )

            for notification in chunk.notifications:
                self.state.mark_sent(notification.key, notification.schedule_ids)
                sent.append(notification)
            try:
                self.state_store.save(self.state)
            except StateError as exc:
                self.logger.critical("state save failed; stopping before more sends: %s", exc)
                raise FatalServiceError(str(exc)) from exc

        self.logger.info("sent %d notification(s) in %d message(s)", len(sent), len(chunks))
        return CycleResult(
            status="sent",
            notifications=evaluation.notifications,
            sent=tuple(sent),
        )


def run_service(settings: Settings, once: bool = False) -> int:
    state_store = StateStore(settings.state_file)
    api_client = ApiClient(
        settings.api_url,
        settings.http_timeout_seconds,
        include_tweet_translation=settings.include_tweet_translation,
    )
    notifier = (
        None
        if settings.dry_run
        else WeComNotifier(settings.webhook_url, settings.http_timeout_seconds)
    )
    try:
        service = NotificationService(settings, api_client, notifier, state_store)
        if once:
            service.run_once()
            return 0

        while True:
            result = service.run_once()
            wait_seconds = settings.poll_interval_seconds
            if result.retry_after is not None:
                wait_seconds = max(wait_seconds, result.retry_after)
            LOGGER.info("next check in %s seconds", wait_seconds)
            time.sleep(wait_seconds)
    except KeyboardInterrupt:
        LOGGER.info("shutdown requested")
        return 0
    except (ConfigError, StateError, FatalServiceError) as exc:
        LOGGER.critical("service stopped: %s", exc)
        return 1
    finally:
        api_client.close()
        if notifier is not None:
            notifier.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Notify WeCom about CodexRunway reset events")
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one check and exit; useful for validation and dry-run previews",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        LOGGER.critical("invalid configuration: %s", exc)
        return 2
    return run_service(settings, once=build_parser().parse_args(argv).once)


if __name__ == "__main__":
    raise SystemExit(main())


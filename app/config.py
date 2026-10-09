from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from dotenv import dotenv_values

from .timezone import get_timezone


DEFAULT_API_URL = "https://www.codexrunway.com/openapi/v1/records"


class ConfigError(ValueError):
    """Raised when an environment variable cannot be used safely."""


def _get(environ: dict[str, str], name: str, default: str) -> str:
    value = environ.get(name, default)
    return value.strip() if isinstance(value, str) else str(value)


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean value")


def _parse_int(value: str, name: str, minimum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return parsed


def _parse_float(value: str, name: str, minimum: float, maximum: float | None = None) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        if maximum is None:
            raise ConfigError(f"{name} must be >= {minimum}")
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


@dataclass(frozen=True)
class Settings:
    webhook_url: str
    poll_interval_seconds: int = 900
    confidence_threshold: float = 0.90
    display_timezone: str = "Asia/Shanghai"
    state_file: Path = Path("/app/data/state.json")
    http_timeout_seconds: float = 15.0
    dry_run: bool = False
    api_url: str = DEFAULT_API_URL
    include_tweet_translation: bool = True

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        if environ is None:
            env_file = Path(__file__).resolve().parent.parent / ".env"
            values = {
                key: value
                for key, value in dotenv_values(
                    env_file, encoding="utf-8-sig", interpolate=False
                ).items()
                if value is not None
            }
            values.update(os.environ)
        else:
            values = dict(environ)
        dry_run = _parse_bool(_get(values, "DRY_RUN", "false"), "DRY_RUN")
        webhook_url = _get(values, "WECOM_WEBHOOK_URL", "")
        if not dry_run and not webhook_url:
            raise ConfigError("WECOM_WEBHOOK_URL is required unless DRY_RUN=true")

        display_timezone = _get(values, "DISPLAY_TIMEZONE", "Asia/Shanghai")
        try:
            get_timezone(display_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"DISPLAY_TIMEZONE is not available: {display_timezone}") from exc

        return cls(
            webhook_url=webhook_url,
            poll_interval_seconds=_parse_int(
                _get(values, "POLL_INTERVAL_SECONDS", "900"),
                "POLL_INTERVAL_SECONDS",
                1,
            ),
            confidence_threshold=_parse_float(
                _get(values, "CONFIDENCE_THRESHOLD", "0.90"),
                "CONFIDENCE_THRESHOLD",
                0.0,
                1.0,
            ),
            display_timezone=display_timezone,
            state_file=Path(_get(values, "STATE_FILE", "/app/data/state.json")),
            http_timeout_seconds=_parse_float(
                _get(values, "HTTP_TIMEOUT_SECONDS", "15"),
                "HTTP_TIMEOUT_SECONDS",
                0.1,
            ),
            dry_run=dry_run,
            api_url=_get(values, "CODEXRUNWAY_API_URL", DEFAULT_API_URL),
            include_tweet_translation=_parse_bool(
                _get(values, "INCLUDE_TWEET_TRANSLATION", "true"),
                "INCLUDE_TWEET_TRANSLATION",
            ),
        )

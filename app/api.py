from __future__ import annotations

from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Mapping

from .http_client import TransportError, UrlLibClient


class ApiError(RuntimeError):
    """Raised for a failed or malformed CodexRunway response."""


class RateLimitError(ApiError):
    def __init__(self, retry_after: float | None):
        self.retry_after = retry_after
        suffix = f"; retry after {retry_after:g}s" if retry_after is not None else ""
        super().__init__(f"CodexRunway API returned HTTP 429{suffix}")


def _header(headers: Any, name: str) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class ApiClient:
    def __init__(
        self,
        url: str,
        timeout_seconds: float,
        client: Any | None = None,
        *,
        include_tweet_translation: bool = True,
    ):
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.include_tweet_translation = include_tweet_translation
        self._client = client or UrlLibClient()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_records(self) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"kind": "all", "page": 1, "pageSize": 10}
        if self.include_tweet_translation:
            params["lang"] = "zh-CN"
        try:
            response = self._client.get(
                self.url,
                params=params,
                timeout=self.timeout_seconds,
            )
        except (TransportError, OSError) as exc:
            raise ApiError(f"CodexRunway request failed: {exc}") from exc

        if response.status_code == 429:
            raise RateLimitError(parse_retry_after(_header(response.headers, "Retry-After")))
        if response.status_code < 200 or response.status_code >= 300:
            raise ApiError(f"CodexRunway API returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise ApiError("CodexRunway API returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ApiError("CodexRunway API response must be an object")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise ApiError("CodexRunway API response has no data object")
        items = data.get("items")
        if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
            raise ApiError("CodexRunway API response data.items must be a list of objects")
        return [dict(item) for item in items]

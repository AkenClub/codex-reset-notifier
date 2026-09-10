from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class TransportError(OSError):
    """Raised when the standard-library HTTP transport cannot connect."""


@dataclass
class Response:
    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _with_query(url: str, params: Mapping[str, Any]) -> str:
    parts = urlsplit(url)
    existing = parts.query
    appended = urlencode(params)
    query = f"{existing}&{appended}" if existing and appended else existing or appended
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


class UrlLibClient:
    """Small injectable HTTP client with the interface used by the service."""

    def get(self, url: str, *, params: Mapping[str, Any], timeout: float) -> Response:
        return self._request("GET", _with_query(url, params), None, timeout)

    def post(self, url: str, *, json: Mapping[str, Any], timeout: float) -> Response:
        return self._request("POST", url, json, timeout)

    def close(self) -> None:
        return None

    @staticmethod
    def _request(
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> Response:
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "CodexResetNotifier/1.0 (+https://www.codexrunway.com/zh/history.html)",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                return Response(
                    status_code=response.status,
                    headers={key: value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except HTTPError as exc:
            return Response(
                status_code=exc.code,
                headers={key: value for key, value in exc.headers.items()},
                body=exc.read(),
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc

from __future__ import annotations

import unittest

from app.api import ApiClient, ApiError, RateLimitError, parse_retry_after


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ApiTests(unittest.TestCase):
    def test_fetches_first_page_of_records(self) -> None:
        client = FakeClient(FakeResponse(200, {"data": {"items": [{"id": "1"}]}}))
        api = ApiClient("https://example.com/records", 15, client=client)
        self.assertEqual(api.fetch_records(), [{"id": "1"}])
        self.assertEqual(
            client.calls[0][1]["params"], {"kind": "all", "page": 1, "pageSize": 10}
        )

    def test_429_exposes_retry_after(self) -> None:
        client = FakeClient(FakeResponse(429, {}, {"Retry-After": "3600"}))
        api = ApiClient("https://example.com/records", 15, client=client)
        with self.assertRaises(RateLimitError) as context:
            api.fetch_records()
        self.assertEqual(context.exception.retry_after, 3600)

    def test_malformed_response_is_an_error(self) -> None:
        client = FakeClient(FakeResponse(200, {"data": {"items": "bad"}}))
        api = ApiClient("https://example.com/records", 15, client=client)
        with self.assertRaises(ApiError):
            api.fetch_records()

    def test_parse_retry_after_invalid_value(self) -> None:
        self.assertIsNone(parse_retry_after("not-a-duration"))


if __name__ == "__main__":
    unittest.main()


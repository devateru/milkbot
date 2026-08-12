from __future__ import annotations

import aiohttp
import unittest

from maishift.client import FetchStatus, MaishiftClient


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self.status = status
        self.body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def read(self) -> bytes:
        return self.body


class FakeSession:
    closed = False

    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.request_headers = None

    def get(self, url, *, headers, allow_redirects):
        self.request_headers = headers
        if self.error:
            raise self.error
        return self.response


class MaishiftClientTests(unittest.IsolatedAsyncioTestCase):
    async def fetch_with(self, response=None, error=None, **kwargs):
        client = MaishiftClient()
        fake = FakeSession(response, error)
        client._session = fake
        result = await client.fetch("sample", **kwargs)
        return result, fake

    async def test_http_errors_are_classified(self) -> None:
        rate_limited, _ = await self.fetch_with(FakeResponse(429, headers={"Retry-After": "120"}))
        server_error, _ = await self.fetch_with(FakeResponse(503))
        missing, _ = await self.fetch_with(FakeResponse(404))
        self.assertEqual(rate_limited.status, FetchStatus.TEMPORARY_ERROR)
        self.assertEqual(rate_limited.retry_after, 120)
        self.assertEqual(server_error.status, FetchStatus.TEMPORARY_ERROR)
        self.assertEqual(missing.status, FetchStatus.INVALID_OR_PRIVATE)

    async def test_connection_error_is_temporary(self) -> None:
        result, _ = await self.fetch_with(error=aiohttp.ClientConnectionError())
        self.assertEqual(result.status, FetchStatus.TEMPORARY_ERROR)

    async def test_conditional_headers_and_304(self) -> None:
        result, fake = await self.fetch_with(
            FakeResponse(304), etag='"abc"', last_modified="Wed, 12 Aug 2026 00:00:00 GMT"
        )
        self.assertEqual(result.status, FetchStatus.NOT_MODIFIED)
        self.assertEqual(fake.request_headers["If-None-Match"], '"abc"')
        self.assertIn("If-Modified-Since", fake.request_headers)

import httpx
import pytest

from billwatcher.scraper.fetch import Fetcher, ResponseTooLarge
from billwatcher.scraper.policy import CrawlPolicy

POLICY = CrawlPolicy("BillWatcherNext/0.1 (+https://example.org/about)", max_response_bytes=20)


def test_conditional_request_and_safe_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"old"'
        return httpx.Response(
            304,
            headers={"ETag": '"old"', "Set-Cookie": "secret", "X-Debug": "internal"},
            request=request,
        )

    with Fetcher(POLICY, transport=httpx.MockTransport(handler)) as fetcher:
        result = fetcher.get("https://www.parlimen.gov.my/doc.pdf", etag='"old"')
    assert result.not_modified
    assert result.headers == {"etag": '"old"'}


def test_redirect_destination_is_revalidated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "https://evil.example/file"}, request=request
        )

    with (
        Fetcher(POLICY, transport=httpx.MockTransport(handler)) as fetcher,
        pytest.raises(ValueError, match="disallowed upstream"),
    ):
        fetcher.get("https://www.parlimen.gov.my/doc.pdf")


def test_declared_and_streamed_size_caps() -> None:
    declared = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"Content-Length": "21"}, request=request)
    )
    with (
        Fetcher(POLICY, transport=declared) as fetcher,
        pytest.raises(ResponseTooLarge, match="declared"),
    ):
        fetcher.get("https://www.parlimen.gov.my/doc.pdf")

    class ChunkedStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * 11
            yield b"x" * 10

    streamed = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=ChunkedStream(), request=request)
    )
    with (
        Fetcher(POLICY, transport=streamed) as fetcher,
        pytest.raises(ResponseTooLarge, match="streamed"),
    ):
        fetcher.get("https://www.parlimen.gov.my/doc.pdf")


def test_retry_after_is_obeyed_for_429() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = 429 if attempts == 1 else 200
        return httpx.Response(status, headers={"Retry-After": "7"}, request=request)

    with Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=delays.append) as fetcher:
        result = fetcher.get("https://www.parlimen.gov.my/list")
    assert result.status_code == 200
    assert attempts == 2
    assert delays == [7.0]


def test_tls_and_transport_failures_are_not_suppressed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("certificate verify failed", request=request)

    with (
        Fetcher(POLICY, transport=httpx.MockTransport(handler)) as fetcher,
        pytest.raises(httpx.ConnectError, match="certificate"),
    ):
        fetcher.get("https://www.parlimen.gov.my/list")

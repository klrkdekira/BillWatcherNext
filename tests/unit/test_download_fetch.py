import httpx
import pytest

from billwatcher.download.fetch import Fetcher, ResponseTooLarge
from billwatcher.download.policy import CrawlPolicy

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


def test_a_dropped_connection_is_retried() -> None:
    """A server that closes a keep-alive connection has not answered; asking again is correct.

    The first live archive crawl died on this after 59 of 136 requests, so the retry is not a
    theoretical nicety.
    """
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.", request=request
            )
        return httpx.Response(200, content=b"ok", request=request)

    with Fetcher(
        POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None
    ) as fetcher:
        result = fetcher.get("https://www.parlimen.gov.my/doc.pdf")
    assert result.status_code == 200
    assert len(attempts) == 3


def test_retries_are_bounded_and_the_transport_error_surfaces() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with (
        Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None) as f,
        pytest.raises(httpx.ConnectTimeout),
    ):
        f.get("https://www.parlimen.gov.my/doc.pdf")


def test_a_certificate_failure_is_not_retried() -> None:
    """It will not verify on the third attempt either, and the reason is what the operator needs."""
    import ssl

    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        error = httpx.ConnectError("certificate verify failed", request=request)
        raise error from ssl.SSLCertVerificationError("unable to get local issuer certificate")

    with (
        Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None) as f,
        pytest.raises(httpx.ConnectError),
    ):
        f.get("https://www.parlimen.gov.my/doc.pdf")
    assert len(attempts) == 1


def test_every_request_is_spaced_by_the_policy_delay() -> None:
    """Politeness is the fetcher's job, not each caller's.

    The listing orchestrator used to sleep between targets and the document worker did not, so
    draining a queue of 1,292 archived PDFs would have fetched them back to back. Enforcing it per
    request means a new caller cannot forget.
    """
    waits: list[float] = []
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"ok", request=request)
    )
    with Fetcher(POLICY, transport=transport, sleep=waits.append) as fetcher:
        for _ in range(3):
            fetcher.get("https://www.parlimen.gov.my/doc.pdf")

    # The first request waits for nothing; each later one waits for the remainder of the delay.
    assert len(waits) == 2
    assert all(0 < wait <= POLICY.delay_seconds for wait in waits)


def test_a_failed_request_still_counts_as_load() -> None:
    """A server that erred was still asked; the next request waits like any other."""
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=waits.append) as fetcher:
        for _ in range(2):
            with pytest.raises(httpx.ConnectError):
                fetcher.get("https://www.parlimen.gov.my/doc.pdf")

    # Three retries per call, spaced by backoff, plus the politeness wait before the second call.
    assert any(0 < wait <= POLICY.delay_seconds for wait in waits)

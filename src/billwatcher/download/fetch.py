import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import httpx

from billwatcher.download.policy import CrawlPolicy

_SAFE_HEADERS = frozenset(
    {"content-type", "content-length", "etag", "last-modified", "cache-control", "retry-after"}
)


@dataclass(frozen=True, slots=True)
class FetchResult:
    request_url: str
    final_url: str
    requested_at: datetime
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    duration_ms: int
    redirect_chain: tuple[str, ...] = ()

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


class ResponseTooLarge(ValueError):
    pass


# Transport failures where the request was never answered. A GET is idempotent, so retrying is
# safe, and on a long crawl it is necessary: an archive run reads 67 documents per chamber over
# several minutes and a keep-alive connection the server decides to close mid-crawl is ordinary,
# not exceptional. The first live archive crawl died on exactly that after 59 requests.
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteError,
    httpx.WriteTimeout,
)


def _is_retryable(error: BaseException) -> bool:
    """Whether a failed request is worth issuing again."""
    if not isinstance(error, _RETRYABLE_TRANSPORT_ERRORS):
        return False
    # A certificate that does not verify will not verify on the third attempt, and the cause
    # matters more than the delay: fail at once so the operator reads the real reason rather
    # than three copies of it (docs/upstream.md records why this site needs a bundle at all).
    cause = error.__cause__ or error.__context__
    return not isinstance(cause, ssl.SSLError)


class Fetcher:
    """Strict-TLS, allowlisted, bounded synchronous fetcher.

    Redirects are followed manually so every destination is revalidated against the allowlist.
    """

    def __init__(
        self,
        policy: CrawlPolicy,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        max_redirects: int = 5,
    ) -> None:
        self.policy = policy
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.max_redirects = max_redirects
        # Politeness belongs here, not in each caller. The listing orchestrator used to sleep
        # between targets while the document worker did not, so queueing 1,292 archived PDFs would
        # have fetched them back to back — the one place the delay mattered most was the one place
        # nobody had put it. Enforced per request, it cannot be forgotten by a new caller.
        self._earliest_next_request = 0.0
        self.client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            # Verification is never disabled. A configured bundle only adds trust anchors so an
            # upstream that serves an incomplete chain can still be verified (HANDOFF 5).
            verify=str(policy.ca_bundle) if policy.ca_bundle else True,
            timeout=httpx.Timeout(30, connect=10),
            headers={"User-Agent": policy.user_agent, "Accept": "text/html,application/pdf;q=0.9"},
        )

    def begin_session(self, url: str) -> FetchResult:
        """Discard the current session and open a new one by fetching `url`.

        Upstream decides *which document it serves* from the session's language, not from the path.
        A document requested under a session in the other language is answered with HTTP 200 and
        the twenty-three bytes `File does not exist (3)` — so `DR 17 BI.pdf` is missing to a Malay
        session and present to an English one, and the reverse holds for `DR 17 BM.pdf`
        (`documentation/upstream.md`, 2026-08-27). A cookieless client is answered as a Malay one,
        which is why a Malay-only crawl never had to know this.

        The cookies are cleared first: the language rides on `GENPRO_SESSION`, so warming a second
        language on top of an existing session is not guaranteed to move it, and starting clean is
        one request either way.
        """
        self.client.cookies.clear()
        return self.get(url)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def get(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        try:
            return self._get(url, etag=etag, last_modified=last_modified)
        finally:
            # Measured from the end of the request: a slow response has already given the server
            # its breathing room, and a failed one still counts as load.
            self._earliest_next_request = time.monotonic() + self.policy.delay_seconds

    def _get(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        self.policy.validate_url(url)
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        result: FetchResult | None = None
        for attempt in range(self.max_attempts):
            self._wait_for_politeness()
            last_attempt = attempt + 1 == self.max_attempts
            try:
                result = self._request_with_redirects(url, headers)
            except Exception as error:
                if last_attempt or not _is_retryable(error):
                    raise
                self.sleep(self._retry_delay(None, attempt))
                continue
            if result.status_code not in {408, 429} and result.status_code < 500:
                return result
            if not last_attempt:
                self.sleep(self._retry_delay(result.headers.get("retry-after"), attempt))
        assert result is not None  # the loop either returns, raises, or leaves a response
        return result

    def _wait_for_politeness(self) -> None:
        """Space requests by the policy delay, measured from the end of the previous request."""
        remaining = self._earliest_next_request - time.monotonic()
        if remaining > 0:
            self.sleep(remaining)

    def _request_with_redirects(self, url: str, headers: Mapping[str, str]) -> FetchResult:
        current = url
        chain: list[str] = []
        started = time.monotonic()
        requested_at = datetime.now(UTC)
        for _redirect in range(self.max_redirects + 1):
            self.policy.validate_url(current)
            with self.client.stream("GET", current, headers=headers) as response:
                if response.has_redirect_location:
                    location = response.headers.get("location")
                    if not location:
                        break
                    destination = urljoin(current, location)
                    self.policy.validate_url(destination)
                    chain.append(destination)
                    current = destination
                    continue
                declared_length = response.headers.get("content-length")
                if declared_length and int(declared_length) > self.policy.max_response_bytes:
                    raise ResponseTooLarge("declared response exceeds configured byte cap")
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > self.policy.max_response_bytes:
                        raise ResponseTooLarge("streamed response exceeds configured byte cap")
                    chunks.append(chunk)
                safe = {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower() in _SAFE_HEADERS
                }
                return FetchResult(
                    request_url=url,
                    final_url=str(response.url),
                    requested_at=requested_at,
                    status_code=response.status_code,
                    headers=safe,
                    body=b"".join(chunks),
                    duration_ms=round((time.monotonic() - started) * 1000),
                    redirect_chain=tuple(chain),
                )
        raise httpx.TooManyRedirects(f"more than {self.max_redirects} redirects", request=None)

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after:
            if retry_after.isdigit():
                return min(float(retry_after), 300.0)
            try:
                parsed = parsedate_to_datetime(retry_after)
                return max(0.0, min((parsed - datetime.now(UTC)).total_seconds(), 300.0))
            except (TypeError, ValueError):
                pass
        return min(2.0**attempt, 30.0)

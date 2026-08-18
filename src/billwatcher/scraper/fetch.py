import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import httpx

from billwatcher.scraper.policy import CrawlPolicy

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
        self.client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            # Verification is never disabled. A configured bundle only adds trust anchors so an
            # upstream that serves an incomplete chain can still be verified (HANDOFF 5).
            verify=str(policy.ca_bundle) if policy.ca_bundle else True,
            timeout=httpx.Timeout(30, connect=10),
            headers={"User-Agent": policy.user_agent, "Accept": "text/html,application/pdf;q=0.9"},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def get(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        self.policy.validate_url(url)
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        for attempt in range(self.max_attempts):
            result = self._request_with_redirects(url, headers)
            if result.status_code not in {408, 429} and result.status_code < 500:
                return result
            if attempt + 1 < self.max_attempts:
                self.sleep(self._retry_delay(result.headers.get("retry-after"), attempt))
        return result

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

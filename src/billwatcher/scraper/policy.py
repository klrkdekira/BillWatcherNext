from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"www.parlimen.gov.my", "parlimen.gov.my"})


@dataclass(frozen=True, slots=True)
class CrawlPolicy:
    user_agent: str
    delay_seconds: float = 2.0
    concurrency: int = 1
    max_response_bytes: int = 104_857_600
    # Path to an additional trust store. TLS verification is always on; this only widens which
    # certificates can complete a chain, and there is no option to turn verification off.
    ca_bundle: Path | None = None

    def __post_init__(self) -> None:
        if self.delay_seconds < 2 or self.concurrency < 1:
            raise ValueError("crawl policy may not be less polite than the release defaults")
        if not self.user_agent.strip():
            raise ValueError("a descriptive user agent is required")
        if self.ca_bundle is not None and not self.ca_bundle.is_file():
            raise ValueError(f"CA bundle does not name a file: {self.ca_bundle}")

    def validate_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"disallowed upstream URL: {url}")

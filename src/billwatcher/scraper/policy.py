from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"www.parlimen.gov.my", "parlimen.gov.my"})


@dataclass(frozen=True, slots=True)
class CrawlPolicy:
    user_agent: str
    delay_seconds: float = 2.0
    concurrency: int = 1
    max_response_bytes: int = 104_857_600

    def __post_init__(self) -> None:
        if self.delay_seconds < 2 or self.concurrency < 1:
            raise ValueError("crawl policy may not be less polite than the release defaults")
        if not self.user_agent.strip():
            raise ValueError("a descriptive user agent is required")

    def validate_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"disallowed upstream URL: {url}")

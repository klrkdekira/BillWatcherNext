import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


@dataclass(frozen=True, slots=True)
class RobotsPolicy:
    sha256: str
    body: bytes
    fetched_url: str

    def permits(self, user_agent: str, url: str) -> bool:
        parser = RobotFileParser()
        parser.set_url(self.fetched_url)
        parser.parse(self.body.decode("utf-8", errors="strict").splitlines())
        return parser.can_fetch(user_agent, url)

    def crawl_delay(self, user_agent: str) -> float | None:
        parser = RobotFileParser()
        parser.set_url(self.fetched_url)
        parser.parse(self.body.decode("utf-8", errors="strict").splitlines())
        value = parser.crawl_delay(user_agent)
        return float(value) if value is not None else None


def parse_robots(body: bytes, *, fetched_url: str) -> RobotsPolicy:
    parts = urlsplit(fetched_url)
    if parts.scheme != "https" or parts.path != "/robots.txt":
        raise ValueError("robots policy must come from the HTTPS host root")
    # Decode now so malformed bytes fail preflight instead of becoming permissive.
    body.decode("utf-8", errors="strict")
    return RobotsPolicy(hashlib.sha256(body).hexdigest(), body, fetched_url)

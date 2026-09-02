"""Bounded pagination with loop detection (HANDOFF 11.3 step 4, 10.5).

A listing that keeps serving the same body for every "next page" is a common upstream failure:
it looks like progress and produces a plausible crawl that never terminates. This guard bounds
the page count and stops the moment a body repeats.

No live target paginates, and now that the archive contract is settled none will: the archive is
a year index rather than a page sequence, so its bound is a year count and its repeat detection is
per-year content hashing by the snapshot layer (ADR-014). This guard is kept because it is the
right shape for the failure it names — a "next page" that keeps serving the same body looks like
progress and produces a plausible crawl that never terminates — and because either listing could
start paginating at any redesign. It is tested on its own.
"""

import hashlib
from dataclasses import dataclass, field


class PaginationLoop(RuntimeError):
    """Raised when a paginated target repeats a body or exceeds its page budget."""

    def __init__(self, message: str, *, page: int, content_sha256: str | None = None) -> None:
        super().__init__(message)
        self.page = page
        self.content_sha256 = content_sha256


@dataclass(slots=True)
class PaginationGuard:
    max_pages: int = 200
    _seen: dict[str, int] = field(default_factory=dict)
    _pages: int = 0

    @property
    def pages_seen(self) -> int:
        return self._pages

    def observe(self, body: bytes) -> str:
        """Record one fetched page, returning its content hash.

        Raises `PaginationLoop` when the body repeats an earlier page or the budget is spent.
        """
        self._pages += 1
        if self._pages > self.max_pages:
            raise PaginationLoop(f"pagination exceeded {self.max_pages} pages", page=self._pages)
        digest = hashlib.sha256(body).hexdigest()
        previous = self._seen.get(digest)
        if previous is not None:
            raise PaginationLoop(
                f"page {self._pages} repeats the body first seen on page {previous}",
                page=self._pages,
                content_sha256=digest,
            )
        self._seen[digest] = self._pages
        return digest

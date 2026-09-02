"""How a pipeline step reports what it did — including, by name, what it could not do.

Every step used to answer `except Exception: counts["failed"] += 1`, which tells an operator that
something failed and nothing whatever about which document, or why. Over a corpus of a couple of
thousand documents that is not a report, it is a rumour: a persistently failing document is
indistinguishable from a transient endpoint timeout, and a bug in our own code is
indistinguishable from malformed upstream input.

`StepResult` keeps the counts a step already returned and adds the identity of each failure beside
them. The counts stay a flat `dict[str, int]` because that is what the CLI echoes and what the
`/status` surface reads; the failures are a separate field rather than extra count keys, so a
histogram stays a histogram.

Manifests are the other half. A per-run manifest is where volatile facts belong — when the run
started, what code produced it, which documents failed — because its path is already unique per
run. The same fields inside a per-artifact sidecar would make every re-run rewrite it (ADR-019).

A long live step needs one thing more. The document download is 1,295 requests spaced two seconds
apart by the crawl policy — about fifty minutes during which a report delivered at the end is
indistinguishable from a hung process, and during which an operator deciding whether to keep
waiting has nothing to read. `Progress` is that running commentary: it goes to stderr so the
step's stdout stays the single parseable JSON object the rest of this CLI promises.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# How many failures a manifest carries. Bounded for the same reason a gate verdict bounds its
# findings: a manifest listing two thousand failures is not read by anybody, and the count above
# it already says how bad things are.
FAILURE_LIMIT = 50

# What a step calls to say where it has got to. `None` is the ordinary case — a test, or a step
# whose whole run is over in a second — so a step must treat progress as optional, never as a
# channel it can rely on having.
Progress = Callable[[str], None] | None


def announce(progress: Progress, message: str) -> None:
    """Report one step of visible work, if anybody is listening."""
    if progress is not None:
        progress(message)


@dataclass(frozen=True, slots=True)
class StepFailure:
    """One document a step could not process, and why."""

    bill_slug: str
    doc_key: str
    version: int
    reason: str

    @property
    def label(self) -> str:
        """How a report names this failure: the three coordinates that address the document."""
        return f"{self.bill_slug}/{self.doc_key}/v{self.version:03d}"

    def as_detail(self) -> dict[str, Any]:
        return {
            "bill_slug": self.bill_slug,
            "doc_key": self.doc_key,
            "version": self.version,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ListingFailure:
    """One listing a step could not fetch, or could not parse once fetched.

    Steps 1 and 2 fail before any document exists: what went wrong belongs to a listing key and a
    URL, and there is no bill slug and no version to name yet. Faking those two coordinates to
    reuse `StepFailure` would stamp `v001` on a robots.txt timeout, so the two kinds stay distinct
    and agree only on what a report asks of them — a label, a reason, and a detail record.
    """

    key: str
    url: str
    reason: str

    @property
    def label(self) -> str:
        """The listing key, plus the URL an operator would need in order to retry it by hand."""
        return f"listing {self.key} <{self.url}>" if self.url else f"listing {self.key}"

    def as_detail(self) -> dict[str, Any]:
        return {"key": self.key, "url": self.url, "reason": self.reason}


# Either kind of failure, wherever a report only needs `label`, `reason` and `as_detail`.
Failure = StepFailure | ListingFailure


@dataclass(frozen=True, slots=True)
class StepResult:
    counts: dict[str, int]
    failures: tuple[Failure, ...] = field(default=())

    def as_payload(self) -> dict[str, Any]:
        """What the CLI echoes: the histogram, plus named failures when there are any."""
        payload: dict[str, Any] = dict(self.counts)
        if self.failures:
            payload["failures"] = [item.as_detail() for item in self.failures[:FAILURE_LIMIT]]
            payload["failures_truncated"] = len(self.failures) > FAILURE_LIMIT
        return payload


def describe_error(error: BaseException) -> str:
    """`TypeName: message`, trimmed — enough to act on without pasting a traceback into a file."""
    message = str(error).strip().splitlines()
    summary = message[0][:200] if message else ""
    return f"{type(error).__name__}: {summary}" if summary else type(error).__name__


def manifest_payload(
    result: StepResult, *, code_versions: dict[str, str], started_at: datetime
) -> dict[str, Any]:
    """The per-run record ADR-019 requires of every step: what it did, at which code versions."""
    return {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "code_versions": dict(code_versions),
        "counts": dict(result.counts),
        "failures": [item.as_detail() for item in result.failures[:FAILURE_LIMIT]],
        "failures_truncated": len(result.failures) > FAILURE_LIMIT,
    }


def run_id_for(started_at: datetime) -> str:
    """A filesystem-safe run identifier from the run's own start time.

    Microseconds are included because the manifest path is the run's identity: at second
    granularity two runs of the same step in one second — an ordinary sequential shell loop over a
    few documents — wrote the same path and the first run's record was simply gone. A manifest that
    can be overwritten is not an audit record.
    """
    return started_at.strftime("%Y%m%dT%H%M%S.%fZ")

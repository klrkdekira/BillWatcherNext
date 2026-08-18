"""Regenerate committed fixtures from stored snapshots, offline (HANDOFF 16.3).

`make fixtures-refresh` used to re-run `reparse`, which validates stored snapshots but does not
regenerate anything. This does what the contract asks: for each committed fixture it finds the
newest stored snapshot of the same upstream document, reduces it to the first few records, and
writes the result with a provenance header naming the snapshot it came from.

Two properties make the output trustworthy:

* **The retained bytes are verbatim.** Reduction only drops whole rows or whole tree nodes; it
  never rewrites what is kept, so a refreshed fixture still fails on any shape the parser gets
  wrong. Cutting rows out is nesting-aware, because the listing hides a table inside a cell.
* **It never reaches the network.** The only input is a snapshot already in the blob store, so a
  refresh cannot silently become a crawl.

What it deliberately does not reproduce is the hand-editing in the committed fixtures — stripped
inline styling, or a row chosen because it carries a particular status. A refreshed fixture is a
starting point for review, which is why it writes to a staging directory unless `--apply` is
given.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.jobs.fixtures import FIXTURE_TARGETS, FIXTURES_DIR, FixtureTarget
from billwatcher.models import Blob, ScrapeRun, SourceSnapshot
from billwatcher.scraper.parse_archive import is_archive_year_url
from billwatcher.storage.blobs import BlobStore

STAGING_DIR = FIXTURES_DIR / "regenerated"
DEFAULT_RECORD_LIMIT = 4


@dataclass(frozen=True, slots=True)
class RefreshedFixture:
    fixture: str
    url: str
    snapshot_id: str
    observed_at: datetime
    records_kept: int
    written_to: Path
    changed: bool


@dataclass(frozen=True, slots=True)
class RefreshReport:
    refreshed: tuple[RefreshedFixture, ...]
    skipped: tuple[tuple[str, str], ...]

    def as_counts(self) -> dict[str, object]:
        return {
            "refreshed": [
                {
                    "fixture": item.fixture,
                    "snapshot_id": item.snapshot_id,
                    "observed_at": item.observed_at.isoformat(),
                    "records_kept": item.records_kept,
                    "written_to": str(item.written_to),
                    "changed": item.changed,
                }
                for item in self.refreshed
            ],
            "skipped": [{"fixture": name, "reason": reason} for name, reason in self.skipped],
        }


def refresh_fixtures(
    session: Session,
    *,
    blob_store: BlobStore,
    targets: tuple[FixtureTarget, ...] = FIXTURE_TARGETS,
    fixtures_dir: Path = FIXTURES_DIR,
    staging_dir: Path = STAGING_DIR,
    apply: bool = False,
    record_limit: int = DEFAULT_RECORD_LIMIT,
) -> RefreshReport:
    refreshed: list[RefreshedFixture] = []
    skipped: list[tuple[str, str]] = []
    destination = fixtures_dir if apply else staging_dir
    for target in targets:
        snapshot = _newest_observation(session, target.url)
        if snapshot is None:
            skipped.append((target.fixture, "no stored snapshot of this document"))
            continue
        blob = session.get(Blob, snapshot.blob_sha256) if snapshot.blob_sha256 else None
        if blob is None:
            skipped.append((target.fixture, "the snapshot's response body is not in the store"))
            continue
        body = blob_store.get(blob.sha256, compression=blob.compression).decode("utf-8")
        try:
            reduced, kept = _reduce(body, url=target.url, limit=record_limit)
        except ValueError as error:
            skipped.append((target.fixture, str(error)))
            continue
        content = _with_provenance(
            reduced,
            fixture=target.fixture,
            url=target.url,
            snapshot=snapshot,
            kept=kept,
            limit=record_limit,
        )
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / target.fixture
        previous = (
            (fixtures_dir / target.fixture).read_text()
            if (fixtures_dir / target.fixture).exists()
            else ""
        )
        path.write_text(content)
        refreshed.append(
            RefreshedFixture(
                fixture=target.fixture,
                url=target.url,
                snapshot_id=snapshot.id,
                observed_at=snapshot.requested_at,
                records_kept=kept,
                written_to=path,
                changed=_structural(previous) != _structural(content),
            )
        )
    return RefreshReport(tuple(refreshed), tuple(skipped))


def _newest_observation(session: Session, url: str) -> SourceSnapshot | None:
    """The newest snapshot of this document that came from upstream rather than from a fixture."""
    return session.scalar(
        select(SourceSnapshot)
        .join(ScrapeRun, ScrapeRun.id == SourceSnapshot.run_id)
        .where(
            SourceSnapshot.url == url,
            SourceSnapshot.status_code == 200,
            SourceSnapshot.blob_sha256.is_not(None),
            ScrapeRun.mode != "fixture",
        )
        .order_by(SourceSnapshot.requested_at.desc())
        .limit(1)
    )


def _structural(content: str) -> str:
    """Content without its provenance header, so a re-dated refresh is not reported as a change."""
    return "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("<!--")
    ).strip()


def _with_provenance(
    reduced: str,
    *,
    fixture: str,
    url: str,
    snapshot: SourceSnapshot,
    kept: int,
    limit: int,
) -> str:
    note = (
        f"Regenerated by `make fixtures-refresh` from snapshot {snapshot.id}, which stored "
        f"{url} on {snapshot.requested_at.isoformat()}. The first {kept} of the document's "
        f"records are kept verbatim (limit {limit}); nothing retained was rewritten. Review "
        "before committing: the fixtures in this directory are hand-reduced further, and a "
        "regenerated file does not reproduce those edits."
    )
    if reduced.lstrip().startswith("<?xml"):
        declaration, _, rest = reduced.partition("?>")
        return f"{declaration}?>\n<!-- {note} -->\n{rest.lstrip()}"
    return f"<!-- {note} -->\n{reduced}"


def _reduce(body: str, *, url: str, limit: int) -> tuple[str, int]:
    if is_archive_year_url(url):
        return _reduce_tree(body, limit=limit)
    return _reduce_listing(body, limit=limit)


def _reduce_tree(body: str, *, limit: int) -> tuple[str, int]:
    """Keep the first `limit` bill nodes of an archive year, each verbatim.

    The nodes are sliced out of the source text rather than re-serialized, because
    `ElementTree.tostring` would rewrite attribute quoting and empty elements. Those rewrites
    look harmless and are exactly what makes a fixture stop being evidence of what upstream
    sent. The document is parsed first so a malformed response is rejected before it is cut up.
    """
    root = ElementTree.fromstring(body)
    if not root.findall("item"):
        raise ValueError("the stored archive year carried no bill nodes")
    open_tag_end = body.index(">", body.index("<tree"))
    spans = _top_level_element_spans(body[open_tag_end + 1 : body.rindex("</tree>")], "item")
    kept = spans[:limit]
    inner = body[open_tag_end + 1 : body.rindex("</tree>")]
    return (
        body[: open_tag_end + 1] + "".join(inner[start:end] for start, end in kept) + "</tree>\n",
        len(kept),
    )


def _top_level_element_spans(body: str, tag: str) -> list[tuple[int, int]]:
    """Spans of the outermost `<tag>` elements, tracking nesting so children are not cut."""
    pattern = re.compile(rf"<{tag}\b[^>]*?/>|<{tag}\b|</{tag}>")
    spans: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for match in pattern.finditer(body):
        token = match.group(0)
        if token.endswith("/>"):
            if depth == 0:
                spans.append((match.start(), match.end()))
            continue
        if token.startswith("</"):
            depth -= 1
            if depth == 0:
                spans.append((start, match.end()))
        else:
            if depth == 0:
                start = match.start()
            depth += 1
    return spans


def _reduce_listing(body: str, *, limit: int) -> tuple[str, int]:
    """Keep a listing's header row and its first `limit` data rows, sliced out verbatim.

    The slice is nesting-aware: the live listing hides a whole table inside its status cell, and
    cutting at the first `</tr>` would truncate a row in the middle of its own detail table.
    """
    rows = _TopLevelRows(body)
    if len(rows.spans) < 2:
        raise ValueError("the stored listing had no rows to reduce")
    header = rows.spans[0]
    data = rows.spans[1 : 1 + limit]
    kept_rows = "".join(body[start:end] for start, end in [header, *data])
    # Everything before the first row and after the last one is markup the parser needs — the
    # table's own tags, the thead and tbody wrappers, the closing document. Only the rows
    # between the ones being kept and the end of the table are dropped.
    return body[: header[0]] + kept_rows + body[rows.spans[-1][1] :], len(data)


class _TopLevelRows(HTMLParser):
    """Byte spans of the `<tr>` elements that belong to the outermost table."""

    def __init__(self, body: str) -> None:
        super().__init__(convert_charrefs=True)
        self._offsets = _line_offsets(body)
        self._table_depth = 0
        self._row_depth = 0
        self._start: int | None = None
        self.spans: list[tuple[int, int]] = []
        self.feed(body)
        self.close()

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr":
            self._row_depth += 1
            if self._table_depth == 1 and self._row_depth == 1:
                self._start = self._offset()

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._table_depth = max(0, self._table_depth - 1)
        elif tag == "tr":
            if self._table_depth == 1 and self._row_depth == 1 and self._start is not None:
                self.spans.append((self._start, self._offset() + len("</tr>")))
                self._start = None
            self._row_depth = max(0, self._row_depth - 1)


def _line_offsets(body: str) -> list[int]:
    offsets = [0]
    for line in body.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets

"""Step 3 of the file-first pipeline: download every document URL `parse_listings` found.

PDF parsing/extraction is explicitly out of scope for this pipeline — the operator has a vLLM
OpenAI-compatible endpoint for that, separately. This step only ever produces
`documents/<bill-slug>/<doc-key>/v001/document.pdf` plus a sidecar.

This is the pipeline's one genuinely long step: the whole corpus is ~1,295 documents, and the crawl
policy spaces every request two seconds apart, so a cold run is around fifty minutes of wall clock.
Two consequences shape the code below. It plans the work before fetching any of it, so the very
first thing an operator learns is how many documents are actually outstanding; and it reports each
attempt as it happens, because a silent fifty minutes cannot be told apart from a hung process.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from billwatcher.download.fetch import Fetcher, FetchResult
from billwatcher.download.targets import TARGETS
from billwatcher.reporting import (
    Progress,
    StepFailure,
    StepResult,
    announce,
    describe_error,
)
from billwatcher.store import PipelineStore

VERSION = 1

# How much of a refused body is quoted in the failure reason. Parliament answers a dead link in
# its own bill index with HTTP 200 and the twenty-three bytes `File does not exist (3)`, so for a
# body this small the body *is* the diagnosis, and quoting it is the difference between a failure
# an operator can classify from the manifest and one they have to re-fetch by hand to understand.
BODY_SNIPPET_LIMIT = 200

# What upstream sends instead of a PDF when the session's language does not match the document's.
# It is HTTP 200 with a `text/html` body, so only the body distinguishes it from a real answer.
MISSING_FILE_MARKER = b"File does not exist"

# The order languages are crawled in. Fixed rather than derived from the queue so two runs report
# their progress the same way, and Malay first because that is the half already on disk.
LANGUAGE_ORDER: tuple[str, ...] = ("ms", "en")


def _session_urls() -> dict[str, str]:
    """One listing URL per language, used only to put a session into that language.

    Taken from `TARGETS` rather than written out again here: the entry points are upstream facts
    that live in one module, and a language whose target moves must not leave this step warming a
    session against a dead URL.
    """
    return {
        target.language: target.url
        for target in TARGETS
        if target.listing_kind == "current" and target.chamber == "dewan_rakyat"
    }


def doc_key(url: str) -> str:
    """A path-safe identifier derived only from the document's own URL.

    There is no database here to assign an id, so the URL is what gives a document a stable
    identity across runs — the same URL always resolves to the same directory, which is what
    makes `has_document` a meaningful "already downloaded" check.
    """
    return f"doc-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def language_of(document: dict[str, Any]) -> str | None:
    """Which language a document is in, or `None` when its listings do not settle it.

    `parse_listings` records every listing language that named a file (`languages`). Exactly one
    means that language published it — the archive names `DR 17 BM.pdf` on its Malay pages and
    `DR 17 BI.pdf` on its English ones. More than one means Parliament links the same file from
    pages of both languages, and a file cannot be two Expressions of one bill, so nothing is
    claimed. A record written before languages were tracked has no entries and says nothing either.
    """
    languages = [value for value in document.get("languages") or [] if isinstance(value, str)]
    return languages[0] if len(languages) == 1 else None


def document_languages(bill: dict[str, Any]) -> dict[str, str]:
    """`{doc_key: language}` for one bill, omitting every document whose language is unsettled.

    Keyed by `doc_key` because that is how a *stored* document is addressed, while the bill record
    knows only URLs. This is what lets a later step read a document's language off the bill it came
    from rather than re-deriving it, or asking an operator to assert one language for a corpus that
    has two.
    """
    languages: dict[str, str] = {}
    for document in bill.get("documents") or []:
        url = document.get("url")
        language = language_of(document)
        if url and language:
            languages[doc_key(url)] = language
    return languages


@dataclass(frozen=True, slots=True)
class _Outstanding:
    """One document this run still has to fetch."""

    bill_slug: str
    key: str
    url: str
    chamber: Any
    language: str | None = None


def fetch_documents(
    fetcher: Fetcher, store: PipelineStore, *, progress: Progress = None
) -> StepResult:
    """Live. One PDF per document URL, skipped if already present; no version tracking yet —
    upstream bytes changing at the same URL is a `for later` concern once the database returns.

    Deciding what to skip *before* fetching anything, rather than one document at a time, is what
    lets this report `[7/588]` instead of an unbounded stream of lines: the skip check is a stat
    against the store, so reading all of them up front costs a second or two and buys a
    denominator. Nothing else writes documents during a run, so the answer cannot go stale.
    """
    counts = {
        "considered": 0,
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
        "sessions_opened": 0,
        "downloaded_language_unsettled": 0,
    }
    outstanding = _plan(store, counts)
    total = len(outstanding)
    announce(
        progress,
        f"{total} document(s) to download; {counts['skipped']} already stored "
        f"of {counts['considered']} referenced",
    )
    failures: list[StepFailure] = []
    session_urls = _session_urls()
    index = 0

    def refuse(item: _Outstanding, reason: str) -> None:
        """Count, name and narrate one document this run will not store."""
        nonlocal index
        index += 1
        counts["failed"] += 1
        failures.append(StepFailure(item.bill_slug, item.key, VERSION, reason))
        announce(progress, f"[{index}/{total}] FAILED {item.bill_slug}/{item.key}: {reason}")

    def store_one(item: _Outstanding, *, note: str = "") -> None:
        """Count and narrate one document this run did store."""
        nonlocal index
        index += 1
        counts["downloaded"] += 1
        announce(progress, f"[{index}/{total}] {item.bill_slug}/{item.key}{note}")

    # Grouped by language and crawled a language at a time, because the session — not the URL —
    # decides which document upstream serves (`Fetcher.begin_session`). Interleaving the two halves
    # would need a fresh session per document, which is one extra request each; grouped, it is two
    # for the whole run.
    by_language: dict[str | None, list[_Outstanding]] = {}
    for item in outstanding:
        by_language.setdefault(item.language, []).append(item)

    # A document both languages' listings named has no language of its own to crawl under (ADR-040
    # §4), so it is attempted under each in turn and only counts as failed once both have refused
    # it. There are few of them and they are the pre-2012 paths with no `BM`/`BI` in the filename.
    unsettled = list(by_language.get(None, ()))
    # Why each language refused an unsettled document, kept so the final report can say "404 in
    # both" rather than only "nobody served it" — the two want different responses from an operator.
    unsettled_reasons: dict[str, dict[str, str]] = {}

    for language in LANGUAGE_ORDER:
        batch = by_language.get(language, [])
        if not batch and not unsettled:
            continue
        session_url = session_urls.get(language)
        if session_url is None:
            for item in batch:
                refuse(item, f"no listing target defines a {language!r} session")
            continue
        try:
            fetcher.begin_session(session_url)
        except Exception as error:  # a session that cannot be opened fails its whole batch
            described = describe_error(error)
            for item in batch:
                refuse(item, f"could not open a {language} session: {described}")
            continue
        counts["sessions_opened"] += 1
        announce(
            progress,
            f"opened a {language} session for {len(batch) + len(unsettled)} document(s)",
        )

        for item in batch:
            reason = _download_one(fetcher, store, item)
            if reason is not None:
                refuse(item, f"{reason}: {item.url}")
                continue
            store_one(item)

        still_unsettled: list[_Outstanding] = []
        for item in unsettled:
            reason = _download_one(fetcher, store, item)
            if reason is None:
                counts["downloaded_language_unsettled"] += 1
                store_one(item, note=f" (as {language})")
                continue
            unsettled_reasons.setdefault(item.key, {})[language] = reason
            still_unsettled.append(item)
        unsettled = still_unsettled

    # Whatever no language would serve is a genuine failure, reported once rather than per attempt.
    for item in unsettled:
        attempts = unsettled_reasons.get(item.key, {})
        detail = "; ".join(f"{language}: {reason}" for language, reason in attempts.items())
        refuse(item, f"no language's session served it ({detail}): {item.url}")
    return StepResult(counts=counts, failures=tuple(failures))


def _plan(store: PipelineStore, counts: dict[str, int]) -> list[_Outstanding]:
    """Every referenced document that is not already stored, counting the ones that are."""
    outstanding: list[_Outstanding] = []
    for slug in store.iter_bill_slugs():
        bill = store.load_bill(slug)
        if not bill:
            continue
        for doc in bill.get("documents", []):
            url = doc.get("url")
            if not url:
                continue
            counts["considered"] += 1
            key = doc_key(url)
            if store.has_document(bill_slug=slug, doc_key=key, version=VERSION):
                counts["skipped"] += 1
                continue
            outstanding.append(_Outstanding(slug, key, url, doc.get("chamber"), language_of(doc)))
    return outstanding


def _describe_body(result: FetchResult) -> str:
    """What arrived instead of a PDF, quoted when it is short enough to be the whole answer."""
    content_type = result.headers.get("content-type", "unknown")
    described = f"{len(result.body)} bytes, content-type {content_type}"
    if len(result.body) > BODY_SNIPPET_LIMIT:
        return described
    snippet = result.body.decode("utf-8", errors="replace").strip()
    return f"{described}: {snippet!r}" if snippet else described


def _download_one(fetcher: Fetcher, store: PipelineStore, item: _Outstanding) -> str | None:
    """`None` on success, otherwise why this document was not stored.

    A refused document is named rather than merely counted, because the two reasons it can be
    refused want opposite responses from an operator: a transport error is worth retrying on the
    next run, and a URL that answers 404 or serves an HTML error page will answer the same way
    forever and costs a full two-second slot every time the run reaches it.
    """
    try:
        result = fetcher.get(item.url)
    except Exception as error:
        return describe_error(error)
    if result.status_code != 200:
        return f"HTTP {result.status_code}"
    if not result.body.startswith(b"%PDF-"):
        if MISSING_FILE_MARKER in result.body[:BODY_SNIPPET_LIMIT]:
            # Upstream's dead-link answer, and also its answer to a document requested under the
            # wrong session language. Named as the ambiguity it is: after this step has tried every
            # language, the remaining reading is that upstream links a file it does not hold.
            return f"upstream reports no such file for a {item.language or 'default'} session"
        return f"not a PDF ({_describe_body(result)})"
    metadata = {
        "source_url": item.url,
        "final_url": result.final_url,
        "retrieved_at": result.requested_at.isoformat(),
        "sha256": hashlib.sha256(result.body).hexdigest(),
        "byte_size": len(result.body),
        "bill_slug": item.bill_slug,
        "chamber": item.chamber,
    }
    # Recorded when the listings settle it, and left out when they do not, rather than written as
    # null: the bill record is the authority on a document's language, and this is a copy of it for
    # anyone reading the stored document on its own.
    if item.language is not None:
        metadata["language"] = item.language
    store.save_document(
        bill_slug=item.bill_slug,
        doc_key=item.key,
        version=VERSION,
        content=result.body,
        metadata=metadata,
    )
    return None


class DocumentImportError(Exception):
    """Why a locally supplied PDF cannot enter the store."""


def import_document(
    store: PipelineStore,
    *,
    bill_slug: str,
    url: str,
    content: bytes,
    via: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Record a PDF obtained outside the crawler, under the identity its URL already has.

    Parliament removes bill files from its own index — every one of the 51 dead links this was
    written for answers `File does not exist` — and a copy recovered from an archive or a library
    mirror enters the corpus here rather than being dropped into the tree by hand. The URL is the
    identity: it must be one the bill's own record names, so a recovered file can never claim a
    document the listings never linked, and its `doc_key` is derived from that URL exactly as the
    crawler would have derived it. `via` names where the bytes actually came from, which is the
    one fact a re-crawl could never reconstruct.

    The stored metadata mirrors what `fetch_documents` writes, minus `final_url` (nothing was
    fetched) and plus `retrieved_via`, so every downstream step reads an imported document exactly
    as it reads a crawled one.
    """
    if not content.startswith(b"%PDF-"):
        raise DocumentImportError("the source file does not have PDF magic bytes")
    bill = store.load_bill(bill_slug)
    if bill is None:
        raise DocumentImportError(f"no bill record for {bill_slug!r}")
    documents = [d for d in bill.get("documents") or [] if d.get("url") == url]
    if not documents:
        raise DocumentImportError(f"{bill_slug}'s record names no document at {url}")
    document = documents[0]
    key = doc_key(url)
    if store.has_document(bill_slug=bill_slug, doc_key=key, version=VERSION) and not replace:
        raise DocumentImportError(
            f"{bill_slug}/{key} is already stored; pass --replace to overwrite it"
        )
    metadata: dict[str, Any] = {
        "source_url": url,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "retrieved_via": via,
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_size": len(content),
        "bill_slug": bill_slug,
        "chamber": document.get("chamber"),
    }
    language = language_of(document)
    if language is not None:
        metadata["language"] = language
    store.save_document(
        bill_slug=bill_slug, doc_key=key, version=VERSION, content=content, metadata=metadata
    )
    return {"bill_slug": bill_slug, "doc_key": key, "language": language, **metadata}

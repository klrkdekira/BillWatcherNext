"""Step 3 of the file-first pipeline: download document URLs found in bill records."""

import io
import json

import httpx
from pypdf import PdfWriter

from billwatcher.download.documents import _session_urls, doc_key, fetch_documents
from billwatcher.download.fetch import Fetcher
from billwatcher.download.policy import CrawlPolicy
from billwatcher.store import FileStore

POLICY = CrawlPolicy("BillWatcherNext-pipeline-test/0.1 (+https://www.parlimen.gov.my/about)")


def pdf(title: str) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


# `fetch_documents` opens one session per language before fetching that language's documents,
# because upstream serves a document only to a session in its language (ADR-040 addendum). These
# tests care about the documents, so the warmup URLs are answered here rather than in every route
# table — an unroutable warmup would fail a whole batch and mask what each test is actually about.
SESSION_URLS = frozenset(_session_urls().values())


def _fetcher(routes: dict[str, tuple[int, bytes]]) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in SESSION_URLS:
            return httpx.Response(
                200,
                content=b"<html></html>",
                headers={"Content-Type": "text/html"},
                request=request,
            )
        status, body = routes[url]
        return httpx.Response(
            status, content=body, headers={"Content-Type": "application/pdf"}, request=request
        )

    return Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None)


def seed_bill(store: FileStore, *, slug: str, urls: list[str]) -> None:
    store.save_bill(
        slug,
        {
            "identifier": {"slug": slug},
            "documents": [{"url": url, "chamber": "dewan_rakyat"} for url in urls],
        },
    )


def test_downloads_every_document_url_found_across_bills(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_bill(store, slug="dr-15-2026", urls=["https://www.parlimen.gov.my/a.pdf"])
    seed_bill(store, slug="dr-16-2026", urls=["https://www.parlimen.gov.my/b.pdf"])

    routes = {
        "https://www.parlimen.gov.my/a.pdf": (200, pdf("a")),
        "https://www.parlimen.gov.my/b.pdf": (200, pdf("b")),
    }
    with _fetcher(routes) as fetcher:
        result = fetch_documents(fetcher, store)

    assert result.counts == {
        "considered": 2,
        "downloaded": 2,
        "skipped": 0,
        "failed": 0,
        # Seeded without a language, so both were attempted under the first session and served.
        "sessions_opened": 1,
        "downloaded_language_unsettled": 2,
    }
    assert result.failures == ()
    refs = {(ref.bill_slug, ref.doc_key) for ref in store.iter_documents()}
    assert refs == {
        ("dr-15-2026", doc_key("https://www.parlimen.gov.my/a.pdf")),
        ("dr-16-2026", doc_key("https://www.parlimen.gov.my/b.pdf")),
    }


def test_an_already_downloaded_document_is_skipped_not_refetched(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_bill(store, slug="dr-15-2026", urls=["https://www.parlimen.gov.my/a.pdf"])
    routes = {"https://www.parlimen.gov.my/a.pdf": (200, pdf("a"))}

    with _fetcher(routes) as fetcher:
        first = fetch_documents(fetcher, store)
    assert first.counts["downloaded"] == 1

    with _fetcher(routes) as fetcher:
        second = fetch_documents(fetcher, store)
    assert second.counts == {
        "considered": 1,
        "downloaded": 0,
        "skipped": 1,
        "failed": 0,
        # Nothing outstanding, so no session is opened: the skip check costs no requests.
        "sessions_opened": 0,
        "downloaded_language_unsettled": 0,
    }


def test_a_non_pdf_response_is_not_stored(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_bill(store, slug="dr-15-2026", urls=["https://www.parlimen.gov.my/bad.pdf"])
    routes = {"https://www.parlimen.gov.my/bad.pdf": (200, b"<html>not a pdf</html>")}

    with _fetcher(routes) as fetcher:
        result = fetch_documents(fetcher, store)

    assert result.counts == {
        "considered": 1,
        "downloaded": 0,
        "skipped": 0,
        "failed": 1,
        "sessions_opened": 2,
        "downloaded_language_unsettled": 0,
    }
    assert list(store.iter_documents()) == []


def test_a_document_shared_by_two_bills_gets_its_own_directory_under_each(tmp_path) -> None:
    store = FileStore(tmp_path)
    shared_url = "https://www.parlimen.gov.my/shared.pdf"
    seed_bill(store, slug="dr-15-2026", urls=[shared_url])
    seed_bill(store, slug="dn-3-2026", urls=[shared_url])
    routes = {shared_url: (200, pdf("shared"))}

    with _fetcher(routes) as fetcher:
        result = fetch_documents(fetcher, store)

    assert result.counts["downloaded"] == 2  # one per bill directory, legibility over dedup
    slugs = {ref.bill_slug for ref in store.iter_documents()}
    assert slugs == {"dr-15-2026", "dn-3-2026"}
    for slug in slugs:
        assert store.has_document(bill_slug=slug, doc_key=doc_key(shared_url), version=1)


def test_a_document_that_will_not_download_is_named_with_its_reason_and_url(tmp_path) -> None:
    """A count of failures is not actionable: `doc-<hash>` is not a URL anybody can retry.

    The two ways a download is refused want opposite responses — a 404 will answer the same way
    forever and costs a full politeness slot on every future run, an HTML error page under a 200
    means the URL is right and the response is not — so the reason distinguishes them by name.
    """
    store = FileStore(tmp_path)
    gone = "https://www.parlimen.gov.my/gone.pdf"
    not_pdf = "https://www.parlimen.gov.my/error-page.pdf"
    seed_bill(store, slug="dr-15-2026", urls=[gone, not_pdf])
    # Parliament's own soft-404: HTTP 200, an HTML content type, and a body that is the message.
    routes = {gone: (404, b"no such bill"), not_pdf: (200, b"File does not exist (3)")}

    with _fetcher(routes) as fetcher:
        result = fetch_documents(fetcher, store)

    assert result.counts == {
        "considered": 2,
        "downloaded": 0,
        "skipped": 0,
        "failed": 2,
        "sessions_opened": 2,
        "downloaded_language_unsettled": 0,
    }
    # Neither document's language is settled, so each was tried under both sessions and the
    # failure names what every language answered — "404 under both" and "no such file under both"
    # want different responses, and a bare "nobody served it" would not tell them apart.
    reasons = {failure.reason for failure in result.failures}
    assert f"no language's session served it (ms: HTTP 404; en: HTTP 404): {gone}" in reasons, (
        reasons
    )
    assert (
        "no language's session served it "
        "(ms: upstream reports no such file for a default session; "
        f"en: upstream reports no such file for a default session): {not_pdf}" in reasons
    ), reasons
    assert {failure.label for failure in result.failures} == {
        f"dr-15-2026/{doc_key(url)}/v001" for url in (gone, not_pdf)
    }
    assert list(store.iter_documents()) == []


def test_the_download_says_how_much_work_is_outstanding_before_it_starts(tmp_path) -> None:
    """The denominator is the point: a resumed run is minutes or an hour depending on it, and the
    old single line of output at the end could not be told apart from a hung process."""
    store = FileStore(tmp_path)
    stored = ["https://www.parlimen.gov.my/a.pdf", "https://www.parlimen.gov.my/b.pdf"]
    fresh = "https://www.parlimen.gov.my/c.pdf"
    seed_bill(store, slug="dr-15-2026", urls=stored)
    routes = {url: (200, pdf(url)) for url in [*stored, fresh]}
    with _fetcher(routes) as fetcher:
        fetch_documents(fetcher, store)

    seed_bill(store, slug="dr-15-2026", urls=[*stored, fresh])
    messages: list[str] = []
    with _fetcher(routes) as fetcher:
        result = fetch_documents(fetcher, store, progress=messages.append)

    assert result.counts == {
        "considered": 3,
        "downloaded": 1,
        "skipped": 2,
        "failed": 0,
        "sessions_opened": 1,
        "downloaded_language_unsettled": 1,
    }
    assert messages == [
        "1 document(s) to download; 2 already stored of 3 referenced",
        "opened a ms session for 1 document(s)",
        f"[1/1] dr-15-2026/{doc_key(fresh)} (as ms)",
    ]


def seed_bill_with_languages(store: FileStore, *, slug: str, documents: list[dict]) -> None:
    store.save_bill(slug, {"identifier": {"slug": slug}, "documents": documents})


def _language_scoped_fetcher(pdfs: dict[str, bytes]) -> tuple[Fetcher, list[str]]:
    """Upstream, as observed: a document is served only to a session in the document's language.

    The mock holds one session language at a time, set by whichever warmup URL was last fetched,
    and answers every other document the way Parliament does — HTTP 200, `text/html`, and the
    twenty-three bytes `File does not exist (3)`.
    """
    session_language = {"value": "ms"}  # a cookieless client is answered as a Malay one
    order: list[str] = []
    by_language = {url: language for language, url in _session_urls().items()}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in by_language:
            session_language["value"] = by_language[url]
            order.append(f"session:{by_language[url]}")
            return httpx.Response(
                200,
                content=b"<html></html>",
                headers={"Content-Type": "text/html"},
                request=request,
            )
        wanted = "en" if url.endswith("-en.pdf") else "ms"
        if wanted != session_language["value"]:
            return httpx.Response(
                200,
                content=b"File does not exist (3)",
                headers={"Content-Type": "text/html"},
                request=request,
            )
        order.append(url)
        return httpx.Response(
            200, content=pdfs[url], headers={"Content-Type": "application/pdf"}, request=request
        )

    fetcher = Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None)
    return fetcher, order


def test_each_document_is_fetched_under_a_session_in_its_own_language(tmp_path) -> None:
    """Upstream picks the document from the session's language, not from the path: `DR 17 BI.pdf`
    is missing to a Malay session and present to an English one. A crawl that never opened a
    session was answered as a Malay one, so every English PDF came back as a soft 404 — 1,256 of
    them, which is the whole English half of the corpus.
    """
    store = FileStore(tmp_path)
    malay = "https://www.parlimen.gov.my/dr-17-ms.pdf"
    english = "https://www.parlimen.gov.my/dr-17-en.pdf"
    seed_bill_with_languages(
        store,
        slug="dr-17-2024",
        documents=[
            {"url": malay, "chamber": "dewan_rakyat", "languages": ["ms"]},
            {"url": english, "chamber": "dewan_rakyat", "languages": ["en"]},
        ],
    )
    fetcher, order = _language_scoped_fetcher({malay: pdf("ms"), english: pdf("en")})
    with fetcher:
        result = fetch_documents(fetcher, store)

    assert result.counts["downloaded"] == 2
    assert result.counts["failed"] == 0
    assert result.counts["sessions_opened"] == 2
    # A session per language, not per document: the whole run costs two extra requests.
    assert order == ["session:ms", malay, "session:en", english]
    for url in (malay, english):
        assert store.has_document(bill_slug="dr-17-2024", doc_key=doc_key(url), version=1)


def test_a_documents_recorded_language_reaches_its_stored_metadata(tmp_path) -> None:
    """The language is a permanent component of the Expression IRI (ADR-024), so the stored
    document carries the one its listing established rather than the operator's later guess."""
    store = FileStore(tmp_path)
    english = "https://www.parlimen.gov.my/dr-17-en.pdf"
    seed_bill_with_languages(
        store,
        slug="dr-17-2024",
        documents=[{"url": english, "chamber": "dewan_rakyat", "languages": ["en"]}],
    )
    fetcher, _order = _language_scoped_fetcher({english: pdf("en")})
    with fetcher:
        fetch_documents(fetcher, store)

    sidecar = tmp_path / "documents" / "dr-17-2024" / doc_key(english) / "v001" / "metadata.json"
    metadata = json.loads(sidecar.read_text())
    assert metadata["language"] == "en"
    assert metadata["source_url"] == english

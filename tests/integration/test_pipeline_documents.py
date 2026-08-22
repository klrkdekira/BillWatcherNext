"""Step 3 of the file-first pipeline: download document URLs found in bill records."""

import io

import httpx
from pypdf import PdfWriter

from billwatcher.pipeline.documents import doc_key, fetch_documents
from billwatcher.pipeline.store import FileStore
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy

POLICY = CrawlPolicy("BillWatcherNext-pipeline-test/0.1 (+https://www.parlimen.gov.my/about)")


def pdf(title: str) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


def _fetcher(routes: dict[str, tuple[int, bytes]]) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes[str(request.url)]
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
        counts = fetch_documents(fetcher, store)

    assert counts == {"considered": 2, "downloaded": 2, "skipped": 0, "failed": 0}
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
    assert first["downloaded"] == 1

    with _fetcher(routes) as fetcher:
        second = fetch_documents(fetcher, store)
    assert second == {"considered": 1, "downloaded": 0, "skipped": 1, "failed": 0}


def test_a_non_pdf_response_is_not_stored(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_bill(store, slug="dr-15-2026", urls=["https://www.parlimen.gov.my/bad.pdf"])
    routes = {"https://www.parlimen.gov.my/bad.pdf": (200, b"<html>not a pdf</html>")}

    with _fetcher(routes) as fetcher:
        counts = fetch_documents(fetcher, store)

    assert counts == {"considered": 1, "downloaded": 0, "skipped": 0, "failed": 1}
    assert list(store.iter_documents()) == []


def test_a_document_shared_by_two_bills_gets_its_own_directory_under_each(tmp_path) -> None:
    store = FileStore(tmp_path)
    shared_url = "https://www.parlimen.gov.my/shared.pdf"
    seed_bill(store, slug="dr-15-2026", urls=[shared_url])
    seed_bill(store, slug="dn-3-2026", urls=[shared_url])
    routes = {shared_url: (200, pdf("shared"))}

    with _fetcher(routes) as fetcher:
        counts = fetch_documents(fetcher, store)

    assert counts["downloaded"] == 2  # one per bill directory, legibility over dedup
    slugs = {ref.bill_slug for ref in store.iter_documents()}
    assert slugs == {"dr-15-2026", "dn-3-2026"}
    for slug in slugs:
        assert store.has_document(bill_slug=slug, doc_key=doc_key(shared_url), version=1)

"""Step 3 of the file-first pipeline: download every document URL `parse_listings` found.

PDF parsing/extraction is explicitly out of scope for this pipeline — the operator has a vLLM
OpenAI-compatible endpoint for that, separately. This step only ever produces
`documents/<bill-slug>/<doc-key>/v001/document.pdf` plus a sidecar.
"""

import hashlib
from typing import Any

from billwatcher.pipeline.store import PipelineStore
from billwatcher.scraper.fetch import Fetcher


def doc_key(url: str) -> str:
    """A path-safe identifier derived only from the document's own URL.

    There is no database here to assign an id, so the URL is what gives a document a stable
    identity across runs — the same URL always resolves to the same directory, which is what
    makes `has_document` a meaningful "already downloaded" check.
    """
    return f"doc-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def fetch_documents(fetcher: Fetcher, store: PipelineStore) -> dict[str, int]:
    """Live. One PDF per document URL, skipped if already present; no version tracking yet —
    upstream bytes changing at the same URL is a `for later` concern once the database returns.
    """
    counts = {"considered": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    for slug in store.iter_bill_slugs():
        bill = store.load_bill(slug)
        if not bill:
            continue
        for doc in bill.get("documents", []):
            url = doc.get("url")
            if not url:
                continue
            key = doc_key(url)
            counts["considered"] += 1
            if store.has_document(bill_slug=slug, doc_key=key, version=1):
                counts["skipped"] += 1
                continue
            if not _download_one(
                fetcher, store, slug=slug, key=key, url=url, chamber=doc.get("chamber")
            ):
                counts["failed"] += 1
                continue
            counts["downloaded"] += 1
    return counts


def _download_one(
    fetcher: Fetcher, store: PipelineStore, *, slug: str, key: str, url: str, chamber: Any
) -> bool:
    try:
        result = fetcher.get(url)
    except Exception:
        return False
    if result.status_code != 200 or not result.body.startswith(b"%PDF-"):
        return False
    metadata = {
        "source_url": url,
        "final_url": result.final_url,
        "retrieved_at": result.requested_at.isoformat(),
        "sha256": hashlib.sha256(result.body).hexdigest(),
        "byte_size": len(result.body),
        "bill_slug": slug,
        "chamber": chamber,
    }
    store.save_document(
        bill_slug=slug, doc_key=key, version=1, content=result.body, metadata=metadata
    )
    return True

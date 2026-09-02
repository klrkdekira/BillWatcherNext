"""`import_document`: a recovered PDF enters the store under the identity its URL already has."""

import pytest

from billwatcher.download.documents import (
    DocumentImportError,
    doc_key,
    import_document,
)
from billwatcher.store import FileStore

URL = "https://www.parlimen.gov.my/files/billindex/pdf/2006/DR12006E.pdf"
PDF = b"%PDF-1.4 recovered bytes"


def _store_with_bill(tmp_path):
    store = FileStore(tmp_path)
    store.save_bill(
        "dr-1-2006",
        {"documents": [{"url": URL, "chamber": "dewan_rakyat", "languages": ["en"]}]},
    )
    return store


def test_an_imported_document_is_stored_exactly_as_a_crawled_one(tmp_path) -> None:
    store = _store_with_bill(tmp_path)
    detail = import_document(
        store, bill_slug="dr-1-2006", url=URL, content=PDF, via="lib.perdana.org.my mirror"
    )
    key = doc_key(URL)
    assert detail["doc_key"] == key
    assert detail["language"] == "en"
    assert detail["retrieved_via"] == "lib.perdana.org.my mirror"
    assert store.load_document(bill_slug="dr-1-2006", doc_key=key, version=1) == PDF


def test_a_url_the_bill_never_named_is_refused(tmp_path) -> None:
    store = _store_with_bill(tmp_path)
    with pytest.raises(DocumentImportError, match="names no document"):
        import_document(
            store,
            bill_slug="dr-1-2006",
            url="https://example.com/other.pdf",
            content=PDF,
            via="anywhere",
        )


def test_a_file_without_pdf_magic_is_refused(tmp_path) -> None:
    store = _store_with_bill(tmp_path)
    with pytest.raises(DocumentImportError, match="magic"):
        import_document(store, bill_slug="dr-1-2006", url=URL, content=b"<html>404", via="anywhere")


def test_an_already_stored_document_is_kept_unless_replace_is_asked(tmp_path) -> None:
    store = _store_with_bill(tmp_path)
    import_document(store, bill_slug="dr-1-2006", url=URL, content=PDF, via="mirror")
    with pytest.raises(DocumentImportError, match="already stored"):
        import_document(store, bill_slug="dr-1-2006", url=URL, content=PDF, via="mirror")
    replaced = b"%PDF-1.4 a better copy"
    import_document(
        store, bill_slug="dr-1-2006", url=URL, content=replaced, via="mirror", replace=True
    )
    assert store.load_document(bill_slug="dr-1-2006", doc_key=doc_key(URL), version=1) == replaced

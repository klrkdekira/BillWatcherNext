import hashlib

from billwatcher.storage.blobs import FilesystemBlobStore


def test_content_addressed_blob_round_trip_and_deduplication(tmp_path) -> None:
    store = FilesystemBlobStore(tmp_path)
    first = store.put(b"immutable", compress=True)
    second = store.put(b"immutable", compress=True)
    assert first == second
    assert first.location == str(tmp_path / first.sha256[:2] / first.sha256[2:4] / first.sha256)
    assert store.get(first.sha256, compression="gzip") == b"immutable"
    assert store.verify(first.sha256, compression="gzip")
    assert first.sha256 == hashlib.sha256(b"immutable").hexdigest()


def test_invalid_digest_cannot_become_a_path(tmp_path) -> None:
    store = FilesystemBlobStore(tmp_path)
    try:
        store.path_for("../../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid digest accepted")


def test_storage_enumeration_reports_only_valid_layout(tmp_path) -> None:
    store = FilesystemBlobStore(tmp_path)
    stored = store.put(b"known")
    invalid = tmp_path / "not-a-layout"
    invalid.write_text("ignored")
    assert store.stored_digests() == {stored.sha256}

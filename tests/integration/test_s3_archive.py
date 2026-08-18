"""The S3 archive backend against a real VersityGW (ADR-013).

These run only when BILLWATCHER_TEST_S3_ENDPOINT points at a gateway, and skip with a clear
message otherwise. The point is that the two backends are interchangeable: the same contract,
the same content-addressed layout, the same guarantees.
"""

import gzip
import hashlib

import pytest

from billwatcher.config import Settings
from billwatcher.storage import build_blob_store
from billwatcher.storage.blobs import (
    BlobNotFound,
    FilesystemBlobStore,
    S3BlobStore,
    relative_key,
)

PDF = b"%PDF-1.7\narchived bill bytes\n%%EOF"
DIGEST = hashlib.sha256(PDF).hexdigest()


def test_the_key_layout_matches_the_filesystem_layout() -> None:
    assert relative_key(DIGEST) == f"{DIGEST[:2]}/{DIGEST[2:4]}/{DIGEST}"
    with pytest.raises(ValueError, match="invalid SHA-256 digest"):
        relative_key("../../escape")


def test_the_factory_defaults_to_the_filesystem(tmp_path) -> None:
    store = build_blob_store(Settings(blob_storage_root=tmp_path))
    assert isinstance(store, FilesystemBlobStore)


def test_selecting_s3_without_credentials_is_refused() -> None:
    with pytest.raises(ValueError, match="requires S3_ENDPOINT_URL"):
        Settings(blob_storage_backend="s3")


def test_round_trip_through_versity(versity_store: S3BlobStore) -> None:
    stored = versity_store.put(PDF)
    assert stored.sha256 == DIGEST
    assert stored.byte_size == len(PDF)
    assert stored.location == f"s3://{versity_store.bucket}/{relative_key(DIGEST)}"
    assert versity_store.get(DIGEST) == PDF
    assert versity_store.verify(DIGEST)


def test_identical_bytes_are_stored_once(versity_store: S3BlobStore) -> None:
    first = versity_store.put(PDF)
    second = versity_store.put(PDF)
    assert first == second
    assert versity_store.stored_digests() == {DIGEST}


def test_compressed_blobs_round_trip(versity_store: S3BlobStore) -> None:
    body = b"<html>a listing snapshot</html>"
    stored = versity_store.put(body, compress=True)
    assert stored.compression == "gzip"
    assert versity_store.get(stored.sha256, compression="gzip") == body


def test_a_missing_blob_raises_rather_than_returning_nothing(versity_store: S3BlobStore) -> None:
    with pytest.raises(BlobNotFound):
        versity_store.get("0" * 64)
    assert not versity_store.verify("0" * 64)


def test_corrupted_bytes_fail_verification(versity_store: S3BlobStore) -> None:
    versity_store.put(PDF)
    # Overwrite the object out of band with content that does not match its address.
    versity_store._client.put_object(
        Bucket=versity_store.bucket, Key=relative_key(DIGEST), Body=b"tampered"
    )
    assert not versity_store.verify(DIGEST)
    with pytest.raises(OSError, match="hash mismatch"):
        versity_store.get(DIGEST)


def test_streaming_yields_the_whole_verified_blob(versity_store: S3BlobStore) -> None:
    body = b"x" * (600 * 1024)
    stored = versity_store.put(body)
    chunks = list(versity_store.stream(stored.sha256))
    assert len(chunks) > 1
    assert b"".join(chunks) == body


def test_enumeration_ignores_keys_that_are_not_content_addressed(
    versity_store: S3BlobStore,
) -> None:
    versity_store.put(PDF)
    versity_store._client.put_object(
        Bucket=versity_store.bucket, Key="notes/readme.txt", Body=b"not a blob"
    )
    assert versity_store.stored_digests() == {DIGEST}


def test_delete_removes_only_the_named_blob(versity_store: S3BlobStore) -> None:
    other = versity_store.put(b"another document")
    versity_store.put(PDF)
    versity_store.delete(DIGEST)
    assert versity_store.stored_digests() == {other.sha256}


def test_both_backends_agree_on_layout_and_content(versity_store: S3BlobStore, tmp_path) -> None:
    """A gateway pointed at an existing blob volume must see the files already there."""
    filesystem = FilesystemBlobStore(tmp_path)
    on_disk = filesystem.put(PDF)
    in_s3 = versity_store.put(PDF)

    assert on_disk.sha256 == in_s3.sha256
    assert on_disk.compression == in_s3.compression
    assert filesystem.get(DIGEST) == versity_store.get(DIGEST) == PDF
    # The relative layout is identical; only the root differs.
    assert on_disk.location.endswith(relative_key(DIGEST))
    assert in_s3.location.endswith(relative_key(DIGEST))
    assert gzip.decompress(gzip.compress(PDF, mtime=0)) == PDF

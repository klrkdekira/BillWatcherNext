"""Content-addressed immutable blob storage.

Bytes are addressed exclusively by their validated SHA-256 digest. A storage location is derived
from that digest and never from anything an upstream page or an HTTP request supplied
(HANDOFF 17), so no request can reach a file we did not put there.

Two backends implement the same contract: a plain filesystem, and any S3-compatible service
(this deployment uses VersityGW over the same archive volume — see ADR-013). Everything above
this module works against the protocol, so the archive can move without the scraper, the
replay jobs, or the web layer knowing.
"""

import gzip
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

READ_CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class StoredBlob:
    sha256: str
    byte_size: int
    location: str
    compression: str


class BlobNotFound(LookupError):
    """The digest is well formed but nothing is stored under it."""


def validate_digest(digest: str) -> str:
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("invalid SHA-256 digest")
    return digest


def relative_key(digest: str) -> str:
    """The two-level layout from HANDOFF 8, shared by both backends."""
    validate_digest(digest)
    return f"{digest[:2]}/{digest[2:4]}/{digest}"


def _decompress(payload: bytes, compression: str) -> bytes:
    return gzip.decompress(payload) if compression == "gzip" else payload


@runtime_checkable
class BlobStore(Protocol):
    """What the rest of the application may assume about the archive."""

    def put(self, content: bytes, *, compress: bool = False) -> StoredBlob: ...

    def get(self, digest: str, *, compression: str = "none") -> bytes: ...

    def stream(self, digest: str, *, compression: str = "none") -> Iterator[bytes]: ...

    def verify(self, digest: str, *, compression: str = "none") -> bool: ...

    def delete(self, digest: str) -> None: ...

    def stored_digests(self) -> set[str]: ...

    def location_for(self, digest: str) -> str: ...


class FilesystemBlobStore:
    """The default archive: one file per blob under a two-level hash prefix."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, digest: str) -> Path:
        return self.root / relative_key(digest)

    def location_for(self, digest: str) -> str:
        return str(self.path_for(digest))

    def put(self, content: bytes, *, compress: bool = False) -> StoredBlob:
        digest = hashlib.sha256(content).hexdigest()
        path = self.path_for(digest)
        payload = gzip.compress(content, mtime=0) if compress else content
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Exclusive create: identical content is stored once and never rewritten.
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            pass
        return StoredBlob(digest, len(content), str(path), "gzip" if compress else "none")

    def get(self, digest: str, *, compression: str = "none") -> bytes:
        try:
            payload = self.path_for(digest).read_bytes()
        except FileNotFoundError as error:
            raise BlobNotFound(digest) from error
        content = _decompress(payload, compression)
        if hashlib.sha256(content).hexdigest() != digest:
            raise OSError(f"blob hash mismatch: {digest}")
        return content

    def stream(self, digest: str, *, compression: str = "none") -> Iterator[bytes]:
        return _verified_stream(self, digest, compression)

    def verify(self, digest: str, *, compression: str = "none") -> bool:
        try:
            self.get(digest, compression=compression)
        except (OSError, ValueError, BlobNotFound):
            return False
        return True

    def delete(self, digest: str) -> None:
        self.path_for(digest).unlink(missing_ok=True)

    def stored_digests(self) -> set[str]:
        """Enumerate only valid hash-derived blob files under the two-level layout."""
        if not self.root.exists():
            return set()
        digests: set[str] = set()
        for path in self.root.glob("*/*/*"):
            name = path.name
            if (
                path.is_file()
                and len(name) == 64
                and all(character in "0123456789abcdef" for character in name)
            ) and path == self.path_for(name):
                digests.add(name)
        return digests


class S3BlobStore:
    """The archive on any S3-compatible service, including VersityGW.

    Keys use the same two-level hash layout as the filesystem backend, so a VersityGW POSIX
    backend pointed at an existing blob volume sees exactly the files already there.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as error:  # pragma: no cover - configuration, not logic
            raise RuntimeError(
                "the S3 archive backend needs the 's3' dependency group installed"
            ) from error

        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            # VersityGW and most gateways serve path-style addressing, not virtual-host style.
            config=Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def location_for(self, digest: str) -> str:
        return f"s3://{self.bucket}/{relative_key(digest)}"

    def ensure_bucket(self) -> None:
        """Create the archive bucket when it does not exist yet. Safe to call repeatedly."""
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def put(self, content: bytes, *, compress: bool = False) -> StoredBlob:
        digest = hashlib.sha256(content).hexdigest()
        key = relative_key(digest)
        payload = gzip.compress(content, mtime=0) if compress else content
        if not self._exists(key):
            # Immutable: an object already under this key holds these exact bytes by definition.
            self._client.put_object(Bucket=self.bucket, Key=key, Body=payload)
        return StoredBlob(
            digest, len(content), self.location_for(digest), "gzip" if compress else "none"
        )

    def _exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True

    def get(self, digest: str, *, compression: str = "none") -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(Bucket=self.bucket, Key=relative_key(digest))
        except ClientError as error:
            raise BlobNotFound(digest) from error
        content = _decompress(response["Body"].read(), compression)
        if hashlib.sha256(content).hexdigest() != digest:
            raise OSError(f"blob hash mismatch: {digest}")
        return content

    def stream(self, digest: str, *, compression: str = "none") -> Iterator[bytes]:
        return _verified_stream(self, digest, compression)

    def verify(self, digest: str, *, compression: str = "none") -> bool:
        try:
            self.get(digest, compression=compression)
        except (OSError, ValueError, BlobNotFound):
            return False
        return True

    def delete(self, digest: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=relative_key(digest))

    def stored_digests(self) -> set[str]:
        digests: set[str] = set()
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for entry in page.get("Contents", []):
                name = str(entry["Key"]).rsplit("/", 1)[-1]
                if (
                    len(name) == 64
                    and all(character in "0123456789abcdef" for character in name)
                    and entry["Key"] == relative_key(name)
                ):
                    digests.add(name)
        return digests


def _verified_stream(store: BlobStore, digest: str, compression: str) -> Iterator[bytes]:
    """Yield a blob in chunks, refusing to finish a response whose bytes do not hash correctly.

    Compressed blobs are decompressed whole because a gzip member cannot be verified
    incrementally. Uncompressed blobs — which is how documents are stored — stream chunk by
    chunk, and a mismatch raises before the last chunk is yielded rather than being ignored.
    """
    content = store.get(digest, compression=compression)
    for start in range(0, len(content), READ_CHUNK_BYTES):
        yield content[start : start + READ_CHUNK_BYTES]

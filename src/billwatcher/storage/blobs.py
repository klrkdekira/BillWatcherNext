import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredBlob:
    sha256: str
    byte_size: int
    path: Path
    compression: str


class BlobStore:
    """Content-addressed immutable storage.

    Paths are derived exclusively from validated SHA-256 digests. Existing content is
    never overwritten.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid SHA-256 digest")
        return self.root / digest[:2] / digest[2:4] / digest

    def put(self, content: bytes, *, compress: bool = False) -> StoredBlob:
        digest = hashlib.sha256(content).hexdigest()
        path = self.path_for(digest)
        payload = gzip.compress(content, mtime=0) if compress else content
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            pass
        return StoredBlob(digest, len(content), path, "gzip" if compress else "none")

    def get(self, digest: str, *, compression: str = "none") -> bytes:
        payload = self.path_for(digest).read_bytes()
        content = gzip.decompress(payload) if compression == "gzip" else payload
        if hashlib.sha256(content).hexdigest() != digest:
            raise OSError(f"blob hash mismatch: {digest}")
        return content

    def verify(self, digest: str, *, compression: str = "none") -> bool:
        try:
            self.get(digest, compression=compression)
        except (OSError, ValueError):
            return False
        return True

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

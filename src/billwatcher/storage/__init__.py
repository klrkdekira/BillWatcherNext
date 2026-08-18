"""Archive storage."""

from billwatcher.config import Settings
from billwatcher.storage.blobs import BlobStore, FilesystemBlobStore, S3BlobStore


def build_blob_store(settings: Settings) -> BlobStore:
    """Resolve the configured archive backend. The caller never picks an implementation."""
    if settings.blob_storage_backend == "s3":
        return S3BlobStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
        )
    return FilesystemBlobStore(settings.blob_storage_root)

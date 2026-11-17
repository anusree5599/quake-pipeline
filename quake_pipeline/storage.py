"""Cloud object storage backends: Google Cloud Storage, AWS S3, and a local
folder that mimics a bucket (for offline testing only).

The backend is chosen with the STORAGE_BACKEND environment variable.
Credentials are never read from this repository - each SDK uses its
standard credential chain (gcloud ADC / service account for GCS,
~/.aws/credentials or AWS_* env vars for S3).
"""

from __future__ import annotations

import os
from pathlib import Path

CONTENT_TYPES = {
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".csv": "text/csv",
    ".html": "text/html; charset=utf-8",
}


def _content_type(path: str) -> str:
    return CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


class StorageBackend:
    name = "base"

    def upload(self, local_path: str, key: str) -> str:  # pragma: no cover
        raise NotImplementedError


class GCSBackend(StorageBackend):
    name = "gcs"

    def __init__(self, bucket: str):
        from google.cloud import storage  # imported lazily so S3 users don't need it

        self.bucket_name = bucket
        self.bucket = storage.Client().bucket(bucket)

    def upload(self, local_path: str, key: str) -> str:
        blob = self.bucket.blob(key)
        blob.upload_from_filename(local_path, content_type=_content_type(local_path))
        return f"gs://{self.bucket_name}/{key}"


class S3Backend(StorageBackend):
    name = "s3"

    def __init__(self, bucket: str, region: str | None = None):
        import boto3

        self.bucket_name = bucket
        self.client = boto3.client("s3", region_name=region)

    def upload(self, local_path: str, key: str) -> str:
        self.client.upload_file(
            local_path, self.bucket_name, key,
            ExtraArgs={"ContentType": _content_type(local_path)},
        )
        return f"s3://{self.bucket_name}/{key}"


class LocalBackend(StorageBackend):
    """Copies files into ./output/bucket/. Not cloud storage - offline testing only."""

    name = "local"

    def __init__(self, root: str = "output/bucket"):
        self.root = Path(root)

    def upload(self, local_path: str, key: str) -> str:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(local_path).read_bytes())
        return f"file://{dest.resolve()}"


def get_backend() -> StorageBackend:
    backend = os.getenv("STORAGE_BACKEND", "gcs").strip().lower()
    if backend == "gcs":
        bucket = os.getenv("GCS_BUCKET")
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND=gcs but GCS_BUCKET is not set (see .env.example)")
        return GCSBackend(bucket)
    if backend == "s3":
        bucket = os.getenv("S3_BUCKET")
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 but S3_BUCKET is not set (see .env.example)")
        return S3Backend(bucket, os.getenv("AWS_REGION"))
    if backend == "local":
        return LocalBackend()
    raise RuntimeError(f"Unknown STORAGE_BACKEND '{backend}'. Use gcs, s3 or local.")

"""Optional S3 / MinIO object storage backend for EXTENDED deployment profile."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.app.storage.base import StorageBackend, StorageObjectMeta


def _to_utc_naive(dt: Any) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    return datetime.now(timezone.utc).replace(tzinfo=None)


class S3StorageBackend(StorageBackend):
    """S3-compatible StorageBackend targeting MinIO or AWS S3 (requires boto3)."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region_name: str = "us-east-1",
    ):
        try:
            import boto3  # type: ignore
            from botocore.exceptions import ClientError  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "S3StorageBackend requires optional dependency 'boto3' (pip install -r requirements-extended.txt)."
            ) from exc

        self._client_error = ClientError
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        )
        # Ensure bucket exists on MinIO/S3 (only create on 404/NoSuchBucket)
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in ("404", "NoSuchBucket", "NotFound") or status_code == 404:
                self.client.create_bucket(Bucket=self.bucket)
            else:
                raise

    def resolve_uri(self, key: str) -> str:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        return f"s3://{self.bucket}/{clean_key}"

    def write_bytes(self, key: str, data: bytes) -> int:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        self.client.put_object(Bucket=self.bucket, Key=clean_key, Body=data)
        return len(data)

    def read_bytes(self, key: str) -> bytes:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        obj = self.client.get_object(Bucket=self.bucket, Key=clean_key)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        return self.head_object(key) is not None

    def head_object(self, key: str) -> Optional[StorageObjectMeta]:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        try:
            resp = self.client.head_object(Bucket=self.bucket, Key=clean_key)
            etag = resp.get("ETag")
            return StorageObjectMeta(
                key=clean_key,
                size_bytes=int(resp.get("ContentLength", 0)),
                last_modified_utc=_to_utc_naive(resp.get("LastModified")),
                etag=etag.strip('"') if isinstance(etag, str) else None,
            )
        except self._client_error as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in ("404", "NoSuchKey", "NotFound") or status_code == 404:
                return None
            raise

    def list_objects(self, prefix: str = "", suffix: str = "") -> List[StorageObjectMeta]:
        clean_prefix = prefix.lstrip("/\\").replace("\\", "/")
        objs: List[StorageObjectMeta] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=clean_prefix):
            for obj in page.get("Contents", []):
                k = obj["Key"]
                if suffix and not k.endswith(suffix):
                    continue
                etag = obj.get("ETag")
                objs.append(StorageObjectMeta(
                    key=k,
                    size_bytes=int(obj.get("Size", 0)),
                    last_modified_utc=_to_utc_naive(obj.get("LastModified")),
                    etag=etag.strip('"') if isinstance(etag, str) else None,
                ))
        objs.sort(key=lambda o: o.key)
        return objs

    def list_keys(self, prefix: str = "", suffix: str = "") -> List[str]:
        return [o.key for o in self.list_objects(prefix=prefix, suffix=suffix)]

    def delete(self, key: str) -> bool:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        self.client.delete_object(Bucket=self.bucket, Key=clean_key)
        return True

    def stat_prefix(self, prefix: str = "") -> Dict[str, Any]:
        objs = self.list_objects(prefix=prefix)
        total_bytes = sum(o.size_bytes for o in objs)
        oldest = min((o.last_modified_utc.replace(tzinfo=timezone.utc).timestamp() for o in objs), default=None)
        newest = max((o.last_modified_utc.replace(tzinfo=timezone.utc).timestamp() for o in objs), default=None)
        return {
            "prefix": prefix,
            "file_count": len(objs),
            "total_bytes": total_bytes,
            "oldest_mtime": oldest,
            "newest_mtime": newest,
        }

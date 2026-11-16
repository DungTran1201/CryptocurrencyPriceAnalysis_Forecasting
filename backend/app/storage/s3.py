"""Optional S3 / MinIO object storage backend for EXTENDED deployment profile."""

from typing import List, Dict, Any, Optional
from backend.app.storage.base import StorageBackend


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
        except ImportError as exc:
            raise RuntimeError(
                "S3StorageBackend requires optional dependency 'boto3' (pip install -r requirements-extended.txt)."
            ) from exc

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        )
        # Ensure bucket exists on MinIO/S3
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

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
        clean_key = key.lstrip("/\\").replace("\\", "/")
        try:
            self.client.head_object(Bucket=self.bucket, Key=clean_key)
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str = "", suffix: str = "") -> List[str]:
        clean_prefix = prefix.lstrip("/\\").replace("\\", "/")
        keys: List[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=clean_prefix):
            for obj in page.get("Contents", []):
                k = obj["Key"]
                if not suffix or k.endswith(suffix):
                    keys.append(k)
        keys.sort()
        return keys

    def delete(self, key: str) -> bool:
        clean_key = key.lstrip("/\\").replace("\\", "/")
        self.client.delete_object(Bucket=self.bucket, Key=clean_key)
        return True

    def stat_prefix(self, prefix: str = "") -> Dict[str, Any]:
        clean_prefix = prefix.lstrip("/\\").replace("\\", "/")
        count = 0
        total_bytes = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=clean_prefix):
            for obj in page.get("Contents", []):
                count += 1
                total_bytes += int(obj.get("Size", 0))
        return {
            "prefix": prefix,
            "file_count": count,
            "total_bytes": total_bytes,
            "oldest_mtime": None,
            "newest_mtime": None,
        }


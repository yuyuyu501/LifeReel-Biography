from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

import boto3
from botocore.config import Config as BotoConfig

from lifereel_api.core.config import get_settings


class LocalPrivateStorage:
    def signed_url(self, storage_key: str) -> str | None:
        return None

    def __init__(self) -> None:
        self.root = Path(get_settings().local_storage_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, storage_key: str, content: BinaryIO) -> None:
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents:
            raise ValueError("STORAGE_KEY_INVALID")
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                shutil.copyfileobj(content, temporary, length=1024 * 1024)
            temporary_path.replace(target)
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    def put(self, storage_key: str, content: bytes) -> None:
        from io import BytesIO

        self.put_file(storage_key, BytesIO(content))

    def get(self, storage_key: str) -> bytes:
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents or not target.is_file():
            raise FileNotFoundError(storage_key)
        return target.read_bytes()

    def iter_range(
        self, storage_key: str, start: int, end: int, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]:
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents or not target.is_file():
            raise FileNotFoundError(storage_key)
        remaining = end - start + 1
        with target.open("rb") as content:
            content.seek(start)
            while remaining > 0:
                chunk = content.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk


class S3PrivateStorage:
    def signed_url(self, storage_key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": storage_key}, ExpiresIn=3600,
        )

    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region_name,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": settings.s3_addressing_style},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def put_file(self, storage_key: str, content: BinaryIO) -> None:
        try:
            self.client.head_object(Bucket=self.bucket, Key=storage_key)
            return
        except self.client.exceptions.ClientError:
            settings = get_settings()
            options = (
                {"ServerSideEncryption": settings.s3_server_side_encryption}
                if settings.s3_server_side_encryption
                else {}
            )
            self.client.upload_fileobj(
                content,
                self.bucket,
                storage_key,
                ExtraArgs=options,
            )

    def put(self, storage_key: str, content: bytes) -> None:
        from io import BytesIO

        self.put_file(storage_key, BytesIO(content))

    def get(self, storage_key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=storage_key)
        return response["Body"].read()

    def iter_range(
        self, storage_key: str, start: int, end: int, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]:
        response = self.client.get_object(
            Bucket=self.bucket,
            Key=storage_key,
            Range=f"bytes={start}-{end}",
        )
        content = response["Body"]
        try:
            while chunk := content.read(chunk_size):
                yield chunk
        finally:
            content.close()


def private_storage():
    return S3PrivateStorage() if get_settings().storage_backend == "s3" else LocalPrivateStorage()

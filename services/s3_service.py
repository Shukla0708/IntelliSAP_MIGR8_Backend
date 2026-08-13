"""File storage for validation source/result workbooks.

Uses local disk when AWS keys look like placeholders (hackathon / no AWS).
Set STORAGE_BACKEND=s3 with real credentials to use S3.
"""

from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.config import Config

from config import settings

_PLACEHOLDER_KEYS = {"", "your-key", "your-secret", "changeme"}


def _use_local() -> bool:
    backend = (settings.storage_backend or "auto").lower()
    if backend == "local":
        return True
    if backend == "s3":
        return False
    # auto: local unless real-looking AWS keys are present
    return (
        settings.aws_access_key_id in _PLACEHOLDER_KEYS
        or settings.aws_secret_access_key in _PLACEHOLDER_KEYS
    )


LOCAL_ROOT = Path(__file__).resolve().parent.parent / "local_storage"


def _local_path(key: str) -> Path:
    # Keep S3-style keys as relative paths under local_storage/
    path = LOCAL_ROOT / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(signature_version="s3v4"),
    )


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    if _use_local():
        _local_path(key).write_bytes(data)
        return
    _s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


def download_bytes(key: str) -> bytes:
    if _use_local():
        path = _local_path(key)
        if not path.is_file():
            raise FileNotFoundError(f"Local object not found: {key}")
        return path.read_bytes()
    return _s3_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def presigned_url(key: str, expires: int = 3600) -> str:
    if _use_local():
        # Served by GET /api/local-files/{key} on this API
        base = settings.public_api_base_url.rstrip("/")
        return f"{base}/api/local-files/{quote(key, safe='')}"
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires,
    )


def storage_mode() -> str:
    return "local" if _use_local() else "s3"

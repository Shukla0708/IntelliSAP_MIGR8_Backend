"""File storage for validation source/result workbooks.

Uses local disk when STORAGE_BACKEND=auto and no AWS credentials are available.
Set STORAGE_BACKEND=s3 on EC2 — uses IAM instance role via boto3 default chain.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote

from config import settings
from services.aws_client import _has_explicit_credentials, get_s3_client


def _use_local() -> bool:
    backend = (settings.storage_backend or "auto").lower()
    if backend == "local":
        return True
    if backend == "s3":
        return False
    if _has_explicit_credentials():
        return False
    try:
        import boto3
        session = boto3.Session()
        creds = session.get_credentials()
        if creds and creds.access_key:
            return False
    except Exception:
        pass
    return True


LOCAL_ROOT = Path(__file__).resolve().parent.parent / "local_storage"


def _local_path(key: str) -> Path:
    path = LOCAL_ROOT / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    if _use_local():
        _local_path(key).write_bytes(data)
        return
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )


def upload_fileobj(key: str, fileobj: BinaryIO, content_type: str) -> Path | None:
    """Stream a file-like object to storage. Returns the local path when using disk."""
    if _use_local():
        path = _local_path(key)
        with path.open("wb") as dest:
            shutil.copyfileobj(fileobj, dest)
        return path
    get_s3_client().upload_fileobj(
        fileobj,
        settings.s3_bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return None


def download_bytes(key: str) -> bytes:
    if _use_local():
        path = _local_path(key)
        if not path.is_file():
            raise FileNotFoundError(f"Local object not found: {key}")
        return path.read_bytes()
    return get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def local_path_if_exists(key: str) -> Path | None:
    if not _use_local():
        return None
    path = LOCAL_ROOT / key
    return path if path.is_file() else None


def download_to_path(key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _use_local():
        src = LOCAL_ROOT / key
        if not src.is_file():
            raise FileNotFoundError(f"Local object not found: {key}")
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
        return dest
    get_s3_client().download_file(settings.s3_bucket, key, str(dest))
    return dest


def download_to_temp(key: str, suffix: str = "") -> Path:
    handle, name = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    Path(name).unlink(missing_ok=True)
    return download_to_path(key, Path(name))


def presigned_url(key: str, expires: int | None = None) -> str:
    ttl = expires if expires is not None else settings.s3_presign_ttl_seconds
    if _use_local():
        base = settings.public_api_base_url.rstrip("/")
        return f"{base}/api/local-files/{quote(key, safe='')}"
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=ttl,
    )


def storage_mode() -> str:
    return "local" if _use_local() else "s3"

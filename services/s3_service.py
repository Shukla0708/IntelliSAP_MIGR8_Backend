"""File storage for validation source/result workbooks.

Uses local disk when STORAGE_BACKEND=auto and no AWS credentials are available.
Set STORAGE_BACKEND=s3 on EC2 — uses IAM instance role via boto3 default chain.
"""

from pathlib import Path
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


def download_bytes(key: str) -> bytes:
    if _use_local():
        path = _local_path(key)
        if not path.is_file():
            raise FileNotFoundError(f"Local object not found: {key}")
        return path.read_bytes()
    return get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def presigned_url(key: str, expires: int = 3600) -> str:
    if _use_local():
        base = settings.public_api_base_url.rstrip("/")
        return f"{base}/api/local-files/{quote(key, safe='')}"
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires,
    )


def storage_mode() -> str:
    return "local" if _use_local() else "s3"

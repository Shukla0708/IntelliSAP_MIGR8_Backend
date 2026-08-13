"""Shared boto3 clients — IAM keys, Bedrock API key, or EC2 instance role."""

import os

import boto3
import certifi
from botocore.config import Config

from config import settings


def _ssl_verify():
    """botocore's bundled CA file misses some issuers on Windows/Python 3.12."""
    if os.environ.get("AWS_CA_BUNDLE"):
        return os.environ["AWS_CA_BUNDLE"]
    return certifi.where()

_PLACEHOLDER_KEYS = {"", "your-key", "your-secret", "changeme", None}


def _has_explicit_credentials() -> bool:
    key = settings.aws_access_key_id
    secret = settings.aws_secret_access_key
    return (
        key not in _PLACEHOLDER_KEYS
        and secret not in _PLACEHOLDER_KEYS
        and bool(key)
        and bool(secret)
    )


def _has_bedrock_api_key() -> bool:
    key = (settings.bedrock_access_key or "").strip()
    return bool(key) and key not in _PLACEHOLDER_KEYS


def get_boto_client(service_name: str, *, signature_version: str | None = None):
    kwargs: dict = {"region_name": settings.aws_region, "verify": _ssl_verify()}
    if _has_explicit_credentials():
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    if signature_version:
        kwargs["config"] = Config(signature_version=signature_version)
    return boto3.client(service_name, **kwargs)


def get_s3_client():
    return get_boto_client("s3", signature_version="s3v4")


def get_bedrock_runtime_client():
    """Bedrock boto3 client — uses BEDROCK_REGION, not AWS_REGION."""
    if _has_bedrock_api_key():
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = settings.bedrock_access_key.strip()
    kwargs: dict = {"region_name": settings.bedrock_region, "verify": _ssl_verify()}
    if _has_explicit_credentials():
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("bedrock-runtime", **kwargs)

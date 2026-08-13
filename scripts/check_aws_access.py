"""Local connectivity check for AWS, S3, Bedrock, and Postgres.

Usage (from backend root):
    python scripts/check_aws_access.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from backend root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from services.aws_client import _has_explicit_credentials, get_bedrock_runtime_client, get_s3_client
from services import s3_service


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def check_aws_identity() -> bool:
    print("\n1) AWS credentials (STS GetCallerIdentity)")
    try:
        import boto3
        session = boto3.Session(region_name=settings.aws_region)
        creds = session.get_credentials()
        if not creds:
            fail("No AWS credentials found (env, ~/.aws/credentials, or IAM role)")
            return False
        source = "explicit keys" if _has_explicit_credentials() else "default credential chain"
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        ok(f"Authenticated via {source}")
        ok(f"Account: {identity.get('Account')}")
        ok(f"ARN: {identity.get('Arn')}")
        return True
    except Exception as exc:
        fail(str(exc))
        return False


def check_s3() -> bool:
    print("\n2) S3 bucket access")
    bucket = settings.s3_bucket
    print(f"     Bucket: {bucket}  Region: {settings.aws_region}")
    print(f"     STORAGE_BACKEND={settings.storage_backend}  resolved mode: {s3_service.storage_mode()}")
    try:
        client = get_s3_client()
        client.head_bucket(Bucket=bucket)
        ok(f"head_bucket succeeded for {bucket}")

        test_key = "_healthcheck/migr8-write-test.txt"
        client.put_object(Bucket=bucket, Key=test_key, Body=b"ok", ContentType="text/plain")
        ok(f"put_object succeeded ({test_key})")
        client.delete_object(Bucket=bucket, Key=test_key)
        ok("delete_object succeeded (cleanup)")
        return True
    except Exception as exc:
        fail(str(exc))
        return False


def check_bedrock() -> bool:
    print("\n3) Bedrock Converse API")
    model_id = settings.bedrock_model_id
    print(f"     Model: {model_id}")
    try:
        client = get_bedrock_runtime_client()
        resp = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "Reply with exactly: OK"}]}],
            inferenceConfig={"maxTokens": 10, "temperature": 0},
        )
        text = resp["output"]["message"]["content"][0]["text"].strip()
        ok(f"converse succeeded — response: {text[:80]!r}")
        return True
    except Exception as exc:
        fail(str(exc))
        warn("Ensure model access is enabled in Bedrock console for your region")
        return False


def check_bedrock_embed() -> bool:
    print("\n3b) Bedrock Cohere Embed v4")
    print(f"     Model: {settings.bedrock_embed_model_id}")
    try:
        from services import embedding_service
        matrix = embedding_service.embed_texts(["customer name", "order date"])
        ok(f"embed_texts succeeded — shape {matrix.shape}")
        return True
    except Exception as exc:
        fail(str(exc))
        warn("Enable Cohere Embed v4 (cohere.embed-v4:0) in Bedrock model access")
        return False


def check_database() -> bool:
    print("\n4) PostgreSQL (DATABASE_URL)")
    url = settings.database_url
    # Mask password in display
    display = url
    if "@" in url and "://" in url:
        prefix, rest = url.split("://", 1)
        if "@" in rest:
            creds, hostpart = rest.split("@", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                display = f"{prefix}://{user}:****@{hostpart}"
    print(f"     URL: {display}")
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT 1")).scalar()
        ok(f"Connected — SELECT 1 => {row}")
        return True
    except Exception as exc:
        fail(str(exc))
        return False


def main() -> int:
    print("MIGR8 AWS / Bedrock / S3 / DB connectivity check")
    print("=" * 50)

    results = [
        check_aws_identity(),
        check_s3(),
        check_bedrock(),
        check_bedrock_embed(),
        check_database(),
    ]

    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"Result: {passed}/{total} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

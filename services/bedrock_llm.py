"""AWS Bedrock Converse API wrapper for structured LLM tasks."""

import json

import httpx

from config import settings
from services.aws_client import _has_bedrock_api_key, get_bedrock_runtime_client


def strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _converse_url() -> str:
    region = settings.bedrock_region
    model_id = settings.bedrock_model_id
    return (
        f"https://bedrock-runtime.{region}.amazonaws.com"
        f"/model/{model_id}/converse"
    )


def _parse_converse_response(data: dict) -> str:
    output = data.get("output", {}).get("message", {}).get("content", [])
    if not output:
        raise ValueError("Bedrock returned an empty response")
    # Sonnet 5 may return reasoningContent first, then the actual text block.
    parts: list[str] = []
    for block in output:
        text = block.get("text")
        if text:
            parts.append(text.strip())
    if not parts:
        raise ValueError("Bedrock returned an empty response")
    return "\n".join(parts)


def _inference_config(max_tokens: int) -> dict:
    """Claude Sonnet 5 rejects deprecated `temperature` in inferenceConfig."""
    return {"maxTokens": max_tokens}


def _chat_via_api_key(system: str, user: str, *, max_tokens: int) -> str:
    """Call Bedrock Converse REST API with BEDROCK_ACCESS_KEY bearer token."""
    payload = {
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": _inference_config(max_tokens),
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.bedrock_access_key.strip()}",
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(_converse_url(), json=payload, headers=headers)
            resp.raise_for_status()
            return _parse_converse_response(resp.json())
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise ValueError(
            f"Bedrock API error {exc.response.status_code} for model "
            f"{settings.bedrock_model_id}: {body}"
        ) from exc
    except Exception as exc:
        raise ValueError(
            f"Bedrock invoke failed for model {settings.bedrock_model_id}: {exc}"
        ) from exc


def _chat_via_boto3(system: str, user: str, *, max_tokens: int) -> str:
    client = get_bedrock_runtime_client()
    try:
        resp = client.converse(
            modelId=settings.bedrock_model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig=_inference_config(max_tokens),
        )
    except Exception as exc:
        raise ValueError(
            f"Bedrock invoke failed for model {settings.bedrock_model_id}: {exc}"
        ) from exc
    return _parse_converse_response(resp)


def chat(system: str, user: str, *, max_tokens: int, temperature: float = 0) -> str:
    """Send a system + user message to Bedrock and return the assistant text."""
    del temperature  # Sonnet 5 does not accept temperature in inferenceConfig
    if _has_bedrock_api_key():
        return _chat_via_api_key(system, user, max_tokens=max_tokens)
    return _chat_via_boto3(system, user, max_tokens=max_tokens)

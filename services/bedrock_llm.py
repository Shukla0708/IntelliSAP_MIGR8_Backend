"""AWS Bedrock Converse API wrapper for structured LLM tasks."""

from __future__ import annotations

import json
import logging
import time

import httpx

from config import settings
from services.aws_client import _has_bedrock_api_key, get_bedrock_runtime_client
from services import llm_cache, llm_usage

logger = logging.getLogger(__name__)


def strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _converse_url(model_id: str) -> str:
    region = settings.bedrock_region
    return (
        f"https://bedrock-runtime.{region}.amazonaws.com"
        f"/model/{model_id}/converse"
    )


def _parse_converse_response(data: dict) -> tuple[str, int, int]:
    output = data.get("output", {}).get("message", {}).get("content", [])
    if not output:
        raise ValueError("Bedrock returned an empty response")
    parts: list[str] = []
    for block in output:
        text = block.get("text")
        if text:
            parts.append(text.strip())
    if not parts:
        raise ValueError("Bedrock returned an empty response")
    usage = data.get("usage") or {}
    return "\n".join(parts), int(usage.get("inputTokens") or 0), int(usage.get("outputTokens") or 0)


def _inference_config(max_tokens: int) -> dict:
    """Claude Sonnet 5 rejects deprecated `temperature` in inferenceConfig."""
    return {"maxTokens": max_tokens}


def _chat_via_api_key(system: str, user: str, *, max_tokens: int, model_id: str) -> tuple[str, int, int]:
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
            resp = client.post(_converse_url(model_id), json=payload, headers=headers)
            resp.raise_for_status()
            return _parse_converse_response(resp.json())
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"Bedrock API error {exc.response.status_code}") from exc
    except Exception as exc:
        raise ValueError("Bedrock invoke failed") from exc


def _chat_via_boto3(system: str, user: str, *, max_tokens: int, model_id: str) -> tuple[str, int, int]:
    client = get_bedrock_runtime_client()
    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig=_inference_config(max_tokens),
        )
    except Exception as exc:
        raise ValueError("Bedrock invoke failed") from exc
    return _parse_converse_response(resp)


def chat(
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float = 0,
    model_id: str | None = None,
    purpose: str = "generic",
    use_cache: bool = True,
    user_id: str | None = None,
) -> str:
    """Send a system + user message to Bedrock and return the assistant text."""
    del temperature
    model = model_id or settings.bedrock_model_id
    if use_cache:
        cached = llm_cache.get_llm(model, system, user)
        if cached is not None:
            llm_usage.record(
                model_id=model,
                purpose=purpose,
                cache_hit=True,
                user_id=user_id,
            )
            return cached

    started = time.perf_counter()
    if _has_bedrock_api_key():
        text, inp, out = _chat_via_api_key(system, user, max_tokens=max_tokens, model_id=model)
    else:
        text, inp, out = _chat_via_boto3(system, user, max_tokens=max_tokens, model_id=model)
    latency_ms = int((time.perf_counter() - started) * 1000)
    llm_usage.record(
        model_id=model,
        purpose=purpose,
        input_tokens=inp,
        output_tokens=out,
        latency_ms=latency_ms,
        cache_hit=False,
        user_id=user_id,
    )
    if use_cache:
        llm_cache.put_llm(model, system, user, text)
    return text

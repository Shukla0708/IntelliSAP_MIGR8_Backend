import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.aws_client import get_bedrock_runtime_client

c = get_bedrock_runtime_client()
mid = "us.anthropic.claude-sonnet-5"
body = json.dumps({
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 50,
    "messages": [{"role": "user", "content": 'Reply JSON only: {"regex": ".*1"}'}],
})
try:
    r = c.invoke_model(
        modelId=mid,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    out = json.loads(r["body"].read())
    print("OK invoke_model:", out.get("content", [{}])[0].get("text", "")[:120])
except Exception as e:
    print("FAIL invoke_model:", e)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.aws_client import get_bedrock_runtime_client, get_boto_client

br = get_boto_client("bedrock")
client = get_bedrock_runtime_client()

profiles = br.list_inference_profiles(maxResults=100).get("inferenceProfileSummaries", [])
ids = [p.get("inferenceProfileId") for p in profiles if p.get("inferenceProfileId")]

print(f"Testing {len(ids)} inference profiles...\n")
working = []
for pid in ids:
    try:
        resp = client.converse(
            modelId=pid,
            messages=[{"role": "user", "content": [{"text": "Say OK"}]}],
            inferenceConfig={"maxTokens": 10, "temperature": 0},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        print(f"[OK] {pid} -> {text!r}")
        working.append(pid)
    except Exception as exc:
        err = str(exc).split("\n")[0][:100]
        print(f"[FAIL] {pid} -> {err}")

print(f"\nWorking profiles: {len(working)}")
for w in working:
    print(f"  {w}")

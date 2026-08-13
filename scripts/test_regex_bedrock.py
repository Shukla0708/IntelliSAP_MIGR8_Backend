import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from services import bedrock_llm, regex_generator

print("aws_region:", settings.aws_region)
print("bedrock_region:", settings.bedrock_region)
print("model:", settings.bedrock_model_id)

print("\n--- bedrock_llm.chat direct ---")
try:
    raw = bedrock_llm.chat(
        "Reply with ONLY JSON: {\"regex\": \".*1\"}",
        "Field name: TEST\nRule: ends with 1",
        max_tokens=200,
    )
    print("OK:", repr(raw))
except Exception as exc:
    print("FAIL:", type(exc).__name__, exc)
    raise SystemExit(1)

print("\n--- regex_generator.generate_regex ---")
try:
    pattern = regex_generator.generate_regex("TEST", "ends with 1")
    print("OK pattern:", pattern)
except Exception as exc:
    print("FAIL:", type(exc).__name__, exc)
    raise SystemExit(1)

print("\nAll checks passed.")

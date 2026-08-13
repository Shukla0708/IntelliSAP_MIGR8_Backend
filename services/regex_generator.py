import json
import re

from services import bedrock_llm

SYSTEM_PROMPT = (
    "You convert a plain-English data validation rule into a single "
    "Python-compatible regex used with re.fullmatch (do NOT include ^ or $). "
    "The pattern must accept ONLY values that satisfy EVERY part of the rule, "
    "and must REJECT values that violate it. "
    "Examples:\n"
    '- Rule: "starts with H4" → {"regex": "H4.*"}\n'
    '- Rule: "must be 10 digits starting with 9" → {"regex": "9[0-9]{9}"}\n'
    '- Rule: "ends with XYZ" → {"regex": ".*XYZ"}\n'
    "Never return a catch-all like .* or [A-Z0-9]+ unless the rule truly allows any value. "
    'Respond with ONLY a JSON object: {"regex": "<pattern>"}. '
    "No explanation, no markdown fences, no extra keys."
)


def generate_regex(field_name: str, user_prompt: str) -> str:
    """Use Bedrock LLM to turn a plain-English rule into a regex pattern."""
    prompt = (user_prompt or "").strip()
    if not prompt:
        raise ValueError("Empty rule prompt")
    raw = bedrock_llm.chat(
        SYSTEM_PROMPT,
        f"Field name: {field_name}\nRule: {prompt}",
        max_tokens=1000,
    )
    raw = bedrock_llm.strip_markdown_fences(raw)

    pattern = json.loads(raw)["regex"].strip()
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$") and not pattern.endswith(r"\$"):
        pattern = pattern[:-1]

    re.compile(pattern)
    return pattern

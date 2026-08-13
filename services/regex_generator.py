import re
import json
from groq import Groq
from config import settings

client = Groq(api_key=settings.groq_api_key)

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
    """Use Groq LLM to turn a plain-English rule into a regex pattern."""
    prompt = (user_prompt or "").strip()
    if not prompt:
        raise ValueError("Empty rule prompt")
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured")

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Field name: {field_name}\nRule: {prompt}"},
        ],
        temperature=0,
        max_tokens=200,
    )
    raw = resp.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    pattern = json.loads(raw)["regex"].strip()
    # Engine uses fullmatch — strip anchors the model often adds
    if pattern.startswith("^"):
        pattern = pattern[1:]
    if pattern.endswith("$") and not pattern.endswith(r"\$"):
        pattern = pattern[:-1]

    re.compile(pattern)  # raises if the model returned an invalid pattern
    return pattern

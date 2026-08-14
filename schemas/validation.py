from typing import Optional

from pydantic import BaseModel, field_validator


class CreateRunRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def trim_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        if len(cleaned) > 120:
            raise ValueError("must be at most 120 characters")
        return cleaned


class FieldRuleIn(BaseModel):
    field_name: str
    flag_key: bool = False
    flag_mandatory: bool = False
    flag_null: bool = False
    flag_email: bool = False
    flag_mobile: bool = False
    flag_date: bool = False
    flag_special_chars: bool = False
    case_format: Optional[str] = None
    data_type: str = "string"
    max_length: Optional[int] = None
    decimal_length: Optional[int] = None
    regex: Optional[str] = None
    regex_prompt: Optional[str] = None
    rule_source: Optional[str] = "default"

    @field_validator("rule_source")
    @classmethod
    def normalize_rule_source(cls, value: Optional[str]) -> str:
        if value in ("user", "ai", "default"):
            return value
        return "default"


class RegexGenerateRequest(BaseModel):
    field_name: str
    prompt: str


class RegexGenerateResponse(BaseModel):
    regex: str


class RunFieldOut(BaseModel):
    field_name: str
    flag_key: bool = False
    flag_mandatory: bool = False
    flag_null: bool = False
    flag_email: bool = False
    flag_mobile: bool = False
    flag_date: bool = False
    flag_special_chars: bool = False
    case_format: Optional[str] = None
    data_type: str = "string"
    max_length: Optional[int] = None
    decimal_length: Optional[int] = None
    regex: Optional[str] = None
    regex_prompt: Optional[str] = None
    rule_source: str = "default"


class SuggestFieldIn(BaseModel):
    field_name: str
    samples: list[str] = []


class SuggestRulesRequest(BaseModel):
    fields: list[SuggestFieldIn]
    run_id: Optional[str] = None


class SuggestedFieldOut(FieldRuleIn):
    rule_source: str = "ai"
    suggestion_source: str = "heuristic"
    template_name: Optional[str] = None


class SuggestRulesResponse(BaseModel):
    suggestions: list[SuggestedFieldOut]
    warning: Optional[str] = None


class RunDetailOut(BaseModel):
    id: str
    project_id: str
    name: str
    status: str
    source_filename: Optional[str] = None
    has_source_file: bool
    processed_rows: int = 0
    total_rows: int = 0
    error_message: Optional[str] = None
    has_result_file: bool = False
    fields: list[RunFieldOut]

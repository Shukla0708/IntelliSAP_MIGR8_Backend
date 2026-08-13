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


class RunDetailOut(BaseModel):
    id: str
    project_id: str
    name: str
    status: str
    source_filename: Optional[str] = None
    has_source_file: bool
    fields: list[RunFieldOut]

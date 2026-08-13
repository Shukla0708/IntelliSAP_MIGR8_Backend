from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class CreateComparisonRequest(BaseModel):
    name: str
    mapping_id: Optional[UUID] = None
    join_keys: Optional[list[str]] = None

    @field_validator("name")
    @classmethod
    def trim_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        if len(cleaned) > 120:
            raise ValueError("must be at most 120 characters")
        return cleaned


class ExecuteComparisonRequest(BaseModel):
    mapping_id: Optional[UUID] = None
    join_keys: Optional[list[str]] = None

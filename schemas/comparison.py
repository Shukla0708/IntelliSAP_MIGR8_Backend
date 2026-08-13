import uuid
from typing import Optional

from pydantic import BaseModel, field_validator


class CreateComparisonRequest(BaseModel):
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


class ExecuteComparisonRequest(BaseModel):
    """Keys are only read when no mapping is selected — a mapping carries its
    own composite key through final_mapping.key."""

    mapping_id: Optional[uuid.UUID] = None
    business_key_columns_preload: list[str] = []
    business_key_columns_postload: list[str] = []


class ComparisonDiscrepancyOut(BaseModel):
    id: str
    businessKey: str
    field: str
    fieldItalic: bool = False
    preloadValue: str
    postloadValue: str
    postloadHighlight: Optional[str] = None
    differenceType: str
    status: str


class ComparisonReviewOut(BaseModel):
    id: str
    projectName: str
    runName: str
    status: str
    matchedRecords: int
    matchRate: str
    differentCount: int
    differentLabel: str
    missingCount: int
    missingLabel: str
    discrepancies: list[ComparisonDiscrepancyOut]

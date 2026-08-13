from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class ProjectCreate(BaseModel):
    name: str


class ProjectOut(BaseModel):
    id: str
    name: str
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, value: UUID | str) -> str:
        return str(value)

    class Config:
        from_attributes = True

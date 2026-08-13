from typing import Literal

from pydantic import BaseModel, Field


ChatPage = Literal["dashboard", "report", "validation_result", "mapping_result"]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatContextIn(BaseModel):
    page: ChatPage = "dashboard"
    project_id: str | None = None
    run_id: str | None = None
    mapping_id: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)
    context: ChatContextIn = Field(default_factory=ChatContextIn)


class ChatResponse(BaseModel):
    reply: str
    refused: bool = False
    page: ChatPage

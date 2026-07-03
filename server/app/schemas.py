from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: HttpUrl


class Site(BaseModel):
    id: str
    name: str
    base_url: str


class IngestRequest(BaseModel):
    site_id: str
    urls: list[HttpUrl] = Field(min_length=1, max_length=200)


class IngestResult(BaseModel):
    indexed_documents: int
    indexed_chunks: int


class ConversationMessage(BaseModel):
    role: str = Field(pattern="^(visitor|agent)$")
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    site_id: str
    message: str = Field(min_length=1, max_length=1200)
    history: list[ConversationMessage] = Field(default_factory=list, max_length=8)


class RouteDecision(BaseModel):
    decision: str = Field(pattern="^(allow|deny)$")
    category: str = Field(pattern="^(greeting|site|appointment|deny)$")
    reason: str = Field(min_length=1, max_length=200)


class RewriteDecision(BaseModel):
    rewritten_message: str = Field(min_length=1, max_length=1200)
    used_history: bool


class ModelUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatUsage(BaseModel):
    route: Optional[ModelUsage] = None
    rewrite: Optional[ModelUsage] = None
    answer: Optional[ModelUsage] = None
    total: Optional[ModelUsage] = None


class Source(BaseModel):
    url: str
    title: str
    score: float


class BookingSlot(BaseModel):
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)


class BookingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class BookingConfirmation(BaseModel):
    event_id: str = Field(min_length=1, max_length=256)
    html_link: Optional[str] = Field(default=None, max_length=2000)


class BookingResult(BaseModel):
    status: str = Field(pattern="^(needs_info|slot_selection|confirmation|confirmed|error)$")
    message: str = Field(min_length=1, max_length=4000)
    slots: list[BookingSlot] = Field(default_factory=list)
    confirmation: Optional[BookingConfirmation] = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    usage: Optional[ChatUsage] = None

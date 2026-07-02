from __future__ import annotations

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


class ChatRequest(BaseModel):
    site_id: str
    message: str = Field(min_length=1, max_length=1200)


class Source(BaseModel):
    url: str
    title: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = []

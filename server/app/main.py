from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from server.app.config import get_settings
from server.app.db import db
from server.app.ingest import ingest_urls
from server.app.openai_client import generate_answer
from server.app.retrieval import retrieve_context
from server.app.schemas import ChatRequest, ChatResponse, IngestRequest, IngestResult, Site, SiteCreate, Source
from server.app.security import enforce_admin_token, enforce_origin, enforce_rate_limit, is_obviously_general_chat

settings = get_settings()

app = FastAPI(title="Agent IA Conversation", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
async def startup() -> None:
    await db.connect()


@app.on_event("shutdown")
async def shutdown() -> None:
    await db.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sites", response_model=Site, dependencies=[Depends(enforce_admin_token)])
async def create_site(payload: SiteCreate) -> Site:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO sites(name, base_url)
            VALUES($1, $2)
            ON CONFLICT(base_url) DO UPDATE SET name = EXCLUDED.name
            RETURNING id::text, name, base_url
            """,
            payload.name,
            str(payload.base_url).rstrip("/"),
        )
    return Site(**dict(row))


@app.post("/ingest", response_model=IngestResult, dependencies=[Depends(enforce_admin_token)])
async def ingest(payload: IngestRequest) -> IngestResult:
    try:
        documents, chunks = await ingest_urls(payload.site_id, [str(url) for url in payload.urls])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestResult(indexed_documents=documents, indexed_chunks=chunks)


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_origin), Depends(enforce_rate_limit)])
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    if is_obviously_general_chat(payload.message):
        return ChatResponse(answer="Le site ne traite pas de ce sujet.")

    context = await retrieve_context(payload.site_id, payload.message)
    if not context:
        return ChatResponse(answer="Le site ne traite pas de ce sujet.")

    answer = await generate_answer(payload.message, [item["content"] for item in context])
    sources = [
        Source(url=item["url"], title=item["title"], score=round(float(item["score"]), 4))
        for item in context[:3]
    ]
    return ChatResponse(answer=answer, sources=sources)

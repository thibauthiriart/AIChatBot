from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from server.app.config import get_settings
from server.app.db import db
from server.app.ingest import ingest_urls
from server.app.openai_client import generate_answer, rewrite_user_message, route_user_message
from server.app.retrieval import retrieve_context
from server.app.schemas import ChatRequest, ChatResponse, IngestRequest, IngestResult, Site, SiteCreate, Source
from server.app.security import enforce_admin_token, enforce_origin, enforce_rate_limit

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
async def chat(payload: ChatRequest) -> ChatResponse:
    route = await route_user_message(payload.message, payload.history)
    if route.decision != "allow":
        return ChatResponse(answer="Ce n'est pas possible.")

    if route.category == "greeting":
        return ChatResponse(answer="Bonjour, comment puis-je vous aider au sujet du site ?")

    rewritten = await rewrite_user_message(payload.message, payload.history)
    search_messages = _build_search_messages(payload.message, payload.history, rewritten.rewritten_message)

    context = []
    search_message = search_messages[0]
    for candidate in search_messages:
        candidate_context = await retrieve_context(payload.site_id, candidate)
        if not candidate_context:
            continue
        context = candidate_context
        search_message = candidate
        break

    if not context:
        return ChatResponse(answer="Le site ne traite pas de ce sujet.")

    answer = await generate_answer(search_message, [item["content"] for item in context], payload.history)
    sources = [
        Source(url=item["url"], title=item["title"], score=round(float(item["score"]), 4))
        for item in context[:3]
    ]
    return ChatResponse(answer=answer, sources=sources)


def _build_search_messages(message: str, history, rewritten_message: str) -> list[str]:
    candidates: list[str] = []
    for candidate in [rewritten_message.strip(), message.strip()]:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    recent_visitor_messages = [item.content.strip() for item in history if item.role == "visitor" and item.content.strip()]
    if recent_visitor_messages:
        combined = " ".join((recent_visitor_messages + [message.strip()])[-4:])
        if combined and combined not in candidates:
            candidates.append(combined)

    recent_conversation_messages = [item.content.strip() for item in history if item.content.strip()]
    if recent_conversation_messages:
        combined_conversation = " ".join((recent_conversation_messages + [message.strip()])[-6:])
        if combined_conversation and combined_conversation not in candidates:
            candidates.append(combined_conversation)

    return candidates

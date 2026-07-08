from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from server.app.booking import BookingService
from server.app.config import get_settings
from server.app.db import db
from server.app.ingest import ingest_urls
from server.app.openai_client import generate_answer, rewrite_user_message, route_user_message
from server.app.retrieval import retrieve_context
from server.app.schemas import ChatRequest, ChatResponse, ChatUsage, IngestRequest, IngestResult, ModelUsage, Site, SiteCreate, Source, WidgetConfigResponse
from server.app.security import enforce_admin_token, enforce_origin, enforce_rate_limit

settings = get_settings()
booking_service = BookingService(settings)

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
    await _ensure_chat_logging_schema()


@app.on_event("shutdown")
async def shutdown() -> None:
    await db.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/widget-config", response_model=WidgetConfigResponse, dependencies=[Depends(enforce_origin)])
async def widget_config() -> WidgetConfigResponse:
    return WidgetConfigResponse(widget_enabled=settings.widget_enabled)


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
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    if not settings.chat_service_enabled:
        return await _respond_and_log(request, payload, ChatResponse(answer="service indisponible"))

    route, route_usage = await route_user_message(payload.message, payload.history)
    if route.decision != "allow":
        return await _respond_and_log(
            request,
            payload,
            ChatResponse(answer="Ce n'est pas possible.", usage=_build_usage(route=route_usage)),
        )

    if route.category == "greeting":
        return await _respond_and_log(
            request,
            payload,
            ChatResponse(
                answer="Bonjour, comment puis-je vous aider au sujet du site ? Si vous le souhaitez, je peux aussi vous orienter vers un premier echange ou un audit selon votre besoin.",
                usage=_build_usage(route=route_usage),
            ),
        )

    if route.category == "appointment":
        booking_result = await booking_service.handle_message(payload.message, payload.history)
        return await _respond_and_log(
            request,
            payload,
            ChatResponse(
                answer=booking_result.message,
                usage=_build_usage(route=route_usage),
            ),
        )

    rewritten, rewrite_usage = await rewrite_user_message(payload.message, payload.history)
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
        return await _respond_and_log(
            request,
            payload,
            ChatResponse(answer="Le site ne traite pas de ce sujet.", usage=_build_usage(route=route_usage, rewrite=rewrite_usage)),
        )

    answer, answer_usage = await generate_answer(search_message, [item["content"] for item in context], payload.history)
    sources = [
        Source(url=item["url"], title=item["title"], score=round(float(item["score"]), 4))
        for item in context[:3]
    ]
    return await _respond_and_log(
        request,
        payload,
        ChatResponse(
            answer=answer,
            sources=sources,
            usage=_build_usage(route=route_usage, rewrite=rewrite_usage, answer=answer_usage),
        ),
    )


async def _respond_and_log(request: Request, payload: ChatRequest, response: ChatResponse) -> ChatResponse:
    await _log_chat_interaction(
        site_id=payload.site_id,
        client_ip=_get_client_ip(request),
        user_message=payload.message,
        assistant_answer=response.answer,
    )
    return response


async def _ensure_chat_logging_schema() -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_logs (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              client_ip TEXT NOT NULL,
              user_message TEXT NOT NULL,
              assistant_answer TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS chat_logs_site_created_idx ON chat_logs(site_id, created_at DESC)"
        )


async def _log_chat_interaction(site_id: str, client_ip: str, user_message: str, assistant_answer: str) -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO chat_logs(site_id, client_ip, user_message, assistant_answer)
            VALUES($1::uuid, $2, $3, $4)
            """,
            site_id,
            client_ip,
            user_message,
            assistant_answer,
        )


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        first_ip = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first_ip:
            return first_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


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


def _build_usage(
    route: ModelUsage | None = None,
    rewrite: ModelUsage | None = None,
    answer: ModelUsage | None = None,
) -> ChatUsage | None:
    if route is None and rewrite is None and answer is None:
        return None

    prompt_tokens = sum(item.prompt_tokens for item in [route, rewrite, answer] if item is not None)
    completion_tokens = sum(item.completion_tokens for item in [route, rewrite, answer] if item is not None)
    total_tokens = sum(item.total_tokens for item in [route, rewrite, answer] if item is not None)
    return ChatUsage(
        route=route,
        rewrite=rewrite,
        answer=answer,
        total=ModelUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )

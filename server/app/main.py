from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from typing import Optional
from uuid import UUID
import re
import unicodedata
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from server.app.booking import BookingProviderError, BookingService, is_appointment_lookup_request
from server.app.client_memory import ensure_client_memory_schema, resolve_client_for_chat, retrieve_client_context, retrieve_recent_global_context
from server.app.config import get_settings
from server.app.db import db
from server.app.ingest import ingest_urls
from server.app.mailer import MailerError, SmtpMailer
from server.app.noota import import_noota_report
from server.app.noota_drive import GoogleDriveNootaSyncService, NootaDriveSyncError, ensure_noota_drive_schema
from server.app.openai_client import NO_CONTEXT_MESSAGE, generate_answer, rewrite_user_message, route_user_message
from server.app.retrieval import retrieve_context
from server.app.schemas import (
    AppointmentNotification,
    AppointmentNotificationListResponse,
    CalendarEventRequest,
    ChatRequest,
    ChatResponse,
    ChatUsage,
    ClientArtifactCreate,
    ClientArtifactSummary,
    ClientContextSummary,
    ClientCreate,
    ClientEventCreate,
    ClientEventSummary,
    ClientProjectCreate,
    ClientProjectSummary,
    ClientSummary,
    IngestRequest,
    IngestResult,
    ModelUsage,
    NootaDriveFileInfo,
    NootaDriveImportAndEmailRequest,
    NootaDriveImportAndEmailResponse,
    NootaDriveImportOneRequest,
    NootaDriveImportedItem,
    NootaDrivePendingListResponse,
    NootaDriveScheduleSuggestionRequest,
    NootaDriveScheduleSuggestionResponse,
    NootaDriveStatusResponse,
    NootaDriveSyncRequest,
    NootaDriveSyncResponse,
    NootaImportResponse,
    NootaReportImport,
    Site,
    SiteCreate,
    Source,
    WidgetConfigResponse,
)
from server.app.security import enforce_admin_token, enforce_noota_or_admin_token, enforce_origin, enforce_rate_limit

logger = logging.getLogger(__name__)

settings = get_settings()
booking_service = BookingService(settings)
noota_drive_sync_service = GoogleDriveNootaSyncService(settings)
mailer = SmtpMailer(settings)

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
    await ensure_client_memory_schema()
    await ensure_noota_drive_schema()
    await _ensure_default_scope()


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
    scope_id = await _resolve_scope_id(payload.site_id)
    try:
        documents, chunks = await ingest_urls(scope_id, [str(url) for url in payload.urls])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestResult(indexed_documents=documents, indexed_chunks=chunks)


@app.post("/knowledge/urls", response_model=IngestResult, dependencies=[Depends(enforce_admin_token)])
async def ingest_knowledge_urls(payload: IngestRequest) -> IngestResult:
    return await ingest(payload)


@app.post("/integrations/noota/report", response_model=NootaImportResponse, dependencies=[Depends(enforce_noota_or_admin_token)])
async def ingest_noota_report(payload: NootaReportImport) -> NootaImportResponse:
    scope_id = await _resolve_scope_id(payload.site_id)
    return await import_noota_report(scope_id, payload)


@app.post("/integrations/noota/google-drive/sync", response_model=NootaDriveSyncResponse, dependencies=[Depends(enforce_admin_token)])
async def sync_noota_google_drive(payload: NootaDriveSyncRequest) -> NootaDriveSyncResponse:
    scope_id = await _resolve_scope_id(payload.site_id)
    try:
        return await noota_drive_sync_service.sync(scope_id, payload.folder_id, payload.limit)
    except NootaDriveSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/integrations/noota/google-drive/pending", response_model=NootaDrivePendingListResponse, dependencies=[Depends(enforce_origin)])
async def list_pending_noota_google_drive_reports(site_id: Optional[str] = None, folder_id: Optional[str] = None, limit: int = 5) -> NootaDrivePendingListResponse:
    await _resolve_scope_id(site_id)
    bounded_limit = min(max(limit, 1), 20)
    try:
        items = await noota_drive_sync_service.list_pending(folder_id, bounded_limit)
    except NootaDriveSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return NootaDrivePendingListResponse(items=items)


@app.post("/integrations/noota/google-drive/import-one", response_model=NootaDriveImportedItem, dependencies=[Depends(enforce_origin)])
async def import_pending_noota_google_drive_report(payload: NootaDriveImportOneRequest) -> NootaDriveImportedItem:
    scope_id = await _resolve_scope_id(payload.site_id)
    try:
        return await noota_drive_sync_service.import_one(scope_id, payload.external_id, payload.folder_id)
    except NootaDriveSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/integrations/noota/google-drive/import-and-email", response_model=NootaDriveImportAndEmailResponse, dependencies=[Depends(enforce_origin)])
async def import_and_email_pending_noota_google_drive_report(payload: NootaDriveImportAndEmailRequest) -> NootaDriveImportAndEmailResponse:
    scope_id = await _resolve_scope_id(payload.site_id)
    try:
        drive_file, report, formatted_report, suggested_appointments = await noota_drive_sync_service.get_pending_report(payload.external_id, payload.folder_id)
        subject = f"Compte rendu - {report.meeting_title}"
        await mailer.send_report(payload.recipient_email, subject, formatted_report)
        scheduled_appointments = await _schedule_report_appointments(
            scope_id,
            report.client_name,
            report.meeting_title,
            formatted_report,
            suggested_appointments,
        )
        imported_item = await noota_drive_sync_service.import_one(scope_id, drive_file.id, payload.folder_id)
    except (NootaDriveSyncError, MailerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BookingProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return NootaDriveImportAndEmailResponse(
        imported_item=imported_item,
        recipient_email=payload.recipient_email,
        mail_sent=True,
        scheduled_appointments=scheduled_appointments,
    )


@app.post("/integrations/noota/google-drive/schedule-suggestion", response_model=NootaDriveScheduleSuggestionResponse, dependencies=[Depends(enforce_origin)])
async def schedule_pending_noota_google_drive_suggestion(payload: NootaDriveScheduleSuggestionRequest) -> NootaDriveScheduleSuggestionResponse:
    scope_id = await _resolve_scope_id(payload.site_id)
    await _log_appointment_schedule_attempt(
        scope_id=scope_id,
        external_id=payload.external_id,
        title=payload.title,
        start=payload.start,
        end=payload.end,
        timezone=payload.timezone,
        status="requested",
        detail="manual_schedule_suggestion_request",
    )
    logger.info(
        "appointment_schedule_requested scope_id=%s external_id=%s title=%s start=%s timezone=%s",
        scope_id,
        payload.external_id,
        payload.title,
        payload.start,
        payload.timezone,
    )
    try:
        _, report, formatted_report, _ = await noota_drive_sync_service.get_pending_report(payload.external_id, payload.folder_id)
        suggestion_response = await _schedule_suggested_appointment(
            scope_id=scope_id,
            external_id=payload.external_id,
            client_name=report.client_name,
            meeting_title=report.meeting_title,
            formatted_report=formatted_report,
            title=payload.title,
            start=payload.start,
            end=payload.end,
            timezone=payload.timezone,
            description=payload.description,
        )
    except (NootaDriveSyncError, BookingProviderError) as exc:
        await _log_appointment_schedule_attempt(
            scope_id=scope_id,
            external_id=payload.external_id,
            title=payload.title,
            start=payload.start,
            end=payload.end,
            timezone=payload.timezone,
            status="error",
            detail=str(exc),
        )
        logger.exception(
            "appointment_schedule_failed scope_id=%s external_id=%s title=%s start=%s",
            scope_id,
            payload.external_id,
            payload.title,
            payload.start,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return suggestion_response


@app.get("/integrations/noota/google-drive/status", response_model=NootaDriveStatusResponse, dependencies=[Depends(enforce_origin)])
async def get_noota_google_drive_status(site_id: Optional[str] = None, folder_id: Optional[str] = None, limit: int = 5) -> NootaDriveStatusResponse:
    scope_id = await _resolve_scope_id(site_id)
    try:
        status = await noota_drive_sync_service.get_status(folder_id, min(max(limit, 1), 20))
    except NootaDriveSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status.imported_reports = len(await _fetch_recent_imported_reports(scope_id, 10))
    return status


@app.post("/clients", response_model=ClientSummary, dependencies=[Depends(enforce_admin_token)])
async def create_client(payload: ClientCreate) -> ClientSummary:
    scope_id = await _resolve_scope_id(payload.site_id)
    async with db.acquire() as connection:
        site_exists = await connection.fetchval("SELECT 1 FROM sites WHERE id = $1::uuid", scope_id)
        if not site_exists:
            raise HTTPException(status_code=404, detail="Unknown site_id")
        row = await connection.fetchrow(
            """
            INSERT INTO clients(site_id, name, short_name, aliases, sector, status, summary, external_ref, updated_at)
            VALUES($1::uuid, $2, $3, $4::text[], $5, $6, $7, $8, now())
            RETURNING
              id::text,
              site_id::text,
              name,
              NULLIF(short_name, '') AS short_name,
              aliases,
              sector,
              status,
              summary,
              external_ref
            """,
            scope_id,
            payload.name,
            payload.short_name or "",
            payload.aliases,
            payload.sector,
            payload.status,
            payload.summary,
            payload.external_ref,
        )
    return ClientSummary(**dict(row))


@app.post("/clients/{client_id}/projects", response_model=ClientProjectSummary, dependencies=[Depends(enforce_admin_token)])
async def create_client_project(client_id: str, payload: ClientProjectCreate) -> ClientProjectSummary:
    async with db.acquire() as connection:
        client_exists = await connection.fetchval("SELECT 1 FROM clients WHERE id = $1::uuid", client_id)
        if not client_exists:
            raise HTTPException(status_code=404, detail="Unknown client_id")
        row = await connection.fetchrow(
            """
            INSERT INTO client_projects(client_id, name, status, summary, started_on, due_on, updated_at)
            VALUES(
              $1::uuid,
              $2,
              $3,
              $4,
              NULLIF($5, '')::date,
              NULLIF($6, '')::date,
              now()
            )
            RETURNING
              id::text,
              client_id::text,
              name,
              status,
              summary,
              started_on::text,
              due_on::text
            """,
            client_id,
            payload.name,
            payload.status,
            payload.summary,
            payload.started_on or "",
            payload.due_on or "",
        )
    return ClientProjectSummary(**dict(row))


@app.post("/clients/{client_id}/artifacts", response_model=ClientArtifactSummary, dependencies=[Depends(enforce_admin_token)])
async def create_client_artifact(client_id: str, payload: ClientArtifactCreate) -> ClientArtifactSummary:
    async with db.acquire() as connection:
        client_exists = await connection.fetchval("SELECT 1 FROM clients WHERE id = $1::uuid", client_id)
        if not client_exists:
            raise HTTPException(status_code=404, detail="Unknown client_id")
        row = await connection.fetchrow(
            """
            INSERT INTO client_artifacts(client_id, project_id, title, kind, content, updated_at)
            VALUES($1::uuid, NULLIF($2, '')::uuid, $3, $4, $5, now())
            RETURNING
              id::text,
              client_id::text,
              project_id::text,
              title,
              kind
            """,
            client_id,
            payload.project_id or "",
            payload.title,
            payload.kind,
            payload.content,
        )
    return ClientArtifactSummary(**dict(row))


@app.post("/clients/{client_id}/events", response_model=ClientEventSummary, dependencies=[Depends(enforce_admin_token)])
async def create_client_event(client_id: str, payload: ClientEventCreate) -> ClientEventSummary:
    async with db.acquire() as connection:
        client_exists = await connection.fetchval("SELECT 1 FROM clients WHERE id = $1::uuid", client_id)
        if not client_exists:
            raise HTTPException(status_code=404, detail="Unknown client_id")
        row = await connection.fetchrow(
            """
            INSERT INTO client_events(client_id, project_id, title, event_type, details, event_at)
            VALUES($1::uuid, NULLIF($2, '')::uuid, $3, $4, $5, COALESCE(NULLIF($6, '')::timestamptz, now()))
            RETURNING
              id::text,
              client_id::text,
              project_id::text,
              title,
              event_type,
              details,
              event_at::text
            """,
            client_id,
            payload.project_id or "",
            payload.title,
            payload.event_type,
            payload.details,
            payload.event_at or "",
        )
    return ClientEventSummary(**dict(row))


@app.get("/clients/{client_id}/context", response_model=ClientContextSummary, dependencies=[Depends(enforce_admin_token)])
async def get_client_context(client_id: str, site_id: Optional[str] = None) -> ClientContextSummary:
    scope_id = await _resolve_scope_id(site_id)
    payload = await retrieve_client_context(scope_id, client_id, "")
    if not payload:
        raise HTTPException(status_code=404, detail="Unknown client context")
    return ClientContextSummary(
        client=ClientSummary(**payload["client"]),
        projects=[ClientProjectSummary(**item) for item in payload["projects"]],
        artifacts=[ClientArtifactSummary(**item) for item in payload["artifacts"]],
        recent_events=[ClientEventSummary(**item) for item in payload["recent_events"]],
    )


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_origin), Depends(enforce_rate_limit)])
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    scope_id = await _resolve_scope_id(payload.site_id)
    if not settings.chat_service_enabled:
        return await _respond_and_log(request, scope_id, payload, ChatResponse(answer="service indisponible"))

    drive_action_response = await _handle_drive_report_action_request(scope_id, payload.message, payload.history)
    if drive_action_response is not None:
        return await _respond_and_log(request, scope_id, payload, drive_action_response)

    drive_summary_response = await _handle_drive_report_summary_request(scope_id, payload.message, payload.history)
    if drive_summary_response is not None:
        return await _respond_and_log(request, scope_id, payload, drive_summary_response)

    if is_appointment_lookup_request(payload.message, payload.history):
        return await _respond_and_log(
            request,
            scope_id,
            payload,
            ChatResponse(answer=await _build_appointment_lookup_answer(scope_id, payload.message, payload.history)),
        )

    route, route_usage = await route_user_message(payload.message, payload.history)
    if route.decision != "allow":
        return await _respond_and_log(
            request,
            scope_id,
            payload,
            ChatResponse(answer="Ce n'est pas possible.", usage=_build_usage(route=route_usage)),
        )

    if route.category == "greeting":
        return await _respond_and_log(
            request,
            scope_id,
            payload,
            ChatResponse(
                answer="Bonjour, comment puis-je vous aider sur un client, un projet, un rapport ou un historique d'echanges ?",
                usage=_build_usage(route=route_usage),
            ),
        )

    if route.category == "appointment":
        booking_result = await booking_service.handle_message(payload.message, payload.history)
        if booking_result.status == "confirmed" and booking_result.confirmation and booking_result.request:
            await _log_appointment_notification(
                site_id=scope_id,
                client_name=booking_result.request.name,
                client_email=booking_result.request.email,
                scheduled_for=booking_result.request.start,
                timezone=booking_result.request.timezone,
                html_link=booking_result.confirmation.html_link,
            )
        return await _respond_and_log(
            request,
            scope_id,
            payload,
            ChatResponse(
                answer=booking_result.message,
                usage=_build_usage(route=route_usage),
            ),
        )

    if _is_drive_report_check_request(payload.message, payload.history):
        drive_answer, drive_sources = await _build_drive_report_check_response(scope_id)
        return await _respond_and_log(
            request,
            scope_id,
            payload,
            ChatResponse(
                answer=drive_answer,
                sources=drive_sources,
                usage=_build_usage(route=route_usage),
            ),
        )

    rewritten, rewrite_usage = await rewrite_user_message(payload.message, payload.history)
    search_messages = _build_search_messages(payload.message, payload.history, rewritten.rewritten_message)
    resolved_client = await resolve_client_for_chat(
        scope_id,
        payload.message,
        payload.history,
        explicit_client_id=payload.client_id,
    )

    context = []
    client_sources: list[Source] = []
    search_message = search_messages[0]
    for candidate in search_messages:
        candidate_context = await retrieve_context(scope_id, candidate)
        candidate_client_context = None
        candidate_global_client_context: list[dict] = []
        if resolved_client:
            candidate_client_context = await retrieve_client_context(scope_id, resolved_client["id"], candidate)
        else:
            candidate_global_client_context = await retrieve_recent_global_context(scope_id, candidate)

        combined_context = list(candidate_context)
        if candidate_client_context:
            combined_context = candidate_client_context["blocks"] + combined_context
            client_sources = [
                Source(url=item["url"], title=item["title"], score=round(float(item["score"]), 4))
                for item in candidate_client_context["blocks"][:3]
            ]
        elif candidate_global_client_context:
            combined_context = candidate_global_client_context + combined_context
            client_sources = [
                Source(url=item["url"], title=item["title"], score=round(float(item["score"]), 4))
                for item in candidate_global_client_context[:3]
            ]
        if not combined_context:
            continue
        context = combined_context
        search_message = candidate
        break

    if not context:
        return await _respond_and_log(
            request,
            scope_id,
            payload,
            ChatResponse(answer=NO_CONTEXT_MESSAGE, usage=_build_usage(route=route_usage, rewrite=rewrite_usage)),
        )

    answer, answer_usage = await generate_answer(search_message, [item["content"] for item in context], payload.history)
    sources = [
        Source(url=item["url"], title=item["title"], score=round(float(item["score"]), 4))
        for item in context[:3]
    ]
    if client_sources:
        sources = client_sources + [source for source in sources if source.url not in {item.url for item in client_sources}]
        sources = sources[:3]
    return await _respond_and_log(
        request,
        scope_id,
        payload,
        ChatResponse(
            answer=answer,
            sources=sources,
            client=ClientSummary(**resolved_client) if resolved_client else None,
            usage=_build_usage(route=route_usage, rewrite=rewrite_usage, answer=answer_usage),
        ),
    )


@app.get("/appointments/recent", response_model=AppointmentNotificationListResponse, dependencies=[Depends(enforce_origin)])
async def get_recent_appointments(site_id: Optional[str] = None, limit: int = 5) -> AppointmentNotificationListResponse:
    scope_id = await _resolve_scope_id(site_id)
    bounded_limit = min(max(limit, 1), 20)
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
              id::text,
              site_id::text,
              client_name,
              client_email,
              scheduled_for::text,
              timezone,
              created_at::text,
              NULLIF(html_link, '') AS html_link
            FROM appointment_notifications
            WHERE site_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2
            """,
            scope_id,
            bounded_limit,
        )
    return AppointmentNotificationListResponse(items=[AppointmentNotification(**dict(row)) for row in rows])


async def _respond_and_log(request: Request, scope_id: str, payload: ChatRequest, response: ChatResponse) -> ChatResponse:
    await _log_chat_interaction(
        site_id=scope_id,
        client_ip=_get_client_ip(request),
        user_message=payload.message,
        assistant_answer=response.answer,
    )
    return response


async def _build_appointment_lookup_answer(scope_id: str, message: str, history: list) -> str:
    combined = " ".join([item.content for item in history[-6:] if getattr(item, "content", "").strip()] + [message]).strip()
    normalized = _normalize_text(combined)
    if any(marker in normalized for marker in ("aujourd'hui", "aujourdhui", "du jour", "ce jour", "today")):
        return await _build_today_appointments_answer(scope_id)
    return await _build_recent_appointments_answer(scope_id)


async def _build_today_appointments_answer(scope_id: str) -> str:
    timezone_name = settings.booking_timezone_default
    day_timezone = ZoneInfo(timezone_name)
    today = datetime.now(day_timezone).date()
    day_start = datetime.combine(today, time.min, tzinfo=day_timezone)
    day_end = day_start + timedelta(days=1)

    rows = await _fetch_appointment_notifications(scope_id, day_start.isoformat(), day_end.isoformat(), ascending=True)
    formatted_day = today.strftime("%d/%m/%Y")
    if not rows:
        return f"Aucun rendez-vous n'est programme aujourd'hui ({formatted_day})."

    lines = [f"Rendez-vous programmes aujourd'hui ({formatted_day}) :"]
    lines.extend(_format_appointment_lines(rows, timezone_name))
    return "\n".join(lines)


async def _build_recent_appointments_answer(scope_id: str) -> str:
    timezone_name = settings.booking_timezone_default
    rows = await _fetch_appointment_notifications(scope_id, limit=10, ascending=False)
    if not rows:
        return "Aucun rendez-vous enregistre n'a ete trouve."

    lines = ["Voici les derniers rendez-vous enregistres :"]
    lines.extend(_format_appointment_lines(rows, timezone_name, include_date=True))
    return "\n".join(lines)


async def _fetch_appointment_notifications(
    scope_id: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
    ascending: bool = False,
) -> list:
    order = "ASC" if ascending else "DESC"
    async with db.acquire() as connection:
        if start and end:
            rows = await connection.fetch(
                f"""
                SELECT
                  client_name,
                  client_email,
                  scheduled_for,
                  timezone
                FROM appointment_notifications
                WHERE site_id = $1::uuid
                  AND scheduled_for >= $2::timestamptz
                  AND scheduled_for < $3::timestamptz
                ORDER BY scheduled_for {order}
                LIMIT $4
                """,
                scope_id,
                start,
                end,
                limit,
            )
        else:
            rows = await connection.fetch(
                f"""
                SELECT
                  client_name,
                  client_email,
                  scheduled_for,
                  timezone
                FROM appointment_notifications
                WHERE site_id = $1::uuid
                ORDER BY scheduled_for {order}
                LIMIT $2
                """,
                scope_id,
                limit,
            )
    return rows


async def _schedule_report_appointments(
    scope_id: str,
    client_name: str,
    meeting_title: str,
    formatted_report: str,
    suggestions: list,
) -> list[NootaDriveScheduleSuggestionResponse]:
    created_items: list[NootaDriveScheduleSuggestionResponse] = []
    for suggestion in suggestions:
        created_items.append(
            await _schedule_suggested_appointment(
                scope_id=scope_id,
                external_id=None,
                client_name=client_name,
                meeting_title=meeting_title,
                formatted_report=formatted_report,
                title=suggestion.title,
                start=suggestion.start,
                end=suggestion.end,
                timezone=suggestion.timezone,
                description=suggestion.source_excerpt,
            )
        )
    return created_items


async def _schedule_suggested_appointment(
    scope_id: str,
    external_id: str | None,
    client_name: str,
    meeting_title: str,
    formatted_report: str,
    title: str,
    start: str,
    end: str,
    timezone: str,
    description: str,
) -> NootaDriveScheduleSuggestionResponse:
    logger.info(
        "appointment_schedule_creating scope_id=%s external_id=%s title=%s start=%s timezone=%s",
        scope_id,
        external_id or "",
        title,
        start,
        timezone,
    )
    confirmation = await booking_service.provider.create_event(
        CalendarEventRequest(
            summary=title,
            start=start,
            end=end,
            timezone=timezone,
            description=description.strip()
            or (
                f"Rendez-vous detecte dans le compte rendu '{meeting_title}'.\n\n"
                f"Client: {client_name}\n\n"
                f"{formatted_report[:2000]}"
            ),
        )
    )
    notification_id = await _log_appointment_notification(
        scope_id,
        client_name,
        "",
        start,
        timezone,
        confirmation.html_link,
    )
    await _log_appointment_schedule_attempt(
        scope_id=scope_id,
        external_id=external_id,
        title=title,
        start=start,
        end=end,
        timezone=timezone,
        status="created",
        detail=f"event_id={confirmation.event_id};notification_id={notification_id or ''}",
    )
    logger.info(
        "appointment_schedule_created scope_id=%s external_id=%s event_id=%s notification_id=%s start=%s",
        scope_id,
        external_id or "",
        confirmation.event_id,
        notification_id or "",
        start,
    )
    return NootaDriveScheduleSuggestionResponse(
        notification_id=notification_id,
        event_id=confirmation.event_id,
        html_link=confirmation.html_link,
        title=title,
        start=start,
        end=end,
        timezone=timezone,
    )


def _format_appointment_lines(rows: list, fallback_timezone: str, include_date: bool = False) -> list[str]:
    lines: list[str] = []
    for row in rows:
        appointment_timezone = row["timezone"] or fallback_timezone
        local_start = row["scheduled_for"].astimezone(ZoneInfo(appointment_timezone))
        contact = (row["client_name"] or "").strip() or (row["client_email"] or "").strip() or "contact non renseigne"
        email = (row["client_email"] or "").strip()
        if email and email != contact:
            contact = f"{contact} ({email})"
        timestamp = local_start.strftime("%d/%m/%Y %H:%M") if include_date else local_start.strftime("%H:%M")
        lines.append(f"- {timestamp} ({appointment_timezone}) : {contact}")
    return lines


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
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS appointment_notifications (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              client_name TEXT NOT NULL DEFAULT '',
              client_email TEXT NOT NULL DEFAULT '',
              scheduled_for TIMESTAMPTZ NOT NULL,
              timezone TEXT NOT NULL DEFAULT 'Europe/Paris',
              html_link TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS appointment_notifications_site_created_idx ON appointment_notifications(site_id, created_at DESC)"
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS appointment_schedule_logs (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              external_id TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL DEFAULT '',
              start_at TIMESTAMPTZ,
              end_at TIMESTAMPTZ,
              timezone TEXT NOT NULL DEFAULT 'Europe/Paris',
              status TEXT NOT NULL,
              detail TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS appointment_schedule_logs_site_created_idx ON appointment_schedule_logs(site_id, created_at DESC)"
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


async def _log_appointment_notification(
    site_id: str,
    client_name: str,
    client_email: str,
    scheduled_for: str,
    timezone: str,
    html_link: Optional[str],
) -> Optional[str]:
    if not scheduled_for:
        return None
    scheduled_for_value = _parse_iso_datetime(scheduled_for)
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO appointment_notifications(site_id, client_name, client_email, scheduled_for, timezone, html_link)
            VALUES($1::uuid, $2, $3, $4, $5, $6)
            RETURNING id::text
            """,
            site_id,
            client_name,
            client_email,
            scheduled_for_value,
            timezone,
            html_link or "",
        )
    return str(row["id"]) if row else None


async def _log_appointment_schedule_attempt(
    scope_id: str,
    external_id: str | None,
    title: str,
    start: str | None,
    end: str | None,
    timezone: str,
    status: str,
    detail: str,
) -> None:
    if db.pool is None:
        logger.warning(
            "appointment_schedule_log_skipped scope_id=%s external_id=%s status=%s reason=db_pool_not_initialized",
            scope_id,
            external_id or "",
            status,
        )
        return
    start_value = _parse_iso_datetime(start)
    end_value = _parse_iso_datetime(end)
    async with db.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO appointment_schedule_logs(
              site_id,
              external_id,
              title,
              start_at,
              end_at,
              timezone,
              status,
              detail
            )
            VALUES(
              $1::uuid,
              $2,
              $3,
              $4,
              $5,
              $6,
              $7,
              $8
            )
            """,
            scope_id,
            external_id or "",
            title,
            start_value,
            end_value,
            timezone,
            status,
            detail[:2000],
        )


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


async def _ensure_default_scope() -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO sites(name, base_url)
            VALUES($1, $2)
            ON CONFLICT(base_url) DO UPDATE SET name = EXCLUDED.name
            """,
            settings.default_scope_name,
            settings.default_scope_base_url.rstrip("/"),
        )


async def _resolve_scope_id(explicit_scope_id: Optional[str]) -> str:
    if explicit_scope_id and explicit_scope_id.strip():
        try:
            return str(UUID(explicit_scope_id.strip()))
        except ValueError:
            pass

    async with db.acquire() as connection:
        scope_id = await connection.fetchval(
            "SELECT id::text FROM sites WHERE base_url = $1",
            settings.default_scope_base_url.rstrip("/"),
        )
        if scope_id:
            return str(scope_id)

        scope_id = await connection.fetchval("SELECT id::text FROM sites ORDER BY created_at ASC LIMIT 1")
        if scope_id:
            return str(scope_id)

    raise HTTPException(status_code=500, detail="No default scope configured")


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


def _is_drive_report_check_request(message: str, history: list) -> bool:
    combined = " ".join([item.content for item in history[-4:] if getattr(item, "content", "").strip()] + [message]).strip()
    normalized = _normalize_text(combined)
    checks = [
        "compte rendu",
        "compte-rendu",
        "cr",
        "reunion",
        "meeting",
        "drive",
        "noota",
    ]
    intents = [
        "check",
        "verifie",
        "verifier",
        "regarde",
        "voir",
        "fait",
        "disponible",
        "importe",
        "importe",
    ]
    return any(token in normalized for token in checks) and any(token in normalized for token in intents)


async def _handle_drive_report_action_request(
    scope_id: str,
    message: str,
    history: list,
) -> ChatResponse | None:
    combined = " ".join([item.content for item in history[-4:] if getattr(item, "content", "").strip()] + [message]).strip()
    normalized = _normalize_text(combined)

    action_terms = [
        "remet en forme",
        "remets en forme",
        "mettre en forme",
        "reformate",
        "reformater",
        "importe",
        "importer",
        "prepare le compte rendu",
        "prepare ce compte rendu",
    ]
    if not any(term in normalized for term in action_terms):
        return None

    pending_items = await noota_drive_sync_service.list_pending(None, 20)
    if not pending_items:
        return ChatResponse(
            answer="Je n'ai trouve aucun compte rendu en attente sur le Drive a remettre en forme pour le moment."
        )

    matched = _match_pending_report_from_message(message, pending_items)
    if matched is None:
        if len(pending_items) == 1:
            matched = pending_items[0]
        else:
            lines = ["J'ai trouve plusieurs comptes rendus en attente sur le Drive. Precise lequel traiter :"]
            for item in pending_items[:5]:
                lines.append(f"- {item.file_name}")
            return ChatResponse(
                answer="\n".join(lines),
                sources=[
                    Source(url=f"drive://pending/{item.external_id}", title=item.file_name, score=1.0 - (index * 0.05))
                    for index, item in enumerate(pending_items[:3])
                ],
            )

    answer = (
        f"J'ai retrouve le compte rendu {matched.file_name} sur le Drive et je l'ai remis en forme pour validation.\n\n"
        f"{matched.formatted_report}"
    )
    return ChatResponse(
        answer=answer,
        sources=[Source(url=f"drive://pending/{matched.external_id}", title=matched.file_name, score=1.0)],
    )


async def _build_drive_report_check_response(scope_id: str) -> tuple[str, list[Source]]:
    pending_items = await noota_drive_sync_service.list_pending(None, 5)
    imported_rows = await _fetch_recent_imported_reports(scope_id, 5)

    if pending_items:
        lines = ["Oui, j'ai verifie le Drive."]
        if len(pending_items) == 1:
            item = pending_items[0]
            lines.append(
                f"Un compte rendu est en attente de validation: {item.meeting_title} pour {item.client_name}."
            )
        else:
            lines.append(f"{len(pending_items)} comptes rendus sont en attente de validation sur le Drive.")
            for item in pending_items[:3]:
                lines.append(f"- {item.meeting_title} pour {item.client_name}")
        lines.append("Il faut le relire dans la popup puis le valider pour l'ajouter a la base et l'envoyer.")
        sources = [
            Source(
                url=f"drive://pending/{item.external_id}",
                title=item.meeting_title,
                score=1.0 - (index * 0.05),
            )
            for index, item in enumerate(pending_items[:3])
        ]
        return "\n".join(lines), sources

    if imported_rows:
        latest = imported_rows[0]
        lines = [
            "J'ai verifie le Drive et je n'ai pas de compte rendu en attente dans la file Noota.",
            (
                f"Le plus recent deja importe en base est {latest['title']} pour {latest['client_name']}, "
                f"mis a jour le {latest['updated_at']}."
            ),
        ]
        sources = [
            Source(
                url=f"client://{row['client_id']}/artifacts/{row['artifact_id']}",
                title=row["title"],
                score=1.0 - (index * 0.05),
            )
            for index, row in enumerate(imported_rows[:3])
        ]
        return "\n".join(lines), sources

    return (
        "J'ai verifie le Drive et la base, mais je n'ai trouve ni compte rendu en attente ni compte rendu Noota deja importe.",
        [],
    )


async def _handle_drive_report_summary_request(
    scope_id: str,
    message: str,
    history: list,
) -> ChatResponse | None:
    combined = " ".join([item.content for item in history[-6:] if getattr(item, "content", "").strip()] + [message]).strip()
    normalized = _normalize_text(combined)

    report_terms = [
        "compte rendu",
        "compte-rendu",
        "cr",
        "reunion",
        "meeting",
    ]
    summary_terms = [
        "que peux tu me dire",
        "que peux-tu me dire",
        "dis moi",
        "dis-moi",
        "resume",
        "resume moi",
        "resume-moi",
        "qu y a t il",
        "qu'y a-t-il",
        "qu y a t-il",
        "contenu",
        "details",
        "detail",
        "explique",
    ]
    if not any(term in normalized for term in report_terms):
        return None
    if not any(term in normalized for term in summary_terms):
        return None

    pending_items = await noota_drive_sync_service.list_pending(None, 20)
    if not pending_items:
        return ChatResponse(answer="Je n'ai trouve aucun compte rendu en attente sur le Drive a commenter pour le moment.")

    matched = _match_pending_report_from_message(combined, pending_items)
    if matched is None:
        if len(pending_items) == 1:
            matched = pending_items[0]
        else:
            lines = ["J'ai trouve plusieurs comptes rendus en attente sur le Drive. Precise lequel je dois resumer :"]
            for item in pending_items[:5]:
                lines.append(f"- {item.file_name}")
            return ChatResponse(
                answer="\n".join(lines),
                sources=[
                    Source(url=f"drive://pending/{item.external_id}", title=item.file_name, score=1.0 - (index * 0.05))
                    for index, item in enumerate(pending_items[:3])
                ],
            )

    answer = _build_pending_report_summary_answer(matched)
    return ChatResponse(
        answer=answer,
        sources=[Source(url=f"drive://pending/{matched.external_id}", title=matched.file_name, score=1.0)],
    )


async def _fetch_recent_imported_reports(scope_id: str, limit: int) -> list[dict]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
              clients.id::text AS client_id,
              clients.name AS client_name,
              client_artifacts.id::text AS artifact_id,
              client_artifacts.title,
              to_char(client_artifacts.updated_at AT TIME ZONE 'Europe/Paris', 'DD/MM/YYYY HH24:MI') AS updated_at
            FROM client_artifacts
            JOIN clients ON clients.id = client_artifacts.client_id
            WHERE clients.site_id = $1::uuid
              AND client_artifacts.kind = 'noota_report'
            ORDER BY client_artifacts.updated_at DESC
            LIMIT $2
            """,
            scope_id,
            limit,
        )
    return [dict(row) for row in rows]


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _build_pending_report_summary_answer(item: object) -> str:
    meeting_title = getattr(item, "meeting_title", "") or getattr(item, "file_name", "Compte rendu")
    client_name = getattr(item, "client_name", "") or "Client a qualifier"
    project_name = getattr(item, "project_name", "")
    meeting_at = getattr(item, "meeting_at", "")
    formatted_report = getattr(item, "formatted_report", "") or ""
    suggestions = getattr(item, "suggested_appointments", []) or []

    sections = _extract_report_sections(formatted_report)
    lines = [f"Ce compte rendu concerne {meeting_title}."]
    lines.append(f"Client: {client_name}.")
    if project_name:
        lines.append(f"Projet: {project_name}.")
    if meeting_at:
        lines.append(f"Date de reunion: {meeting_at}.")

    summary = "\n".join(sections.get("Synthese", [])[:2]).strip()
    if summary:
        lines.append("")
        lines.append("Synthese:")
        lines.append(summary)

    key_points = sections.get("Points cles", [])[:4]
    if key_points:
        lines.append("")
        lines.append("Points cles:")
        for point in key_points:
            lines.append(f"- {point}")

    actions = sections.get("Actions", [])[:4]
    if actions:
        lines.append("")
        lines.append("Actions relevees:")
        for action in actions:
            lines.append(f"- {action}")

    if suggestions:
        lines.append("")
        lines.append("Rendez-vous detectes:")
        for suggestion in suggestions[:3]:
            title = getattr(suggestion, "title", "Rendez-vous")
            start = getattr(suggestion, "start", "")
            timezone = getattr(suggestion, "timezone", "Europe/Paris")
            lines.append(f"- {title} ({start}, {timezone})")

    if not summary and not key_points and not actions:
        preview = formatted_report.strip()
        if preview:
            lines.append("")
            lines.append(preview[:1200])

    lines.append("")
    lines.append("Si vous voulez, je peux aussi vous le remettre en forme complet dans le chat ou preparer l'ajout du rendez-vous a l'agenda.")
    return "\n".join(lines)


def _extract_report_sections(formatted_report: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    known_headers = {"Informations generales", "Participants", "Synthese", "Points cles", "Decisions", "Actions", "Transcript"}
    for raw_line in formatted_report.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in known_headers:
            current = line
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        sections[current].append(line.lstrip("- ").strip())
    return sections


def _match_pending_report_from_message(message: str, pending_items: list) -> object | None:
    normalized_message = _normalize_text(message)
    best_item = None
    best_score = 0

    for item in pending_items:
        candidates = [
            getattr(item, "file_name", ""),
            getattr(item, "meeting_title", ""),
            getattr(item, "client_name", ""),
            getattr(item, "project_name", ""),
        ]
        score = 0
        for candidate in candidates:
            normalized_candidate = _normalize_text(candidate)
            if normalized_candidate and normalized_candidate in normalized_message:
                score = max(score, len(normalized_candidate))
        if score > best_score:
            best_item = item
            best_score = score

    return best_item

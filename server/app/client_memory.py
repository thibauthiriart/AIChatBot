from __future__ import annotations

import re
import unicodedata
from typing import Any

from server.app.config import get_settings
from server.app.db import db
from server.app.schemas import ConversationMessage


async def ensure_client_memory_schema() -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              short_name TEXT NOT NULL DEFAULT '',
              aliases TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              sector TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              external_ref TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_projects (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              started_on DATE NULL,
              due_on DATE NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_artifacts (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
              project_id UUID NULL REFERENCES client_projects(id) ON DELETE SET NULL,
              title TEXT NOT NULL,
              kind TEXT NOT NULL DEFAULT 'report',
              content TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_events (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
              project_id UUID NULL REFERENCES client_projects(id) ON DELETE SET NULL,
              title TEXT NOT NULL,
              event_type TEXT NOT NULL DEFAULT 'note',
              details TEXT NOT NULL DEFAULT '',
              event_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute("CREATE INDEX IF NOT EXISTS clients_site_idx ON clients(site_id, updated_at DESC)")
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS client_projects_client_idx ON client_projects(client_id, updated_at DESC)"
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS client_artifacts_client_idx ON client_artifacts(client_id, updated_at DESC)"
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS client_events_client_idx ON client_events(client_id, event_at DESC)"
        )


async def fetch_client_by_id(site_id: str, client_id: str) -> dict[str, Any] | None:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
              id::text,
              site_id::text,
              name,
              NULLIF(short_name, '') AS short_name,
              aliases,
              sector,
              status,
              summary,
              external_ref
            FROM clients
            WHERE site_id = $1::uuid AND id = $2::uuid
            """,
            site_id,
            client_id,
        )
    return _row_to_client(row)


async def resolve_client_for_chat(
    site_id: str,
    message: str,
    history: list[ConversationMessage],
    explicit_client_id: str | None = None,
) -> dict[str, Any] | None:
    if explicit_client_id:
        return await fetch_client_by_id(site_id, explicit_client_id)

    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
              id::text,
              site_id::text,
              name,
              NULLIF(short_name, '') AS short_name,
              aliases,
              sector,
              status,
              summary,
              external_ref
            FROM clients
            WHERE site_id = $1::uuid
            ORDER BY updated_at DESC, name ASC
            """,
            site_id,
        )

    haystacks = [message.strip()]
    haystacks.extend(item.content.strip() for item in history[-6:] if item.content.strip())
    normalized_haystack = " ".join(_normalize(item) for item in haystacks if item).strip()
    if not normalized_haystack:
        return None

    best_match: dict[str, Any] | None = None
    best_score = 0
    for row in rows:
        client = _row_to_client(row)
        aliases = [client["name"], client.get("short_name") or "", *(client.get("aliases") or [])]
        for alias in aliases:
            normalized_alias = _normalize(alias)
            if len(normalized_alias) < 3:
                continue
            if normalized_alias not in normalized_haystack:
                continue
            score = len(normalized_alias)
            if score > best_score:
                best_match = client
                best_score = score

    return best_match


async def retrieve_client_context(site_id: str, client_id: str, question: str) -> dict[str, Any] | None:
    client = await fetch_client_by_id(site_id, client_id)
    if not client:
        return None

    settings = get_settings()
    async with db.acquire() as connection:
        projects = [dict(row) for row in await connection.fetch(_PROJECTS_QUERY, client_id)]
        artifacts = [dict(row) for row in await connection.fetch(_ARTIFACTS_QUERY, client_id)]
        events = [dict(row) for row in await connection.fetch(_EVENTS_QUERY, client_id)]

    question_tokens = _extract_keywords(question)
    context_blocks: list[dict[str, Any]] = []
    context_blocks.append(_build_client_overview_block(client))

    if projects:
        project_block = _build_project_summary_block(client, projects)
        if project_block:
            context_blocks.append(project_block)

    if events:
        context_blocks.append(_build_recent_events_block(client, events[:6]))

    scored_artifacts = []
    for artifact in artifacts:
        score = _score_text(question_tokens, artifact["title"], artifact["content"])
        scored_artifacts.append((score, artifact))
    scored_artifacts.sort(key=lambda item: (-item[0], item[1]["title"]))

    for score, artifact in scored_artifacts[: max(0, settings.chat_max_context_chunks - len(context_blocks))]:
        if score <= 0 and len(context_blocks) >= settings.chat_max_context_chunks:
            break
        context_blocks.append(_build_artifact_block(client, artifact, score))

    while len(context_blocks) < min(settings.chat_max_context_chunks, 4) and len(context_blocks) < len(artifacts) + 3:
        artifact_index = len(context_blocks) - 3
        if 0 <= artifact_index < len(artifacts):
            context_blocks.append(_build_artifact_block(client, artifacts[artifact_index], 0.2))
        else:
            break

    return {
        "client": client,
        "projects": [_serialize_project(project) for project in projects[:5]],
        "artifacts": [_serialize_artifact(artifact) for artifact in artifacts[:5]],
        "recent_events": [_serialize_event(event) for event in events[:8]],
        "blocks": context_blocks[: settings.chat_max_context_chunks],
    }


async def retrieve_recent_global_context(site_id: str, question: str) -> list[dict[str, Any]]:
    settings = get_settings()
    question_tokens = _extract_keywords(question)

    async with db.acquire() as connection:
        artifact_rows = await connection.fetch(
            """
            SELECT
              clients.id::text AS client_id,
              clients.name AS client_name,
              client_artifacts.id::text AS artifact_id,
              client_artifacts.title,
              client_artifacts.kind,
              client_artifacts.content,
              client_artifacts.updated_at
            FROM client_artifacts
            JOIN clients ON clients.id = client_artifacts.client_id
            WHERE clients.site_id = $1::uuid
            ORDER BY client_artifacts.updated_at DESC
            LIMIT 12
            """,
            site_id,
        )
        event_rows = await connection.fetch(
            """
            SELECT
              clients.id::text AS client_id,
              clients.name AS client_name,
              client_events.id::text AS event_id,
              client_events.title,
              client_events.event_type,
              client_events.details,
              client_events.event_at
            FROM client_events
            JOIN clients ON clients.id = client_events.client_id
            WHERE clients.site_id = $1::uuid
            ORDER BY client_events.event_at DESC, client_events.created_at DESC
            LIMIT 12
            """,
            site_id,
        )

    blocks: list[dict[str, Any]] = []

    for row in artifact_rows:
        item = dict(row)
        score = _score_text(question_tokens, item["title"], item["kind"], item["content"], item["client_name"])
        if score <= 0 and not _looks_like_recent_report_query(question_tokens):
            continue
        blocks.append(
            {
                "content": f"Document recent pour {item['client_name']} - {item['kind']} - {item['title']}: {item['content']}",
                "url": f"client://{item['client_id']}/artifacts/{item['artifact_id']}",
                "title": item["title"],
                "score": max(score, 0.3),
            }
        )

    for row in event_rows:
        item = dict(row)
        score = _score_text(question_tokens, item["title"], item["event_type"], item["details"], item["client_name"])
        if score <= 0 and not _looks_like_recent_report_query(question_tokens):
            continue
        blocks.append(
            {
                "content": (
                    f"Evenement recent pour {item['client_name']}: {item['event_at'].isoformat()} - "
                    f"{item['event_type']} - {item['title']}"
                    + (f" ({item['details']})" if item["details"] else "")
                ),
                "url": f"client://{item['client_id']}/events/{item['event_id']}",
                "title": f"{item['client_name']} - {item['title']}",
                "score": max(score, 0.25),
            }
        )

    blocks.sort(key=lambda item: -float(item["score"]))
    return blocks[: settings.chat_max_context_chunks]


def _row_to_client(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = dict(row)
    payload["aliases"] = [alias for alias in payload.get("aliases", []) if alias]
    return payload


def _serialize_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(project["id"]),
        "client_id": str(project["client_id"]),
        "name": project["name"],
        "status": project["status"] or "",
        "summary": project["summary"] or "",
        "started_on": project["started_on"].isoformat() if project["started_on"] else None,
        "due_on": project["due_on"].isoformat() if project["due_on"] else None,
    }


def _serialize_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(artifact["id"]),
        "client_id": str(artifact["client_id"]),
        "project_id": str(artifact["project_id"]) if artifact["project_id"] else None,
        "title": artifact["title"],
        "kind": artifact["kind"],
    }


def _serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(event["id"]),
        "client_id": str(event["client_id"]),
        "project_id": str(event["project_id"]) if event["project_id"] else None,
        "title": event["title"],
        "event_type": event["event_type"],
        "details": event["details"] or "",
        "event_at": event["event_at"].isoformat(),
    }


def _build_client_overview_block(client: dict[str, Any]) -> dict[str, Any]:
    aliases = ", ".join(client["aliases"]) if client["aliases"] else "aucun alias"
    content = (
        f"Client: {client['name']}. "
        f"Nom court: {client.get('short_name') or 'non renseigne'}. "
        f"Secteur: {client.get('sector') or 'non renseigne'}. "
        f"Statut: {client.get('status') or 'non renseigne'}. "
        f"Reference externe: {client.get('external_ref') or 'non renseignee'}. "
        f"Aliases: {aliases}. "
        f"Resume general: {client.get('summary') or 'aucun resume'}."
    )
    return {
        "content": content,
        "url": f"client://{client['id']}/overview",
        "title": f"Fiche client {client['name']}",
        "score": 1.0,
    }


def _build_project_summary_block(client: dict[str, Any], projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not projects:
        return None
    parts = []
    for project in projects[:5]:
        dates = []
        if project["started_on"]:
            dates.append(f"debut {project['started_on'].isoformat()}")
        if project["due_on"]:
            dates.append(f"echeance {project['due_on'].isoformat()}")
        schedule = f" ({', '.join(dates)})" if dates else ""
        parts.append(
            f"{project['name']} [{project['status'] or 'statut non renseigne'}]{schedule}: {project['summary'] or 'sans resume'}"
        )
    return {
        "content": f"Projets du client {client['name']}: " + " | ".join(parts),
        "url": f"client://{client['id']}/projects",
        "title": f"Projets {client['name']}",
        "score": 0.9,
    }


def _build_recent_events_block(client: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    lines = []
    for event in events:
        lines.append(
            f"{event['event_at'].isoformat()}: {event['event_type']} - {event['title']}"
            + (f" ({event['details']})" if event["details"] else "")
        )
    return {
        "content": f"Historique recent du client {client['name']}: " + " | ".join(lines),
        "url": f"client://{client['id']}/timeline",
        "title": f"Timeline {client['name']}",
        "score": 0.8,
    }


def _build_artifact_block(client: dict[str, Any], artifact: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "content": f"Document client {artifact['kind']} - {artifact['title']}: {artifact['content']}",
        "url": f"client://{client['id']}/artifacts/{artifact['id']}",
        "title": artifact["title"],
        "score": max(score, 0.2),
    }


def _score_text(question_tokens: list[str], *parts: str) -> float:
    haystack = _normalize(" ".join(part for part in parts if part))
    if not haystack:
        return 0.0
    score = 0.0
    for token in question_tokens:
        if token in haystack:
            score += 2.0
    for left, right in _bigrams(question_tokens):
        if f"{left} {right}" in haystack:
            score += 3.0
    return score


def _extract_keywords(text: str) -> list[str]:
    stopwords = {
        "alors",
        "avec",
        "client",
        "comment",
        "dans",
        "depuis",
        "elle",
        "est",
        "faire",
        "leurs",
        "mais",
        "nous",
        "pour",
        "projet",
        "quel",
        "quelle",
        "quelles",
        "quels",
        "site",
        "son",
        "sur",
        "tout",
        "une",
        "vos",
        "votre",
    }
    keywords: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", _normalize(text)):
        if len(token) < 3 or token in stopwords or token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return keywords


def _bigrams(tokens: list[str]) -> list[tuple[str, str]]:
    return [(tokens[index], tokens[index + 1]) for index in range(len(tokens) - 1)]


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _looks_like_recent_report_query(tokens: list[str]) -> bool:
    hints = {"compte", "rendu", "reunion", "meeting", "cr", "rapport", "copil"}
    return any(token in hints for token in tokens)


_PROJECTS_QUERY = """
    SELECT id, client_id, name, status, summary, started_on, due_on
    FROM client_projects
    WHERE client_id = $1::uuid
    ORDER BY updated_at DESC, name ASC
"""

_ARTIFACTS_QUERY = """
    SELECT id, client_id, project_id, title, kind, content
    FROM client_artifacts
    WHERE client_id = $1::uuid
    ORDER BY updated_at DESC, title ASC
"""

_EVENTS_QUERY = """
    SELECT id, client_id, project_id, title, event_type, details, event_at
    FROM client_events
    WHERE client_id = $1::uuid
    ORDER BY event_at DESC, created_at DESC
"""

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
              task_extraction_status TEXT NOT NULL DEFAULT 'pending',
              task_extracted_at TIMESTAMPTZ NULL,
              task_extracted_count INTEGER NOT NULL DEFAULT 0,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            "ALTER TABLE client_artifacts ADD COLUMN IF NOT EXISTS task_extraction_status TEXT NOT NULL DEFAULT 'pending'"
        )
        await connection.execute("ALTER TABLE client_artifacts ADD COLUMN IF NOT EXISTS task_extracted_at TIMESTAMPTZ NULL")
        await connection.execute(
            "ALTER TABLE client_artifacts ADD COLUMN IF NOT EXISTS task_extracted_count INTEGER NOT NULL DEFAULT 0"
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
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_project_tasks (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
              project_id UUID NULL REFERENCES client_projects(id) ON DELETE CASCADE,
              artifact_id UUID NULL REFERENCES client_artifacts(id) ON DELETE SET NULL,
              title TEXT NOT NULL,
              owner TEXT NOT NULL DEFAULT '',
              due_date TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'proposed',
              source_excerpt TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS client_project_tasks_client_idx ON client_project_tasks(client_id, updated_at DESC)"
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS client_project_tasks_project_idx ON client_project_tasks(project_id, updated_at DESC)"
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
    rewritten_message: str | None = None,
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

    haystacks = [message.strip(), (rewritten_message or "").strip()]
    haystacks.extend(item.content.strip() for item in history[-6:] if item.content.strip())
    normalized_haystacks = [_normalize(item) for item in haystacks if item.strip()]
    normalized_haystack = " ".join(normalized_haystacks).strip()
    if not normalized_haystack:
        return None

    best_match: dict[str, Any] | None = None
    best_score = 0.0
    for row in rows:
        client = _row_to_client(row)
        aliases = [client["name"], client.get("short_name") or "", *(client.get("aliases") or [])]
        for alias in aliases:
            normalized_alias = _normalize(alias)
            if len(normalized_alias) < 3:
                continue
            score = _score_client_alias(normalized_alias, normalized_haystacks)
            if score <= 0:
                continue
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
        tasks = [dict(row) for row in await connection.fetch(_TASKS_QUERY, client_id)]

    question_tokens = _extract_keywords(question)
    context_blocks: list[dict[str, Any]] = []
    context_blocks.append(_build_client_overview_block(client))

    if projects:
        project_block = _build_project_summary_block(client, projects, tasks)
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
        "tasks": [_serialize_task(task) for task in tasks[:30]],
        "blocks": context_blocks[: settings.chat_max_context_chunks],
    }


async def list_client_project_tasks(site_id: str, client_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        client_exists = await connection.fetchval(
            "SELECT 1 FROM clients WHERE site_id = $1::uuid AND id = $2::uuid",
            site_id,
            client_id,
        )
        if not client_exists:
            raise LookupError("Unknown client")
        rows = await connection.fetch(
            """
            SELECT
              client_project_tasks.id,
              client_project_tasks.client_id,
              client_project_tasks.project_id,
              client_projects.name AS project_name,
              client_project_tasks.artifact_id,
              client_artifacts.title AS artifact_title,
              client_project_tasks.title,
              client_project_tasks.owner,
              client_project_tasks.due_date,
              client_project_tasks.status,
              client_project_tasks.source_excerpt,
              client_project_tasks.created_at,
              client_project_tasks.updated_at
            FROM client_project_tasks
            LEFT JOIN client_projects ON client_projects.id = client_project_tasks.project_id
            LEFT JOIN client_artifacts ON client_artifacts.id = client_project_tasks.artifact_id
            WHERE client_project_tasks.client_id = $1::uuid
            ORDER BY
              CASE client_project_tasks.status
                WHEN 'proposed' THEN 0
                WHEN 'later' THEN 1
                WHEN 'done' THEN 2
                ELSE 3
              END,
              client_project_tasks.updated_at DESC
            """,
            client_id,
        )
    return [_serialize_task(dict(row)) for row in rows]


async def update_client_project_task_status(site_id: str, task_id: str, status: str) -> dict[str, Any]:
    if status not in {"proposed", "done", "later", "abandoned"}:
        raise ValueError("Invalid task status")

    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            WITH updated AS (
              UPDATE client_project_tasks
              SET status = $3, updated_at = now()
              FROM clients
              WHERE client_project_tasks.client_id = clients.id
                AND clients.site_id = $1::uuid
                AND client_project_tasks.id = $2::uuid
              RETURNING client_project_tasks.*
            )
            SELECT
              updated.id,
              updated.client_id,
              updated.project_id,
              client_projects.name AS project_name,
              updated.artifact_id,
              client_artifacts.title AS artifact_title,
              updated.title,
              updated.owner,
              updated.due_date,
              updated.status,
              updated.source_excerpt,
              updated.created_at,
              updated.updated_at
            FROM updated
            LEFT JOIN client_projects ON client_projects.id = updated.project_id
            LEFT JOIN client_artifacts ON client_artifacts.id = updated.artifact_id
            """,
            site_id,
            task_id,
            status,
        )
    if not row:
        raise LookupError("Unknown task")
    return _serialize_task(dict(row))


async def create_client_project_task(
    client_id: str,
    project_id: str | None,
    artifact_id: str | None,
    title: str,
    owner: str = "",
    due_date: str = "",
    source_excerpt: str = "",
) -> dict[str, Any] | None:
    normalized_title = _clean_task_title(title)
    if not normalized_title:
        return None

    async with db.acquire() as connection:
        existing = await connection.fetchrow(
            """
            SELECT
              id,
              client_id,
              project_id,
              artifact_id,
              title,
              owner,
              due_date,
              status,
              source_excerpt,
              created_at,
              updated_at
            FROM client_project_tasks
            WHERE client_id = $1::uuid
              AND COALESCE(project_id::text, '') = COALESCE($2, '')
              AND lower(title) = lower($3)
            LIMIT 1
            """,
            client_id,
            project_id,
            normalized_title,
        )
        if existing:
            return _serialize_task(dict(existing))

        row = await connection.fetchrow(
            """
            INSERT INTO client_project_tasks(client_id, project_id, artifact_id, title, owner, due_date, status, source_excerpt, updated_at)
            VALUES($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, 'proposed', $7, now())
            RETURNING
              id,
              client_id,
              project_id,
              artifact_id,
              title,
              owner,
              due_date,
              status,
              source_excerpt,
              created_at,
              updated_at
            """,
            client_id,
            project_id,
            artifact_id,
            normalized_title,
            owner.strip(),
            due_date.strip(),
            source_excerpt.strip()[:1000],
        )
    return _serialize_task(dict(row))


async def mark_client_artifact_tasks_processed(artifact_id: str, extracted_count: int = 0) -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            UPDATE client_artifacts
            SET task_extraction_status = 'processed',
                task_extracted_at = now(),
                task_extracted_count = GREATEST(task_extracted_count, $2),
                updated_at = now()
            WHERE id = $1::uuid
            """,
            artifact_id,
            max(0, extracted_count),
        )


async def suggest_tasks_from_client_reports(site_id: str, client_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        artifact_rows = await connection.fetch(
            """
            SELECT client_artifacts.id::text, client_artifacts.client_id::text, client_artifacts.project_id::text, client_artifacts.title, client_artifacts.content
            FROM client_artifacts
            JOIN clients ON clients.id = client_artifacts.client_id
            WHERE clients.site_id = $1::uuid AND clients.id = $2::uuid
              AND COALESCE(client_artifacts.task_extraction_status, 'pending') <> 'processed'
            ORDER BY client_artifacts.updated_at DESC
            """,
            site_id,
            client_id,
        )

    created: list[dict[str, Any]] = []
    for artifact in artifact_rows:
        artifact_count = 0
        for candidate in extract_task_candidates_from_report(artifact["content"]):
            task = await create_client_project_task(
                artifact["client_id"],
                artifact["project_id"],
                artifact["id"],
                candidate["title"],
                candidate.get("owner", ""),
                candidate.get("due_date", ""),
                candidate.get("source_excerpt", ""),
            )
            if task:
                created.append(task)
                artifact_count += 1
        await mark_client_artifact_tasks_processed(artifact["id"], artifact_count)
    return created


def extract_task_candidates_from_report(content: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    in_actions_section = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        lowered = _normalize(line)
        if not line:
            if in_actions_section:
                in_actions_section = False
            continue
        if lowered in {"actions", "action items", "taches", "todo", "a faire"}:
            in_actions_section = True
            continue
        has_request_marker = _has_client_request_marker(lowered)
        has_discussion_marker = _has_discussion_task_marker(lowered)
        if not in_actions_section and not has_request_marker and not has_discussion_marker and not any(marker in lowered for marker in (" a faire", " action ", " responsable:", " echeance:")):
            continue
        if not re.match(r"^[-*•]|\d+[.)]", line) and not has_request_marker and not has_discussion_marker:
            continue
        title = re.sub(r"^[-*•]\s*|\d+[.)]\s*", "", line).strip()
        owner = _extract_inline_field(title, "Responsable")
        due_date = _extract_inline_field(title, "Echeance")
        title = re.sub(r"\s*\|\s*Responsable:\s*[^|]+", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*\|\s*Echeance:\s*[^|]+", "", title, flags=re.IGNORECASE).strip()
        cleaned = _clean_task_title(title)
        if cleaned and is_actionable_task_title(cleaned, owner, due_date):
            candidates.append(
                {
                    "title": cleaned,
                    "owner": owner,
                    "due_date": due_date,
                    "source_excerpt": line,
                }
            )
    return candidates


def is_actionable_task_title(title: str, owner: str = "", due_date: str = "") -> bool:
    normalized = _normalize(title).strip(" -:;.")
    if not normalized:
        return False
    if normalized in _NON_TASK_TITLES:
        return False
    if normalized.startswith(("aucun ", "aucune ", "pas d ", "pas de ")):
        return False
    if re.fullmatch(r"\d{1,2}\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)", normalized):
        return False
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?", normalized):
        return False
    tokens = [token for token in re.findall(r"[a-z0-9]+", normalized) if token]
    if len(tokens) <= 1:
        return False
    if len(normalized) < 8:
        return False
    if _starts_with_action_verb(normalized):
        return True
    if _has_client_request_marker(normalized):
        return True
    if _has_discussion_task_marker(normalized):
        return True
    if owner.strip() or due_date.strip():
        return True
    return False


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


def _serialize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(task["id"]),
        "client_id": str(task["client_id"]),
        "project_id": str(task["project_id"]) if task.get("project_id") else None,
        "project_name": task.get("project_name") or "",
        "artifact_id": str(task["artifact_id"]) if task.get("artifact_id") else None,
        "artifact_title": task.get("artifact_title") or "",
        "title": task["title"],
        "owner": task.get("owner") or "",
        "due_date": task.get("due_date") or "",
        "status": task.get("status") or "proposed",
        "source_excerpt": task.get("source_excerpt") or "",
        "created_at": task["created_at"].isoformat() if hasattr(task.get("created_at"), "isoformat") else str(task.get("created_at", "")),
        "updated_at": task["updated_at"].isoformat() if hasattr(task.get("updated_at"), "isoformat") else str(task.get("updated_at", "")),
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


def _build_project_summary_block(client: dict[str, Any], projects: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
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
        project_tasks = [task for task in tasks if str(task.get("project_id") or "") == str(project["id"])][:5]
        if project_tasks:
            task_summary = "; ".join(f"{task['title']} [{task.get('status') or 'proposed'}]" for task in project_tasks)
            parts.append(f"Taches {project['name']}: {task_summary}")
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


_NON_TASK_TITLES = {
    "action",
    "actions",
    "responsable",
    "responsables",
    "echeance",
    "echeances",
    "date",
    "dates",
    "a realiser",
    "a faire",
    "todo",
    "questions abordees",
    "plusieurs sujets ont ete discutes",
}

_ACTION_VERB_PREFIXES = (
    "adapter",
    "ajouter",
    "analyser",
    "activer",
    "collecter",
    "completer",
    "confirmer",
    "corriger",
    "creer",
    "deployer",
    "envoyer",
    "faire ",
    "finaliser",
    "mettre ",
    "modifier",
    "nettoyer",
    "organiser",
    "partager",
    "planifier",
    "preparer",
    "publier",
    "rediger",
    "relancer",
    "tester",
    "transmettre",
    "valider",
    "verifier",
)

_CLIENT_REQUEST_MARKERS = (
    "si possible",
    "si c'est possible",
    "si cela est possible",
    "j'aimerais",
    "j aimerais",
    "je voudrais",
    "je souhaiterais",
    "on aimerait",
    "on voudrait",
    "on souhaiterait",
    "le client aimerait",
    "le client voudrait",
    "le client souhaiterait",
    "le client souhaite",
    "le client demande",
    "demande de",
    "demande d'",
    "besoin de",
    "besoin d'",
    "il faudrait",
    "il faut",
    "ce serait bien de",
    "ce serait utile de",
    "possibilite de",
    "possibilite d'",
    "possibilité de",
    "possibilité d'",
)

_DISCUSSION_TASK_MARKERS = (
    "compromis",
    "arbitrage",
    "arbitrer",
    "a trancher",
    "a ete tranche",
    "a ete discute",
    "a ete longuement discute",
    "longue discussion",
    "longuement discute",
    "discussion autour",
    "discussion sur",
    "debat autour",
    "debat sur",
    "point sensible",
    "point bloquant",
    "point de blocage",
    "sujet sensible",
    "sujet bloque",
    "sujet recurrent",
    "revient souvent",
    "revient dans plusieurs",
    "revenu plusieurs fois",
    "mentionne dans plusieurs",
    "mentionnee dans plusieurs",
    "mentionne plusieurs fois",
    "mentionnee plusieurs fois",
    "cite dans plusieurs",
    "citee dans plusieurs",
)


def _starts_with_action_verb(normalized_title: str) -> bool:
    return normalized_title.startswith(_ACTION_VERB_PREFIXES)


def _has_client_request_marker(normalized_title: str) -> bool:
    return any(marker in normalized_title for marker in _CLIENT_REQUEST_MARKERS)


def _has_discussion_task_marker(normalized_title: str) -> bool:
    return any(marker in normalized_title for marker in _DISCUSSION_TASK_MARKERS)


def _clean_task_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip(" -:;")
    if len(cleaned) < 4:
        return ""
    return cleaned[:500]


def _extract_inline_field(text: str, label: str) -> str:
    match = re.search(rf"\|\s*{label}\s*:\s*([^|]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip()[:160] if match else ""


def _score_client_alias(normalized_alias: str, haystacks: list[str]) -> float:
    alias_tokens = [token for token in normalized_alias.split(" ") if token]
    if not alias_tokens:
        return 0.0

    best_score = 0.0
    for haystack in haystacks:
        if not haystack:
            continue
        if normalized_alias in haystack:
            best_score = max(best_score, 100.0 + len(normalized_alias))
            continue

        matched_tokens = 0
        matched_chars = 0
        for token in alias_tokens:
            if len(token) < 3:
                continue
            if token in haystack:
                matched_tokens += 1
                matched_chars += len(token)

        if matched_tokens == len(alias_tokens) and matched_tokens > 0:
            best_score = max(best_score, 70.0 + matched_chars)
            continue

        if len(alias_tokens) == 1 and matched_tokens == 1:
            best_score = max(best_score, 50.0 + matched_chars)

    return best_score


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

_TASKS_QUERY = """
    SELECT
      client_project_tasks.id,
      client_project_tasks.client_id,
      client_project_tasks.project_id,
      client_projects.name AS project_name,
      client_project_tasks.artifact_id,
      client_artifacts.title AS artifact_title,
      client_project_tasks.title,
      client_project_tasks.owner,
      client_project_tasks.due_date,
      client_project_tasks.status,
      client_project_tasks.source_excerpt,
      client_project_tasks.created_at,
      client_project_tasks.updated_at
    FROM client_project_tasks
    LEFT JOIN client_projects ON client_projects.id = client_project_tasks.project_id
    LEFT JOIN client_artifacts ON client_artifacts.id = client_project_tasks.artifact_id
    WHERE client_project_tasks.client_id = $1::uuid
    ORDER BY client_project_tasks.updated_at DESC
"""

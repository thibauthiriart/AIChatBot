from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import re
import unicodedata
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from server.app.client_memory import mark_client_artifact_tasks_processed
from server.app.db import db


_FIELD_DEFINITIONS = [
    {
        "key": "client_name",
        "label": "Client cible",
        "prompt": "Quel est le client ou l'entite exacte pour cette proposition d'offre ?",
        "priority": "critical",
    },
    {
        "key": "request_summary",
        "label": "Besoin client",
        "prompt": "Quel est le besoin, le contexte et l'objectif principal de l'offre ?",
        "priority": "critical",
    },
    {
        "key": "scope_details",
        "label": "Perimetre",
        "prompt": "Quel est le perimetre exact de la mission et qu'est-ce qui est inclus ?",
        "priority": "critical",
    },
    {
        "key": "deliverables",
        "label": "Livrables",
        "prompt": "Quels livrables doivent etre fournis dans l'offre ?",
        "priority": "critical",
    },
    {
        "key": "planning_details",
        "label": "Planning",
        "prompt": "Quel est le planning, le delai cible ou les jalons attendus ?",
        "priority": "critical",
    },
    {
        "key": "pricing_details",
        "label": "Prix",
        "prompt": "Quel est le prix, le budget ou la logique de chiffrage a retenir ?",
        "priority": "critical",
    },
    {
        "key": "time_spent_details",
        "label": "Temps passe",
        "prompt": "Quel temps passe, quelle charge ou quel volume de jours faut-il retenir ?",
        "priority": "critical",
    },
    {
        "key": "team_details",
        "label": "Equipe",
        "prompt": "Quelle equipe doit intervenir sur cette offre ou quels roles faut-il proposer ?",
        "priority": "critical",
    },
    {
        "key": "constraints",
        "label": "Contraintes",
        "prompt": "Y a-t-il des contraintes, hypotheses ou exclusions a faire apparaitre ?",
        "priority": "important",
    },
]

_KEYWORDS_TO_FIELD = {
    "prix": "pricing_details",
    "budget": "pricing_details",
    "tarif": "pricing_details",
    "tjm": "pricing_details",
    "jours": "time_spent_details",
    "jour": "time_spent_details",
    "charge": "time_spent_details",
    "temps": "time_spent_details",
    "planning": "planning_details",
    "jalon": "planning_details",
    "delai": "planning_details",
    "deadline": "planning_details",
    "livrable": "deliverables",
    "livrables": "deliverables",
    "equipe": "team_details",
    "consultant": "team_details",
    "chef de projet": "team_details",
    "perimetre": "scope_details",
    "scope": "scope_details",
    "mission": "scope_details",
    "besoin": "request_summary",
    "objectif": "request_summary",
    "contexte": "request_summary",
    "contrainte": "constraints",
    "exclusion": "constraints",
    "client": "client_name",
}

_NEGATIVE_SHORT_REPLIES = {
    "non",
    "no",
    "aucun",
    "aucune",
    "rien",
    "ras",
    "n/a",
    "na",
    "neant",
}

_NO_CONSTRAINTS_ANSWER = "Aucune contrainte, hypothese ou exclusion signalee."


@dataclass
class GeneratedExport:
    filename: str
    content_type: str
    data: bytes


_OFFER_TASK_TRUTH_SEPARATOR = "\n\n---\n\n## Etat actuel des taches du projet\n"


async def ensure_offer_schema() -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offer_projects (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              title TEXT NOT NULL,
              client_name TEXT NOT NULL DEFAULT '',
              sector TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'draft',
              linked_client_id UUID NULL REFERENCES clients(id) ON DELETE SET NULL,
              linked_client_project_id UUID NULL REFERENCES client_projects(id) ON DELETE SET NULL,
              request_summary TEXT NOT NULL DEFAULT '',
              scope_details TEXT NOT NULL DEFAULT '',
              deliverables TEXT NOT NULL DEFAULT '',
              planning_details TEXT NOT NULL DEFAULT '',
              pricing_details TEXT NOT NULL DEFAULT '',
              time_spent_details TEXT NOT NULL DEFAULT '',
              team_details TEXT NOT NULL DEFAULT '',
              constraints TEXT NOT NULL DEFAULT '',
              generated_offer_markdown TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offer_project_messages (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id UUID NOT NULL REFERENCES offer_projects(id) ON DELETE CASCADE,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offer_project_emails (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id UUID NOT NULL REFERENCES offer_projects(id) ON DELETE CASCADE,
              subject TEXT NOT NULL DEFAULT '',
              sender TEXT NOT NULL DEFAULT '',
              content TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offer_reference_documents (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              title TEXT NOT NULL,
              client_name TEXT NOT NULL DEFAULT '',
              sector TEXT NOT NULL DEFAULT '',
              offer_type TEXT NOT NULL DEFAULT '',
              delivery_timeline TEXT NOT NULL DEFAULT '',
              pricing_notes TEXT NOT NULL DEFAULT '',
              team_notes TEXT NOT NULL DEFAULT '',
              tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              content TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS team_profiles (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              full_name TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT '',
              seniority TEXT NOT NULL DEFAULT '',
              skills TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              sectors TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              bio TEXT NOT NULL DEFAULT '',
              availability_notes TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offer_project_exports (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id UUID NOT NULL REFERENCES offer_projects(id) ON DELETE CASCADE,
              format TEXT NOT NULL,
              filename TEXT NOT NULL,
              content_type TEXT NOT NULL,
              content BYTEA NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offer_project_task_choices (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id UUID NOT NULL REFERENCES offer_projects(id) ON DELETE CASCADE,
              task_key TEXT NOT NULL,
              title TEXT NOT NULL,
              detail TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT 'offer',
              source_id TEXT NOT NULL DEFAULT '',
              decision TEXT NOT NULL DEFAULT 'pending',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(project_id, task_key)
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offer_project_files (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id UUID NOT NULL REFERENCES offer_projects(id) ON DELETE CASCADE,
              filename TEXT NOT NULL,
              content_type TEXT NOT NULL DEFAULT '',
              size_bytes INTEGER NOT NULL DEFAULT 0,
              content BYTEA NOT NULL,
              extracted_text TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute("ALTER TABLE offer_projects ADD COLUMN IF NOT EXISTS linked_client_id UUID NULL REFERENCES clients(id) ON DELETE SET NULL")
        await connection.execute("ALTER TABLE offer_projects ADD COLUMN IF NOT EXISTS linked_client_project_id UUID NULL REFERENCES client_projects(id) ON DELETE SET NULL")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_projects_site_updated_idx ON offer_projects(site_id, updated_at DESC)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_projects_linked_client_idx ON offer_projects(linked_client_id)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_projects_linked_client_project_idx ON offer_projects(linked_client_project_id)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_project_messages_project_created_idx ON offer_project_messages(project_id, created_at ASC)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_project_emails_project_created_idx ON offer_project_emails(project_id, created_at DESC)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_project_files_project_created_idx ON offer_project_files(project_id, created_at DESC)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_reference_documents_site_updated_idx ON offer_reference_documents(site_id, updated_at DESC)")
        await connection.execute("CREATE INDEX IF NOT EXISTS team_profiles_site_updated_idx ON team_profiles(site_id, updated_at DESC)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_project_exports_project_created_idx ON offer_project_exports(project_id, created_at DESC)")
        await connection.execute("CREATE INDEX IF NOT EXISTS offer_project_task_choices_project_idx ON offer_project_task_choices(project_id, updated_at DESC)")


async def create_offer_project(site_id: str, title: str, client_name: str = "", sector: str = "", request_summary: str = "") -> dict[str, Any]:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO offer_projects(site_id, title, client_name, sector, request_summary, updated_at)
            VALUES($1::uuid, $2, $3, $4, $5, now())
            RETURNING id::text, title, client_name, sector, status, updated_at::text
            """,
            site_id,
            title.strip() or "Nouveau projet d'offre",
            client_name.strip(),
            sector.strip(),
            request_summary.strip(),
        )
        await connection.execute(
            """
            INSERT INTO offer_project_messages(project_id, role, content)
            VALUES($1::uuid, 'agent', $2)
            """,
            str(row["id"]),
            "Je suis pret a structurer cette proposition d'offre. Je vais m'appuyer sur vos references, vos emails et vos donnees equipe, puis vous demander les informations manquantes.",
        )
    return await get_offer_project_summary(str(row["id"]))


async def list_offer_projects(site_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, title, client_name, sector, status, updated_at::text
            FROM offer_projects
            WHERE site_id = $1::uuid
            ORDER BY updated_at DESC
            """,
            site_id,
        )
    items = [dict(row) for row in rows]
    for item in items:
        item["completion_ratio"] = await _compute_completion_ratio(item["id"])
    return items


async def get_offer_project_summary(project_id: str) -> dict[str, Any]:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT id::text, title, client_name, sector, status, updated_at::text
            FROM offer_projects
            WHERE id = $1::uuid
            """,
            project_id,
        )
    if row is None:
        raise LookupError("Unknown offer project")
    item = dict(row)
    item["completion_ratio"] = await _compute_completion_ratio(project_id)
    return item


async def update_offer_project(project_id: str, payload: dict[str, str]) -> dict[str, Any]:
    allowed_fields = [
        "title",
        "client_name",
        "sector",
        "request_summary",
        "scope_details",
        "deliverables",
        "planning_details",
        "pricing_details",
        "time_spent_details",
        "team_details",
        "constraints",
    ]
    assignments = []
    values: list[Any] = []
    for field in allowed_fields:
        if field in payload and payload[field] is not None:
            values.append(str(payload[field]).strip())
            assignments.append(f"{field} = ${len(values)}")
    if not assignments:
        return await get_offer_project_summary(project_id)
    values.append(project_id)
    async with db.acquire() as connection:
        await connection.execute(
            f"""
            UPDATE offer_projects
            SET {', '.join(assignments)}, updated_at = now()
            WHERE id = ${len(values)}::uuid
            """
            ,
            *values,
        )
    return await get_offer_project_summary(project_id)


async def delete_offer_project(project_id: str) -> None:
    async with db.acquire() as connection:
        await connection.execute("DELETE FROM offer_projects WHERE id = $1::uuid", project_id)


async def create_offer_reference(site_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO offer_reference_documents(
              site_id, title, client_name, sector, offer_type, delivery_timeline, pricing_notes, team_notes, tags, content, updated_at
            )
            VALUES($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
            RETURNING id::text, title, client_name, sector, offer_type, delivery_timeline, pricing_notes, team_notes, tags, created_at::text
            """,
            site_id,
            payload["title"].strip(),
            payload.get("client_name", "").strip(),
            payload.get("sector", "").strip(),
            payload.get("offer_type", "").strip(),
            payload.get("delivery_timeline", "").strip(),
            payload.get("pricing_notes", "").strip(),
            payload.get("team_notes", "").strip(),
            payload.get("tags", []),
            payload["content"].strip(),
        )
    item = dict(row)
    item["excerpt"] = _excerpt(payload["content"])
    return item


async def create_team_profile(site_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO team_profiles(site_id, full_name, role, seniority, skills, sectors, bio, availability_notes, updated_at)
            VALUES($1::uuid, $2, $3, $4, $5, $6, $7, $8, now())
            RETURNING id::text, full_name, role, seniority, skills, sectors, bio, availability_notes
            """,
            site_id,
            payload["full_name"].strip(),
            payload.get("role", "").strip(),
            payload.get("seniority", "").strip(),
            payload.get("skills", []),
            payload.get("sectors", []),
            payload.get("bio", "").strip(),
            payload.get("availability_notes", "").strip(),
        )
    return dict(row)


async def add_offer_project_email(project_id: str, subject: str, sender: str, content: str) -> dict[str, Any]:
    await _get_offer_project(project_id)
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO offer_project_emails(project_id, subject, sender, content)
            VALUES($1::uuid, $2, $3, $4)
            RETURNING id::text, subject, sender, created_at::text
            """,
            project_id,
            subject.strip(),
            sender.strip(),
            content.strip(),
        )
        await connection.execute("UPDATE offer_projects SET updated_at = now() WHERE id = $1::uuid", project_id)
    item = dict(row)
    item["excerpt"] = _excerpt(content)
    return item


async def add_offer_project_file(project_id: str, filename: str, content_type: str, content: bytes) -> dict[str, Any]:
    await _get_offer_project(project_id)
    extracted_text = _extract_file_text(filename, content_type, content)
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO offer_project_files(project_id, filename, content_type, size_bytes, content, extracted_text)
            VALUES($1::uuid, $2, $3, $4, $5, $6)
            RETURNING id::text, filename, content_type, size_bytes, created_at::text
            """,
            project_id,
            filename,
            content_type,
            len(content),
            content,
            extracted_text,
        )
        await connection.execute("UPDATE offer_projects SET updated_at = now() WHERE id = $1::uuid", project_id)
    item = dict(row)
    item["excerpt"] = _excerpt(extracted_text or f"Fichier charge: {filename}")
    return item


async def list_offer_project_messages(project_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, role, content, created_at::text
            FROM offer_project_messages
            WHERE project_id = $1::uuid
            ORDER BY created_at ASC
            """,
            project_id,
        )
    return [dict(row) for row in rows]


async def add_offer_project_message(project_id: str, role: str, content: str) -> dict[str, Any]:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO offer_project_messages(project_id, role, content)
            VALUES($1::uuid, $2, $3)
            RETURNING id::text, role, content, created_at::text
            """,
            project_id,
            role,
            content,
        )
        await connection.execute("UPDATE offer_projects SET updated_at = now() WHERE id = $1::uuid", project_id)
    return dict(row)


async def get_offer_project_context(site_id: str, project_id: str) -> dict[str, Any]:
    project = await _get_offer_project(project_id)
    references = await _match_offer_references(site_id, project)
    team_profiles = await _match_team_profiles(site_id, project)
    client_context = await _get_linked_client_context(site_id, project)
    task_choices = await _ensure_offer_task_choices(site_id, project) if project.get("linked_client_id") else await _list_offer_task_choices(project_id)
    missing_items = _build_missing_items(project)
    messages = await list_offer_project_messages(project_id)
    emails = await _list_offer_project_emails(project_id)
    files = await _list_offer_project_files(project_id)
    exports = await _list_offer_project_exports(project_id)
    summary = await get_offer_project_summary(project_id)
    return {
        "project": summary,
        "request_summary": project["request_summary"],
        "scope_details": project["scope_details"],
        "deliverables": project["deliverables"],
        "planning_details": project["planning_details"],
        "pricing_details": project["pricing_details"],
        "time_spent_details": project["time_spent_details"],
        "team_details": project["team_details"],
        "constraints": project["constraints"],
        "missing_items": missing_items,
        "messages": messages,
        "emails": emails,
        "files": files,
        "references": references,
        "suggested_team_profiles": team_profiles,
        "exports": exports,
        "generated_offer_markdown": project["generated_offer_markdown"] or "",
        "linked_client": client_context.get("client"),
        "linked_client_project": client_context.get("selected_project"),
        "client_artifacts": client_context.get("artifacts", []),
        "client_recent_events": client_context.get("events", []),
        "client_project_tasks": client_context.get("tasks", []),
        "task_choices": task_choices,
    }


async def handle_offer_project_message(site_id: str, project_id: str, content: str) -> dict[str, Any]:
    content = content.strip()
    if not content:
        raise ValueError("Message vide")

    messages_before = await list_offer_project_messages(project_id)
    prompted_field = _field_from_prompted_message(messages_before)
    await add_offer_project_message(project_id, "visitor", content)
    project = await _get_offer_project(project_id)
    missing_before = _build_missing_items(project)
    extracted_updates = _extract_updates_from_message(content, missing_before, prompted_field)
    if extracted_updates:
        project = await _apply_updates(project_id, extracted_updates)

    project = await _get_offer_project(project_id)
    missing_after = _build_missing_items(project)
    generated_offer_markdown = project["generated_offer_markdown"] or ""

    normalized = _normalize(content)
    project_selection = await _maybe_select_linked_client_project(site_id, project_id, project, content)
    if project_selection:
        answer = project_selection
        project = await _get_offer_project(project_id)
        missing_after = _build_missing_items(project)
    else:
        client_resolution = await _maybe_link_client_from_message(site_id, project_id, project, content)
        if client_resolution:
            answer = client_resolution
            project = await _get_offer_project(project_id)
            missing_after = _build_missing_items(project)
        elif is_offer_later_task_lookup_request(content):
            answer = await build_offer_later_tasks_answer(site_id, content, project_id)
        elif _is_generation_request(normalized):
            if any(item["priority"] == "critical" and item["status"] == "missing" for item in missing_after):
                answer = "Je peux generer l'offre des que les donnees critiques sont completes. " + _next_missing_prompt(missing_after)
            else:
                generated_offer_markdown = await generate_offer_markdown(site_id, project_id)
                answer = (
                    "Le brouillon de l'offre est pret. Vous pouvez maintenant le relire puis le telecharger en DOCX ou en PDF.\n\n"
                    + _build_offer_task_review(project)
                )
        elif _looks_like_offer_task_decision(normalized):
            answer = await _apply_offer_task_decisions(site_id, project, content)
        elif _is_offer_task_request(normalized):
            if project.get("linked_client_id"):
                answer = await _build_offer_task_selection_review(site_id, project)
            elif any(item["priority"] == "critical" and item["status"] == "missing" for item in missing_after):
                answer = "Je pourrai exposer les taches des que les donnees critiques seront completes. " + _next_missing_prompt(missing_after)
            else:
                answer = _build_offer_task_review(project)
        else:
            if extracted_updates:
                if missing_after:
                    answer = "Information bien enregistree. " + _next_missing_prompt(missing_after)
                else:
                    task_review = await _build_offer_task_selection_review(site_id, project)
                    answer = "Information bien enregistree. Toutes les donnees critiques sont completes.\n\n" + task_review
            elif missing_after:
                answer = _next_missing_prompt(missing_after)
            elif generated_offer_markdown:
                answer = await _build_offer_source_of_truth_answer(site_id, project)
            else:
                task_review = await _build_offer_task_selection_review(site_id, project)
                answer = "Le projet est complet cote donnees critiques.\n\n" + task_review

    message = await add_offer_project_message(project_id, "agent", answer)
    return {
        "message": message,
        "project": await get_offer_project_summary(project_id),
        "missing_items": missing_after,
        "generated_offer_markdown": generated_offer_markdown,
        "exports": await _list_offer_project_exports(project_id),
    }


async def generate_offer_markdown(site_id: str, project_id: str) -> str:
    project = await _get_offer_project(project_id)
    references = await _match_offer_references(site_id, project)
    team_profiles = await _match_team_profiles(site_id, project)
    client_context = await _get_linked_client_context(site_id, project)
    task_choices = await _list_offer_task_choices(project_id)
    markdown = _build_offer_markdown(
        project,
        references,
        team_profiles,
        client_context,
        task_choices,
        previous_offer_markdown=project["generated_offer_markdown"] or "",
    )
    async with db.acquire() as connection:
        await connection.execute(
            """
            UPDATE offer_projects
            SET generated_offer_markdown = $2, status = 'ready', updated_at = now()
            WHERE id = $1::uuid
            """,
            project_id,
            markdown,
        )
    return markdown


async def generate_offer_export(project_id: str, export_format: str) -> dict[str, Any]:
    project = await _get_offer_project(project_id)
    markdown = project["generated_offer_markdown"] or ""
    if not markdown:
        raise ValueError("Aucun brouillon n'a ete genere pour ce projet.")

    export = _render_export(project["title"], markdown, export_format)
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO offer_project_exports(project_id, format, filename, content_type, content)
            VALUES($1::uuid, $2, $3, $4, $5)
            RETURNING id::text, format, filename, created_at::text
            """,
            project_id,
            export_format,
            export.filename,
            export.content_type,
            export.data,
        )
    return dict(row)


async def get_offer_export(project_id: str, export_id: str) -> tuple[dict[str, Any], bytes]:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT id::text, format, filename, content_type, content, created_at::text
            FROM offer_project_exports
            WHERE project_id = $1::uuid AND id = $2::uuid
            """,
            project_id,
            export_id,
        )
    if row is None:
        raise LookupError("Unknown offer export")
    return dict(row), bytes(row["content"])


def is_offer_later_task_lookup_request(message: str) -> bool:
    normalized = _normalize_lookup(message)
    if "plus tard" not in normalized:
        return False
    if re.search(r"\bt\d+\b", normalized) and any(marker in normalized for marker in ("dans l offre", "oublie", "retire", "garde", "mettre")):
        return False
    return any(token in normalized for token in ("quelle", "quelles", "quoi", "liste", "reste", "restent", "laisse", "laissees", "tache", "taches"))


async def build_offer_later_tasks_answer(site_id: str, message: str, offer_project_id: str | None = None) -> str:
    client = None if offer_project_id else await _find_client_mentioned(site_id, message)
    rows = await _list_offer_task_choices_by_decision(site_id, "later", offer_project_id, client["id"] if client else None)
    rows = _dedupe_offer_task_choice_rows(rows, include_offer_title=offer_project_id is not None)
    if not rows:
        scope = " pour ce projet d'offre" if offer_project_id else (f" pour {client['name']}" if client else "")
        return f"Aucune tache n'est classee plus tard{scope}."

    lines = ["Taches laissees pour plus tard :"]
    for item in rows:
        context = []
        if item.get("client_name"):
            context.append(item["client_name"])
        if item.get("client_project_name"):
            context.append(item["client_project_name"])
        if item.get("offer_title") and not offer_project_id:
            context.append(f"offre {item['offer_title']}")
        suffix = f" ({' / '.join(context)})" if context else ""
        detail = f" : {item['detail']}" if item.get("detail") else ""
        lines.append(f"- {item['title']}{detail}{suffix}")
    return "\n".join(lines)


def _dedupe_offer_task_choice_rows(rows: list[dict[str, Any]], include_offer_title: bool = False) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for item in rows:
        key = (
            str(item.get("title") or ""),
            str(item.get("detail") or ""),
            str(item.get("client_name") or ""),
            str(item.get("client_project_name") or ""),
        )
        if include_offer_title:
            key = (*key, str(item.get("offer_title") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


async def _list_offer_task_choices_by_decision(
    site_id: str,
    decision: str,
    offer_project_id: str | None = None,
    client_id: str | None = None,
) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
              offer_project_task_choices.title,
              offer_project_task_choices.detail,
              offer_project_task_choices.source,
              offer_project_task_choices.source_id,
              offer_projects.title AS offer_title,
              clients.name AS client_name,
              client_projects.name AS client_project_name,
              offer_project_task_choices.updated_at::text AS updated_at
            FROM offer_project_task_choices
            JOIN offer_projects ON offer_projects.id = offer_project_task_choices.project_id
            LEFT JOIN clients ON clients.id = offer_projects.linked_client_id
            LEFT JOIN client_projects ON client_projects.id = offer_projects.linked_client_project_id
            WHERE offer_projects.site_id = $1::uuid
              AND offer_project_task_choices.decision = $2
              AND ($3::uuid IS NULL OR offer_projects.id = $3::uuid)
              AND ($4::uuid IS NULL OR offer_projects.linked_client_id = $4::uuid)
            ORDER BY offer_project_task_choices.updated_at DESC, offer_project_task_choices.title ASC
            """,
            site_id,
            decision,
            offer_project_id,
            client_id,
        )
    return [dict(row) for row in rows]


async def _get_offer_project(project_id: str) -> dict[str, Any]:
    async with db.acquire() as connection:
        row = await connection.fetchrow("SELECT * FROM offer_projects WHERE id = $1::uuid", project_id)
    if row is None:
        raise LookupError("Unknown offer project")
    return dict(row)


async def _apply_updates(project_id: str, updates: dict[str, str]) -> dict[str, Any]:
    await update_offer_project(project_id, updates)
    return await _get_offer_project(project_id)


async def _maybe_link_client_from_message(site_id: str, offer_project_id: str, project: dict[str, Any], message: str) -> str:
    if project.get("linked_client_id"):
        return ""
    client = await _find_client_mentioned(site_id, message)
    if not client:
        return ""

    client_context = await _get_client_context(site_id, client["id"], None)
    projects = client_context["projects"]
    if len(projects) > 1:
        await _link_offer_to_client(offer_project_id, client, None)
        lines = [f"J'ai trouve plusieurs projets pour {client['name']}. Lequel doit servir de contexte pour cette proposition ?"]
        for index, item in enumerate(projects[:10], start=1):
            summary = f" - {item['summary']}" if item.get("summary") else ""
            lines.append(f"{index}. {item['name']}{summary}")
        lines.append("Repondez avec le numero ou le nom du projet.")
        return "\n".join(lines)

    selected_project = projects[0] if projects else None
    await _link_offer_to_client(offer_project_id, client, selected_project)
    linked_project = await _get_offer_project(offer_project_id)
    linked_context = await _get_linked_client_context(site_id, linked_project)
    task_review = await _build_offer_task_selection_review(site_id, linked_project)
    return _build_loaded_client_context_answer(linked_context) + "\n\n" + task_review


async def _maybe_select_linked_client_project(site_id: str, offer_project_id: str, project: dict[str, Any], message: str) -> str:
    if not project.get("linked_client_id") or project.get("linked_client_project_id"):
        return ""
    client_context = await _get_client_context(site_id, str(project["linked_client_id"]), None)
    projects = client_context["projects"]
    if len(projects) <= 1:
        return ""
    selected_project = _select_project_from_message(message, projects)
    if not selected_project:
        choices = ", ".join(f"{index}. {item['name']}" for index, item in enumerate(projects[:10], start=1))
        return f"Je n'ai pas identifie le projet a charger. Choisissez un numero ou un nom parmi : {choices}."
    await _link_offer_to_client_project(offer_project_id, selected_project)
    linked_project = await _get_offer_project(offer_project_id)
    linked_context = await _get_linked_client_context(site_id, linked_project)
    task_review = await _build_offer_task_selection_review(site_id, linked_project)
    return _build_loaded_client_context_answer(linked_context) + "\n\n" + task_review


async def _find_client_mentioned(site_id: str, message: str) -> dict[str, Any] | None:
    normalized_message = _normalize_lookup(message)
    if not normalized_message:
        return None
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, site_id::text, name, NULLIF(short_name, '') AS short_name, aliases, sector, status, summary, external_ref
            FROM clients
            WHERE site_id = $1::uuid
            ORDER BY updated_at DESC, name ASC
            """,
            site_id,
        )
    best: tuple[int, dict[str, Any]] | None = None
    for row in rows:
        client = dict(row)
        aliases = [client["name"], client.get("short_name") or "", *(client.get("aliases") or [])]
        for alias in aliases:
            normalized_alias = _normalize_lookup(alias)
            if len(normalized_alias) < 3 or normalized_alias not in normalized_message:
                continue
            score = len(normalized_alias)
            if best is None or score > best[0]:
                best = (score, client)
    return best[1] if best else None


async def _link_offer_to_client(offer_project_id: str, client: dict[str, Any], selected_project: dict[str, Any] | None) -> None:
    title = selected_project["name"] if selected_project else f"Projet {client['name']}"
    request_summary = selected_project.get("summary", "") if selected_project else client.get("summary", "")
    async with db.acquire() as connection:
        await connection.execute(
            """
            UPDATE offer_projects
            SET
              linked_client_id = $2::uuid,
              linked_client_project_id = NULLIF($3, '')::uuid,
              client_name = $4,
              sector = CASE WHEN sector = '' THEN $5 ELSE sector END,
              title = CASE WHEN title = '' OR title = 'Nouveau projet d''offre' THEN $6 ELSE title END,
              request_summary = CASE WHEN request_summary = '' THEN $7 ELSE request_summary END,
              updated_at = now()
            WHERE id = $1::uuid
            """,
            offer_project_id,
            client["id"],
            selected_project["id"] if selected_project else "",
            client["name"],
            client.get("sector") or "",
            title,
            request_summary or "",
        )


async def _link_offer_to_client_project(offer_project_id: str, selected_project: dict[str, Any]) -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            UPDATE offer_projects
            SET
              linked_client_project_id = $2::uuid,
              title = CASE WHEN title = '' OR title = 'Nouveau projet d''offre' OR title LIKE 'Projet %' THEN $3 ELSE title END,
              request_summary = CASE WHEN request_summary = '' THEN $4 ELSE request_summary END,
              updated_at = now()
            WHERE id = $1::uuid
            """,
            offer_project_id,
            selected_project["id"],
            selected_project["name"],
            selected_project.get("summary") or "",
        )


async def _get_linked_client_context(site_id: str, project: dict[str, Any]) -> dict[str, Any]:
    client_id = project.get("linked_client_id")
    if not client_id:
        return {"client": None, "selected_project": None, "projects": [], "artifacts": [], "events": [], "tasks": []}
    return await _get_client_context(site_id, str(client_id), str(project["linked_client_project_id"]) if project.get("linked_client_project_id") else None)


async def _get_client_context(site_id: str, client_id: str, selected_project_id: str | None) -> dict[str, Any]:
    async with db.acquire() as connection:
        client_row = await connection.fetchrow(
            """
            SELECT id::text, site_id::text, name, NULLIF(short_name, '') AS short_name, aliases, sector, status, summary, external_ref
            FROM clients
            WHERE site_id = $1::uuid AND id = $2::uuid
            """,
            site_id,
            client_id,
        )
        if not client_row:
            return {"client": None, "selected_project": None, "projects": [], "artifacts": [], "events": [], "tasks": []}
        project_rows = await connection.fetch(
            """
            SELECT id::text, client_id::text, name, status, summary, started_on::text, due_on::text
            FROM client_projects
            WHERE client_id = $1::uuid
            ORDER BY updated_at DESC, name ASC
            """,
            client_id,
        )
        artifact_rows = await connection.fetch(
            """
            SELECT id::text, client_id::text, project_id::text AS project_id, title, kind, content, updated_at::text AS updated_at
            FROM client_artifacts
            WHERE client_id = $1::uuid
              AND ($2::uuid IS NULL OR project_id = $2::uuid)
            ORDER BY updated_at DESC, title ASC
            """,
            client_id,
            selected_project_id,
        )
        event_rows = await connection.fetch(
            """
            SELECT id::text, client_id::text, project_id::text AS project_id, title, event_type, details, event_at::text AS event_at
            FROM client_events
            WHERE client_id = $1::uuid
              AND ($2::uuid IS NULL OR project_id = $2::uuid)
            ORDER BY event_at DESC, created_at DESC
            """,
            client_id,
            selected_project_id,
        )
        task_rows = await connection.fetch(
            """
            SELECT
              client_project_tasks.id::text AS id,
              client_project_tasks.client_id::text AS client_id,
              client_project_tasks.project_id::text AS project_id,
              client_projects.name AS project_name,
              client_project_tasks.artifact_id::text AS artifact_id,
              client_artifacts.title AS artifact_title,
              client_project_tasks.title,
              client_project_tasks.owner,
              client_project_tasks.due_date,
              client_project_tasks.status,
              client_project_tasks.source_excerpt,
              client_project_tasks.created_at::text AS created_at,
              client_project_tasks.updated_at::text AS updated_at
            FROM client_project_tasks
            LEFT JOIN client_projects ON client_projects.id = client_project_tasks.project_id
            LEFT JOIN client_artifacts ON client_artifacts.id = client_project_tasks.artifact_id
            WHERE client_project_tasks.client_id = $1::uuid
              AND ($2::uuid IS NULL OR client_project_tasks.project_id = $2::uuid)
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
            selected_project_id,
        )

    projects = [dict(row) for row in project_rows]
    artifacts = [dict(row) for row in artifact_rows]
    tasks = [dict(row) for row in task_rows]
    for task in tasks:
        task["report_mentions"] = _count_task_report_mentions(task.get("title", ""), artifacts)
    selected_project = next((item for item in projects if item["id"] == selected_project_id), None) if selected_project_id else None
    return {
        "client": dict(client_row),
        "selected_project": selected_project,
        "projects": projects,
        "artifacts": [_summarize_client_artifact(artifact) for artifact in artifacts],
        "events": [dict(row) for row in event_rows],
        "tasks": tasks,
    }


def _select_project_from_message(message: str, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = _normalize_lookup(message)
    number_match = re.search(r"\b(\d{1,2})\b", normalized)
    if number_match:
        index = int(number_match.group(1)) - 1
        if 0 <= index < len(projects):
            return projects[index]
    scored: list[tuple[int, dict[str, Any]]] = []
    for project in projects:
        normalized_name = _normalize_lookup(project["name"])
        if normalized_name and normalized_name in normalized:
            scored.append((len(normalized_name), project))
            continue
        score = sum(len(token) for token in normalized_name.split() if len(token) >= 3 and token in normalized)
        if score > 0:
            scored.append((score, project))
    scored.sort(key=lambda item: -item[0])
    return scored[0][1] if scored else None


def _build_loaded_client_context_answer(client_context: dict[str, Any]) -> str:
    client = client_context.get("client")
    selected_project = client_context.get("selected_project")
    artifacts = client_context.get("artifacts", [])
    events = client_context.get("events", [])
    tasks = client_context.get("tasks", [])
    if not client:
        return "Je n'ai pas retrouve le contexte client en base."

    project_label = f" / projet {selected_project['name']}" if selected_project else ""
    lines = [f"Contexte charge pour {client['name']}{project_label}."]
    lines.append(f"- Comptes rendus/documents charges : {len(artifacts)}")
    lines.append(f"- Reunions/evenements charges : {len(events)}")
    lines.append(f"- Taches existantes chargees : {len(tasks)}")

    if artifacts:
        lines.append("")
        lines.append("Derniers comptes rendus :")
        for item in artifacts[:3]:
            lines.append(f"- {item['title']} : {item['excerpt']}")
    if tasks:
        lines.append("")
        lines.append("Taches existantes :")
        for item in tasks[:8]:
            owner = f" - {item['owner']}" if item.get("owner") else ""
            due = f" - echeance {item['due_date']}" if item.get("due_date") else ""
            lines.append(f"- {item['title']} [{item.get('status') or 'proposed'}]{owner}{due}")

    lines.append("")
    lines.append("Je vais utiliser ce contexte pour cadrer l'offre. Donnez-moi maintenant les elements manquants de cadrage ou demandez-moi les taches existantes.")
    return "\n".join(lines)


async def _build_linked_task_review(site_id: str, project: dict[str, Any]) -> str:
    client_context = await _get_linked_client_context(site_id, project)
    tasks = client_context.get("tasks", [])
    lines = []
    if tasks:
        lines.append("Taches deja chargees pour ce projet client :")
        for item in tasks[:20]:
            owner = f" - {item['owner']}" if item.get("owner") else ""
            due = f" - echeance {item['due_date']}" if item.get("due_date") else ""
            lines.append(f"- {item['title']} [{item.get('status') or 'proposed'}]{owner}{due}")
        lines.append("")
    else:
        lines.append("Aucune tache existante n'est rattachee a ce projet client pour le moment.")
        lines.append("")
    lines.append(_build_offer_task_review(project))
    return "\n".join(lines)


async def _build_offer_task_selection_review(site_id: str, project: dict[str, Any]) -> str:
    choices = await _ensure_offer_task_choices(site_id, project)
    if not choices:
        return "Je n'ai pas encore de taches a classer pour cette offre."

    lines = ["Voici les taches a classer pour cette proposition :"]
    for index, task in enumerate(choices, start=1):
        decision = _task_decision_label(task.get("decision") or "pending")
        detail = f" : {task['detail']}" if task.get("detail") else ""
        lines.append(f"- T{index} - {task['title']}{detail} [{decision}]")
    lines.append("")
    lines.append("Dites-moi lesquelles mettre dans l'offre, laisser pour plus tard ou oublier. Exemple : dans l'offre T1 T3, plus tard T2, oublier T4.")
    return "\n".join(lines)


async def _build_offer_source_of_truth_answer(site_id: str, project: dict[str, Any]) -> str:
    choices = await _ensure_offer_task_choices(site_id, project) if project.get("linked_client_id") else await _list_offer_task_choices(str(project["id"]))
    counts = {
        "include": sum(1 for item in choices if item.get("decision") == "include"),
        "later": sum(1 for item in choices if item.get("decision") == "later"),
        "forgotten": sum(1 for item in choices if item.get("decision") == "forgotten"),
        "pending": sum(1 for item in choices if item.get("decision") == "pending"),
    }
    lines = [
        "Je repars de la derniere proposition generee comme source de verite pour ce projet.",
        "Je garde aussi la liste de taches du projet comme contexte actif.",
        "",
        "Etat des taches :",
        f"- Dans l'offre : {counts['include']}",
        f"- Plus tard : {counts['later']}",
        f"- Oubliees : {counts['forgotten']}",
    ]
    if counts["pending"]:
        lines.append(f"- Encore a choisir : {counts['pending']}")
    lines.append("")
    lines.append("Si vous demandez une nouvelle generation, je repartirai de cette derniere proposition et je mettrai a jour l'etat des taches.")
    return "\n".join(lines)


async def _apply_offer_task_decisions(site_id: str, project: dict[str, Any], message: str) -> str:
    choices = await _ensure_offer_task_choices(site_id, project)
    if not choices:
        return "Je n'ai pas encore de taches a classer pour cette offre."

    normalized = _normalize(message)
    ids_by_decision = {
        "include": _extract_task_ids_for_decision(normalized, ("dans l'offre", "dans l offre", "inclure", "inclu", "inclues", "mettre", "mets", "garde", "garder", "conserve")),
        "later": _extract_task_ids_for_decision(normalized, ("plus tard", "later")),
        "forgotten": _extract_task_ids_for_decision(normalized, ("oublie", "oublier", "retire", "retirer", "supprime", "abandonne")),
    }
    updates: list[tuple[str, str]] = []
    for decision, display_ids in ids_by_decision.items():
        for display_id in display_ids:
            index = int(display_id[1:]) - 1
            if 0 <= index < len(choices):
                updates.append((choices[index]["task_key"], decision))

    if not updates:
        return "Je n'ai pas identifie clairement le classement. Utilisez par exemple : dans l'offre T1 T3, plus tard T2, oublier T4."

    async with db.acquire() as connection:
        for task_key, decision in updates:
            await connection.execute(
                """
                UPDATE offer_project_task_choices
                SET decision = $3, updated_at = now()
                WHERE project_id = $1::uuid AND task_key = $2
                """,
                project["id"],
                task_key,
                decision,
            )

    await _mark_source_artifacts_processed_for_task_keys(str(project["id"]), [task_key for task_key, _ in updates])
    refreshed = await _list_offer_task_choices(str(project["id"]))
    lines = ["C'est note pour les taches de la proposition :"]
    for decision in ("include", "later", "forgotten", "pending"):
        matching = [f"T{index}" for index, item in enumerate(refreshed, start=1) if item.get("decision") == decision]
        if matching:
            lines.append(f"- {_task_decision_label(decision)} : {', '.join(matching)}")
    lines.append("")
    lines.append("Je prendrai uniquement les taches marquees 'dans l'offre' dans la section taches du brouillon.")
    return "\n".join(lines)


async def _mark_source_artifacts_processed_for_task_keys(project_id: str, task_keys: list[str]) -> None:
    if not task_keys:
        return
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT DISTINCT client_project_tasks.artifact_id::text AS artifact_id
            FROM offer_project_task_choices
            JOIN client_project_tasks
              ON offer_project_task_choices.source = 'client'
             AND offer_project_task_choices.source_id = client_project_tasks.id::text
            WHERE offer_project_task_choices.project_id = $1::uuid
              AND offer_project_task_choices.task_key = ANY($2::text[])
              AND client_project_tasks.artifact_id IS NOT NULL
            """,
            project_id,
            task_keys,
        )
    for row in rows:
        await mark_client_artifact_tasks_processed(row["artifact_id"], 0)


async def _ensure_offer_task_choices(site_id: str, project: dict[str, Any]) -> list[dict[str, Any]]:
    client_context = await _get_linked_client_context(site_id, project)
    candidates = _build_offer_task_candidates(project, client_context)
    async with db.acquire() as connection:
        for candidate in candidates:
            await connection.execute(
                """
                INSERT INTO offer_project_task_choices(project_id, task_key, title, detail, source, source_id, updated_at)
                VALUES($1::uuid, $2, $3, $4, $5, $6, now())
                ON CONFLICT(project_id, task_key)
                DO UPDATE SET
                  title = EXCLUDED.title,
                  detail = EXCLUDED.detail,
                  source = EXCLUDED.source,
                  source_id = EXCLUDED.source_id,
                  updated_at = now()
                """,
                project["id"],
                candidate["task_key"],
                candidate["title"],
                candidate["detail"],
                candidate["source"],
                candidate["source_id"],
            )
    return await _list_offer_task_choices(str(project["id"]))


def _build_offer_task_candidates(project: dict[str, Any], client_context: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for task in client_context.get("tasks", []):
        parts = []
        if task.get("owner"):
            parts.append(f"responsable {task['owner']}")
        if task.get("due_date"):
            parts.append(f"echeance {task['due_date']}")
        report_mentions = int(task.get("report_mentions") or 0)
        if report_mentions >= 2:
            parts.append(f"mentionnee dans {report_mentions} comptes rendus")
        if task.get("source_excerpt"):
            parts.append(task["source_excerpt"])
        candidates.append(
            {
                "task_key": f"client:{task['id']}",
                "title": task["title"],
                "detail": _compact_detail(" ; ".join(parts)),
                "source": "client",
                "source_id": task["id"],
            }
        )

    # Disabled intentionally: these are internal offer-production tasks
    # (generate draft, validate scope, export, etc.), not tasks extracted from
    # client reports. Keep them out of the user classification list so the
    # choices only concern report/client-project tasks.
    # for item in _build_offer_task_items(project):
    #     candidates.append(
    #         {
    #             "task_key": f"offer:{item['id']}",
    #             "title": item["title"],
    #             "detail": item["detail"],
    #             "source": "offer",
    #             "source_id": item["id"],
    #         }
    #     )
    return candidates


def _count_task_report_mentions(title: str, artifacts: list[dict[str, Any]]) -> int:
    tokens = _task_title_lookup_tokens(title)
    if not tokens:
        return 0
    required_matches = 1 if len(tokens) == 1 else min(2, len(tokens))
    count = 0
    for artifact in artifacts:
        haystack = _normalize_lookup(
            " ".join(
                str(artifact.get(key) or "")
                for key in ("title", "content")
            )
        )
        if sum(1 for token in tokens if token in haystack) >= required_matches:
            count += 1
    return count


def _task_title_lookup_tokens(title: str) -> list[str]:
    stopwords = {
        "avec",
        "dans",
        "des",
        "les",
        "pour",
        "sans",
        "sur",
        "une",
        "validation",
        "valider",
    }
    normalized = _normalize_lookup(title)
    seen: set[str] = set()
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", normalized):
        if len(token) < 4 or token in stopwords or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens[:8]


async def _list_offer_task_choices(project_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT task_key, title, detail, source, source_id, decision, created_at::text, updated_at::text
            FROM offer_project_task_choices
            WHERE project_id = $1::uuid
            ORDER BY
              CASE source WHEN 'client' THEN 0 ELSE 1 END,
              created_at ASC,
              title ASC
            """,
            project_id,
        )
    return [dict(row) for row in rows]


def _extract_task_ids_for_decision(normalized_message: str, markers: tuple[str, ...]) -> list[str]:
    all_markers = ("dans l'offre", "dans l offre", "inclure", "inclu", "inclues", "mettre", "mets", "garde", "garder", "conserve", "plus tard", "later", "oublie", "oublier", "retire", "retirer", "supprime", "abandonne")
    ids: list[str] = []
    for marker in markers:
        marker_index = normalized_message.find(marker)
        if marker_index < 0:
            continue
        segment = normalized_message[marker_index:]
        next_positions = [
            segment.find(other)
            for other in all_markers
            if other not in markers and segment.find(other) > 0
        ]
        if next_positions:
            segment = segment[: min(next_positions)]
        found = re.findall(r"\bt\d+\b", segment)
        if not found:
            prefix = normalized_message[:marker_index]
            previous_positions = [prefix.rfind(other) for other in all_markers if other not in markers]
            previous = max(previous_positions) if previous_positions else -1
            segment = prefix[previous + 1 :]
            found = re.findall(r"\bt\d+\b", segment)
        ids.extend(match.upper() for match in found)
    return sorted(set(ids), key=lambda item: int(item[1:]))


def _task_decision_label(decision: str) -> str:
    return {
        "include": "dans l'offre",
        "later": "plus tard",
        "forgotten": "oubliee",
        "pending": "a choisir",
    }.get(decision, "a choisir")


def _summarize_client_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": artifact["id"],
        "client_id": artifact["client_id"],
        "project_id": artifact.get("project_id"),
        "title": artifact["title"],
        "kind": artifact["kind"],
        "excerpt": _excerpt(artifact.get("content") or "", 420),
        "updated_at": artifact.get("updated_at") or "",
    }


async def _compute_completion_ratio(project_id: str) -> int:
    project = await _get_offer_project(project_id)
    items = _build_missing_items(project)
    if not items:
        return 100
    completed = sum(1 for item in items if item["status"] == "completed")
    return round((completed / len(items)) * 100)


def _build_missing_items(project: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for definition in _FIELD_DEFINITIONS:
        answer = str(project.get(definition["key"], "") or "").strip()
        items.append(
            {
                **definition,
                "status": "completed" if answer else "missing",
                "answer": answer,
            }
        )
    return items


def _extract_updates_from_message(
    message: str,
    missing_items: list[dict[str, Any]],
    prompted_field: str | None = None,
) -> dict[str, str]:
    lowered = _normalize(message)
    if _is_generation_request(lowered) or lowered.startswith("ajoute un email"):
        return {}

    if prompted_field == "constraints" and _is_negative_reply(lowered):
        return {"constraints": _NO_CONSTRAINTS_ANSWER}

    explicit = {}
    for key, field in _KEYWORDS_TO_FIELD.items():
        if key in lowered:
            explicit[field] = message.strip()
    if explicit:
        return explicit

    if "client " in lowered or lowered.startswith("pour "):
        return {"client_name": message.strip()}

    first_missing = next((item for item in missing_items if item["status"] == "missing"), None)
    if first_missing is not None and first_missing["key"] == "constraints" and _is_negative_reply(lowered):
        return {"constraints": _NO_CONSTRAINTS_ANSWER}
    if first_missing is not None and len(message.strip()) >= 8 and "?" not in message:
        return {first_missing["key"]: message.strip()}
    return {}


def _field_from_prompted_message(messages: list[dict[str, Any]]) -> str | None:
    last_agent_message = next((item for item in reversed(messages) if item.get("role") == "agent"), None)
    if not last_agent_message:
        return None
    normalized_content = _normalize(str(last_agent_message.get("content", "")))
    for definition in _FIELD_DEFINITIONS:
        if _normalize(definition["prompt"]) in normalized_content:
            return definition["key"]
    return None


def _next_missing_prompt(missing_items: list[dict[str, Any]]) -> str:
    missing = [item for item in missing_items if item["status"] == "missing"]
    if not missing:
        return "Toutes les donnees critiques sont completes."
    first = missing[0]
    critical_left = sum(1 for item in missing if item["priority"] == "critical")
    suffix = f" Il reste {critical_left} information(s) critique(s) a completer." if critical_left > 1 else ""
    return first["prompt"] + suffix


def _is_generation_request(normalized_message: str) -> bool:
    return any(
        token in normalized_message
        for token in ("genere l'offre", "genere le brouillon", "genere l offre", "prepare l'offre", "produis l'offre", "finalise l'offre")
    )


def _is_offer_task_request(normalized_message: str) -> bool:
    return any(token in normalized_message for token in ("tache", "taches", "task", "tasks", "todo", "a faire", "action", "actions"))


def _looks_like_offer_task_decision(normalized_message: str) -> bool:
    if not re.search(r"\bt\d+\b", normalized_message):
        return False
    return any(
        token in normalized_message
        for token in (
            "dans l'offre",
            "dans l offre",
            "offre",
            "inclure",
            "inclu",
            "mettre",
            "mets",
            "garde",
            "garder",
            "conserve",
            "plus tard",
            "retire",
            "retirer",
            "oublie",
            "oublier",
            "supprime",
            "abandonne",
        )
    )


def _build_offer_task_review(project: dict[str, Any]) -> str:
    tasks = _build_offer_task_items(project)
    lines = ["Voici les taches proposees pour terminer cette proposition d'offre :"]
    for task in tasks:
        lines.append(f"- {task['id']} - {task['title']} : {task['detail']}")
    lines.append("")
    lines.append("Dites-moi quoi faire avec chaque tache, par exemple : garder T1 T3, plus tard T2, retirer T4.")
    return "\n".join(lines)


def _build_offer_task_items(project: dict[str, Any]) -> list[dict[str, str]]:
    pricing_detail = _compact_detail(
        " ; ".join(
            item
            for item in (
                str(project.get("pricing_details", "") or "").strip(),
                str(project.get("time_spent_details", "") or "").strip(),
            )
            if item
        )
    )
    return [
        {
            "id": "T1",
            "title": "Generer ou actualiser le brouillon de l'offre",
            "detail": _compact_detail(str(project.get("request_summary", "") or "").strip()),
        },
        {
            "id": "T2",
            "title": "Valider le perimetre de mission",
            "detail": _compact_detail(str(project.get("scope_details", "") or "").strip()),
        },
        {
            "id": "T3",
            "title": "Valider les livrables",
            "detail": _compact_detail(str(project.get("deliverables", "") or "").strip()),
        },
        {
            "id": "T4",
            "title": "Confirmer le planning et les jalons",
            "detail": _compact_detail(str(project.get("planning_details", "") or "").strip()),
        },
        {
            "id": "T5",
            "title": "Verifier le chiffrage et la charge",
            "detail": pricing_detail,
        },
        {
            "id": "T6",
            "title": "Confirmer l'equipe proposee",
            "detail": _compact_detail(str(project.get("team_details", "") or "").strip()),
        },
        {
            "id": "T7",
            "title": "Verifier les contraintes, hypotheses et exclusions",
            "detail": _compact_detail(str(project.get("constraints", "") or "").strip()),
        },
        {
            "id": "T8",
            "title": "Relire, exporter et envoyer la proposition finale",
            "detail": "DOCX ou PDF selon le format attendu.",
        },
    ]


def _compact_detail(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        return "A confirmer."
    return normalized[:180] + ("..." if len(normalized) > 180 else "")


def _summarize_offer_task_decision(message: str) -> str:
    normalized = _normalize(message)
    kept = _extract_task_ids_after_decision(normalized, ("garde", "garder", "conserve"))
    later = _extract_task_ids_after_decision(normalized, ("plus tard",))
    removed = _extract_task_ids_after_decision(normalized, ("retire", "retirer", "supprime", "abandonne"))

    lines = ["C'est note pour les taches de la proposition :"]
    if kept:
        lines.append(f"- A garder : {', '.join(kept)}")
    if later:
        lines.append(f"- A faire plus tard : {', '.join(later)}")
    if removed:
        lines.append(f"- A retirer : {', '.join(removed)}")
    if not (kept or later or removed):
        lines.append("- Je n'ai pas identifie clairement le classement. Utilisez par exemple : garder T1 T3, plus tard T2, retirer T4.")
    lines.append("Vous pouvez encore modifier ce choix ou me demander de generer le brouillon final.")
    return "\n".join(lines)


def _extract_task_ids_after_decision(normalized_message: str, markers: tuple[str, ...]) -> list[str]:
    ids: list[str] = []
    for marker in markers:
        marker_index = normalized_message.find(marker)
        if marker_index < 0:
            continue
        segment = normalized_message[marker_index:]
        next_marker_positions = [
            segment.find(other)
            for other in ("garde", "garder", "conserve", "plus tard", "retire", "retirer", "supprime", "abandonne")
            if other not in markers and segment.find(other) > 0
        ]
        if next_marker_positions:
            segment = segment[: min(next_marker_positions)]
        ids.extend(match.upper() for match in re.findall(r"\bt\d+\b", segment))
    return sorted(set(ids), key=lambda item: int(item[1:]))


def _is_negative_reply(normalized_message: str) -> bool:
    if normalized_message in _NEGATIVE_SHORT_REPLIES:
        return True
    return any(
        normalized_message.startswith(prefix)
        for prefix in (
            "pas de contrainte",
            "pas d'hypothese",
            "pas d exclusion",
            "pas d'exclusion",
            "aucune contrainte",
            "aucune hypothese",
            "aucune exclusion",
        )
    )


async def _match_offer_references(site_id: str, project: dict[str, Any]) -> list[dict[str, Any]]:
    query = " ".join(
        [
            project.get("title", "") or "",
            project.get("client_name", "") or "",
            project.get("sector", "") or "",
            project.get("request_summary", "") or "",
            project.get("scope_details", "") or "",
        ]
    )
    query_tokens = _extract_tokens(query)
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, title, client_name, sector, offer_type, delivery_timeline, pricing_notes, team_notes, tags, content, created_at::text
            FROM offer_reference_documents
            WHERE site_id = $1::uuid
            ORDER BY updated_at DESC
            LIMIT 40
            """,
            site_id,
        )
    scored = []
    for row in rows:
        item = dict(row)
        haystack = _normalize(" ".join([item["title"], item["client_name"], item["sector"], item["offer_type"], item["content"]]))
        score = sum(2 for token in query_tokens if token in haystack)
        if project.get("sector") and _normalize(project["sector"]) in haystack:
            score += 4
        if score <= 0:
            continue
        item["excerpt"] = _excerpt(item["content"])
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["title"]))
    return [item for _, item in scored[:3]]


async def _match_team_profiles(site_id: str, project: dict[str, Any]) -> list[dict[str, Any]]:
    query = " ".join(
        [
            project.get("sector", "") or "",
            project.get("request_summary", "") or "",
            project.get("team_details", "") or "",
        ]
    )
    tokens = _extract_tokens(query)
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, full_name, role, seniority, skills, sectors, bio, availability_notes
            FROM team_profiles
            WHERE site_id = $1::uuid
            ORDER BY updated_at DESC
            LIMIT 30
            """,
            site_id,
        )
    scored = []
    for row in rows:
        item = dict(row)
        haystack = _normalize(" ".join([item["full_name"], item["role"], item["seniority"], " ".join(item["skills"]), " ".join(item["sectors"]), item["bio"]]))
        score = sum(2 for token in tokens if token in haystack)
        if project.get("sector") and _normalize(project["sector"]) in haystack:
            score += 3
        if score <= 0 and tokens:
            continue
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["full_name"]))
    return [item for _, item in scored[:3]]


async def _list_offer_project_emails(project_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, subject, sender, content, created_at::text
            FROM offer_project_emails
            WHERE project_id = $1::uuid
            ORDER BY created_at DESC
            """,
            project_id,
        )
    items = []
    for row in rows:
        item = dict(row)
        item["excerpt"] = _excerpt(item["content"])
        item.pop("content", None)
        items.append(item)
    return items


async def _list_offer_project_exports(project_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, format, filename, created_at::text
            FROM offer_project_exports
            WHERE project_id = $1::uuid
            ORDER BY created_at DESC
            """,
            project_id,
        )
    return [dict(row) for row in rows]


async def _list_offer_project_files(project_id: str) -> list[dict[str, Any]]:
    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id::text, filename, content_type, size_bytes, extracted_text, created_at::text
            FROM offer_project_files
            WHERE project_id = $1::uuid
            ORDER BY created_at DESC
            """,
            project_id,
        )
    items = []
    for row in rows:
        item = dict(row)
        item["excerpt"] = _excerpt(item.pop("extracted_text", "") or f"Fichier charge: {item['filename']}")
        items.append(item)
    return items


def _build_offer_markdown(
    project: dict[str, Any],
    references: list[dict[str, Any]],
    team_profiles: list[dict[str, Any]],
    client_context: dict[str, Any] | None = None,
    task_choices: list[dict[str, Any]] | None = None,
    previous_offer_markdown: str = "",
) -> str:
    team_fallback = "\n".join(f"- {item['full_name']} - {item['role']}" for item in team_profiles) if team_profiles else "A preciser"
    references_block = "\n".join(
        f"- {item['title']} ({item['sector'] or 'secteur non precise'}) : {item['excerpt']}" for item in references
    ) or "- Aucune reference rapprochee n'a ete retenue"
    client_context = client_context or {}
    artifacts = client_context.get("artifacts", [])
    events = client_context.get("events", [])
    tasks = client_context.get("tasks", [])
    selected_task_choices = [item for item in (task_choices or []) if item.get("decision") == "include"]
    current_tasks_truth_block = _build_offer_tasks_truth_block(tasks, task_choices or [])
    previous_base = _strip_offer_task_truth_section(previous_offer_markdown)
    if previous_base:
        return (
            previous_base
            + _OFFER_TASK_TRUTH_SEPARATOR
            + current_tasks_truth_block
            + "\n\n"
            + "## Base de reprise\n"
            + "Cette version reprend la derniere proposition generee comme source de verite. "
            + "Le bloc ci-dessus remplace l'ancien etat des taches du projet.\n"
        )

    meetings_block = "\n".join(
        f"- {item['title']} ({item.get('kind') or 'document'}) : {item.get('excerpt') or ''}" for item in artifacts
    ) or "- Aucun compte rendu rattache n'a ete charge"
    events_block = "\n".join(
        f"- {item['event_at']} - {item['event_type']} - {item['title']}" + (f" : {item['details']}" if item.get("details") else "")
        for item in events
    ) or "- Aucun evenement rattache n'a ete charge"
    tasks_block = "\n".join(
        f"- {item['title']} [{item.get('status') or 'proposed'}]"
        + (f" - {item['owner']}" if item.get("owner") else "")
        + (f" - echeance {item['due_date']}" if item.get("due_date") else "")
        for item in tasks
    ) or "- Aucune tache existante rattachee"
    selected_tasks_block = "\n".join(
        f"- {item['title']}" + (f" : {item['detail']}" if item.get("detail") else "")
        for item in selected_task_choices
    ) or "- Aucune tache n'a encore ete selectionnee pour apparaitre dans l'offre"
    return (
        f"# Proposition d'offre - {project['title']}\n\n"
        f"## Client cible\n{project['client_name'] or 'A preciser'}\n\n"
        f"## Contexte et besoin\n{project['request_summary'] or 'A preciser'}\n\n"
        f"## Contexte client charge\n"
        f"### Comptes rendus et documents\n{meetings_block}\n\n"
        f"### Reunions et evenements\n{events_block}\n\n"
        f"### Taches existantes\n{tasks_block}\n\n"
        f"### Taches retenues dans l'offre\n{selected_tasks_block}\n\n"
        f"### Etat de reference des taches\n{current_tasks_truth_block}\n\n"
        f"## Perimetre de la mission\n{project['scope_details'] or 'A preciser'}\n\n"
        f"## Livrables\n{project['deliverables'] or 'A preciser'}\n\n"
        f"## Equipe proposee\n{project['team_details'] or team_fallback}\n\n"
        f"## Planning\n{project['planning_details'] or 'A preciser'}\n\n"
        f"## Chiffrage\n{project['pricing_details'] or 'A preciser'}\n\n"
        f"## Charge et temps passe\n{project['time_spent_details'] or 'A preciser'}\n\n"
        f"## Contraintes, hypotheses et exclusions\n{project['constraints'] or 'A preciser'}\n\n"
        f"## References mobilisees\n{references_block}\n\n"
        f"## Conclusion\nNous proposons une approche adaptee au besoin exprime, en nous appuyant sur nos references et sur l'equipe la plus pertinente pour securiser la mission.\n"
    )


def _strip_offer_task_truth_section(markdown: str) -> str:
    normalized = (markdown or "").strip()
    if not normalized:
        return ""
    return normalized.split(_OFFER_TASK_TRUTH_SEPARATOR, 1)[0].strip()


def _build_offer_tasks_truth_block(tasks: list[dict[str, Any]], task_choices: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    if task_choices:
        for decision in ("include", "later", "forgotten", "pending"):
            matching = [item for item in task_choices if (item.get("decision") or "pending") == decision]
            if not matching:
                continue
            lines.append(f"{_task_decision_label(decision).capitalize()} :")
            lines.extend(f"- {item['title']}" + (f" : {item['detail']}" if item.get("detail") else "") for item in matching)
            lines.append("")
    elif tasks:
        lines.append("Taches projet :")
        lines.extend(
            f"- {item['title']} [{item.get('status') or 'proposed'}]"
            + (f" - {item['owner']}" if item.get("owner") else "")
            + (f" - echeance {item['due_date']}" if item.get("due_date") else "")
            for item in tasks
        )
    else:
        lines.append("- Aucune tache projet rattachee")
    return "\n".join(lines).strip()


def _extract_file_text(filename: str, content_type: str, content: bytes) -> str:
    lower_name = filename.lower()
    textual_extensions = (".txt", ".md", ".csv", ".json", ".yml", ".yaml")
    if lower_name.endswith(textual_extensions) or content_type.startswith("text/"):
        return content.decode("utf-8", errors="ignore").strip()
    if lower_name.endswith(".pdf") or content_type == "application/pdf":
        return (
            f"Document PDF charge: {filename}. "
            "Extraction automatique du texte non active dans cette version, "
            "mais le fichier est bien rattache au projet."
        )
    return f"Fichier charge: {filename}"


def _render_export(title: str, markdown: str, export_format: str) -> GeneratedExport:
    safe_stem = _slugify(title or "proposition-offre")
    plain_text = _markdown_to_plain_text(markdown)
    if export_format == "docx":
        return GeneratedExport(
            filename=f"{safe_stem}.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            data=_build_docx(plain_text),
        )
    if export_format == "pdf":
        return GeneratedExport(
            filename=f"{safe_stem}.pdf",
            content_type="application/pdf",
            data=_build_pdf(plain_text),
        )
    raise ValueError("Unsupported export format")


def _build_docx(text: str) -> bytes:
    paragraphs = [line.strip() or "" for line in text.splitlines()]
    body = []
    for paragraph in paragraphs:
        escaped = _xml_escape(paragraph)
        if escaped:
            body.append(
                f"<w:p><w:r><w:t xml:space=\"preserve\">{escaped}</w:t></w:r></w:p>"
            )
        else:
            body.append("<w:p/>")
    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:wpc=\"http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas\" "
        "xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\" "
        "xmlns:o=\"urn:schemas-microsoft-com:office:office\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
        "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\" "
        "xmlns:v=\"urn:schemas-microsoft-com:vml\" "
        "xmlns:wp14=\"http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
        "xmlns:w10=\"urn:schemas-microsoft-com:office:word\" "
        "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:w14=\"http://schemas.microsoft.com/office/word/2010/wordml\" "
        "xmlns:wpg=\"http://schemas.microsoft.com/office/word/2010/wordprocessingGroup\" "
        "xmlns:wpi=\"http://schemas.microsoft.com/office/word/2010/wordprocessingInk\" "
        "xmlns:wne=\"http://schemas.microsoft.com/office/2006/wordml\" "
        "xmlns:wps=\"http://schemas.microsoft.com/office/word/2010/wordprocessingShape\" mc:Ignorable=\"w14 wp14\">"
        f"<w:body>{''.join(body)}<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/></w:sectPr></w:body></w:document>"
    )
    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>"
    )
    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
        "</Relationships>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _build_pdf(text: str) -> bytes:
    lines = [line[:110] for line in text.splitlines() if line.strip()] or ["Proposition d'offre"]
    y = 800
    content_stream_lines = ["BT", "/F1 11 Tf", "40 800 Td"]
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index == 0:
            content_stream_lines.append(f"({escaped}) Tj")
        else:
            y -= 15
            content_stream_lines.append(f"0 -15 Td ({escaped}) Tj")
    content_stream_lines.append("ET")
    stream = "\n".join(content_stream_lines).encode("latin-1", "replace")
    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n")
    objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.append(f"5 0 obj << /Length {len(stream)} >> stream\n".encode("latin-1") + stream + b"\nendstream endobj\n")
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref_start = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    output.extend(
        (
            f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF"
        ).encode("latin-1")
    )
    return bytes(output)


def _markdown_to_plain_text(markdown: str) -> str:
    text = re.sub(r"^#+\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"^\-\s+", "- ", text, flags=re.MULTILINE)
    return text.strip()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _normalize_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _extract_tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]{3,}", _normalize(value)) if token]


def _excerpt(content: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize(value))
    return slug.strip("-") or "proposition-offre"


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

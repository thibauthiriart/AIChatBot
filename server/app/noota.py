from __future__ import annotations

from typing import Any

from server.app.db import db
from server.app.schemas import (
    ClientArtifactSummary,
    ClientEventSummary,
    ClientProjectSummary,
    ClientSummary,
    NootaActionItem,
    NootaImportResponse,
    NootaParticipant,
    NootaReportImport,
)


async def import_noota_report(scope_id: str, payload: NootaReportImport) -> NootaImportResponse:
    client = await _resolve_or_create_client(scope_id, payload)
    project = await _resolve_or_create_project(client["id"], payload.project_name)
    formatted_report = format_noota_report(payload, client["name"], project["name"] if project else "")
    artifact = await _create_artifact(client["id"], project["id"] if project else None, payload, formatted_report)
    event = await _create_event(client["id"], project["id"] if project else None, payload)
    return NootaImportResponse(
        client=ClientSummary(**client),
        project=ClientProjectSummary(**project) if project else None,
        artifact=ClientArtifactSummary(**artifact),
        event=ClientEventSummary(**event),
        formatted_report=formatted_report,
    )


def format_noota_report(payload: NootaReportImport, client_name: str, project_name: str = "") -> str:
    lines: list[str] = []
    lines.append(f"Compte rendu Noota - {payload.meeting_title}")
    lines.append("")
    lines.append("Informations generales")
    lines.append(f"Client: {client_name}")
    if project_name:
        lines.append(f"Projet: {project_name}")
    if payload.meeting_at:
        lines.append(f"Date de reunion: {payload.meeting_at}")
    if payload.language:
        lines.append(f"Langue: {payload.language}")
    if payload.source_url:
        lines.append(f"Source Noota: {payload.source_url}")
    if payload.external_id:
        lines.append(f"Reference externe: {payload.external_id}")

    if payload.participants:
        lines.append("")
        lines.append("Participants")
        for participant in payload.participants:
            suffix = ", ".join(part for part in [participant.role.strip(), participant.company.strip()] if part)
            detail = f" - {suffix}" if suffix else ""
            email = f" ({participant.email.strip()})" if participant.email.strip() else ""
            lines.append(f"- {participant.name}{email}{detail}")

    if payload.summary.strip():
        lines.append("")
        lines.append("Synthese")
        lines.append(payload.summary.strip())

    if payload.key_points:
        lines.append("")
        lines.append("Points cles")
        for item in payload.key_points:
            if item.strip():
                lines.append(f"- {item.strip()}")

    if payload.decisions:
        lines.append("")
        lines.append("Decisions")
        for item in payload.decisions:
            if item.strip():
                lines.append(f"- {item.strip()}")

    if payload.action_items:
        lines.append("")
        lines.append("Actions")
        for action in payload.action_items:
            owner = f" | Responsable: {action.owner.strip()}" if action.owner.strip() else ""
            due_date = f" | Echeance: {action.due_date.strip()}" if action.due_date.strip() else ""
            lines.append(f"- {action.description.strip()}{owner}{due_date}")

    if payload.transcript.strip():
        lines.append("")
        lines.append("Transcript")
        lines.append(payload.transcript.strip())

    return "\n".join(lines).strip()


async def _resolve_or_create_client(scope_id: str, payload: NootaReportImport) -> dict[str, Any]:
    if payload.client_id:
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
                scope_id,
                payload.client_id,
            )
        if row:
            return dict(row)

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
            WHERE site_id = $1::uuid
              AND (
                lower(name) = lower($2)
                OR lower(short_name) = lower($2)
                OR EXISTS (
                  SELECT 1
                  FROM unnest(aliases) alias
                  WHERE lower(alias) = lower($2)
                )
              )
            LIMIT 1
            """,
            scope_id,
            payload.client_name,
        )
        if row:
            existing = dict(row)
            merged_aliases = sorted({*existing.get("aliases", []), *[alias for alias in payload.client_aliases if alias]})
            updated = await connection.fetchrow(
                """
                UPDATE clients
                SET aliases = $3::text[], updated_at = now()
                WHERE id = $1::uuid AND site_id = $2::uuid
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
                existing["id"],
                scope_id,
                merged_aliases,
            )
            return dict(updated)

        created = await connection.fetchrow(
            """
            INSERT INTO clients(site_id, name, short_name, aliases, status, summary, external_ref, updated_at)
            VALUES($1::uuid, $2, $3, $4::text[], 'actif', $5, $6, now())
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
            payload.client_name,
            payload.client_name,
            [alias for alias in payload.client_aliases if alias],
            f"Client alimente depuis un rapport Noota importe automatiquement.",
            payload.external_id,
        )
    return dict(created)


async def _resolve_or_create_project(client_id: str, project_name: str) -> dict[str, Any] | None:
    normalized_name = project_name.strip()
    if not normalized_name:
        return None

    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
              id::text,
              client_id::text,
              name,
              status,
              summary,
              started_on::text,
              due_on::text
            FROM client_projects
            WHERE client_id = $1::uuid AND lower(name) = lower($2)
            LIMIT 1
            """,
            client_id,
            normalized_name,
        )
        if row:
            return dict(row)

        created = await connection.fetchrow(
            """
            INSERT INTO client_projects(client_id, name, status, summary, updated_at)
            VALUES($1::uuid, $2, 'en cours', 'Projet alimente depuis Noota.', now())
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
            normalized_name,
        )
    return dict(created)


async def _create_artifact(
    client_id: str,
    project_id: str | None,
    payload: NootaReportImport,
    formatted_report: str,
) -> dict[str, Any]:
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO client_artifacts(client_id, project_id, title, kind, content, updated_at)
            VALUES($1::uuid, $2::uuid, $3, 'noota_report', $4, now())
            RETURNING
              id::text,
              client_id::text,
              project_id::text,
              title,
              kind
            """,
            client_id,
            project_id,
            payload.meeting_title,
            formatted_report,
        )
    return dict(row)


async def _create_event(client_id: str, project_id: str | None, payload: NootaReportImport) -> dict[str, Any]:
    details = payload.summary.strip() or f"Rapport de reunion importe depuis Noota: {payload.meeting_title}"
    async with db.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO client_events(client_id, project_id, title, event_type, details, event_at)
            VALUES(
              $1::uuid,
              $2::uuid,
              $3,
              'meeting_report',
              $4,
              COALESCE(NULLIF($5, '')::timestamptz, now())
            )
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
            project_id,
            payload.meeting_title,
            details,
            payload.meeting_at or "",
        )
    return dict(row)

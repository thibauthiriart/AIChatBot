from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import httpx

from server.app.config import Settings, get_settings
from server.app.db import db
from server.app.noota import format_noota_report, import_noota_report
from server.app.schemas import CalendarEventSuggestion, NootaDriveFileInfo, NootaDriveImportedItem, NootaDrivePendingItem, NootaDriveStatusResponse, NootaDriveSyncResponse, NootaReportImport


class NootaDriveSyncError(RuntimeError):
    pass


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str = ""


async def ensure_noota_drive_schema() -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS external_imports (
              id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              artifact_id UUID NULL REFERENCES client_artifacts(id) ON DELETE SET NULL,
              imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(provider, external_id)
            )
            """
        )


class GoogleDriveNootaSyncService:
    _scope = "https://www.googleapis.com/auth/drive.readonly"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def sync(self, scope_id: str, folder_id: str | None, limit: int) -> NootaDriveSyncResponse:
        root_folder_id = (folder_id or self.settings.noota_google_drive_root_folder_id).strip()
        if not root_folder_id:
            raise NootaDriveSyncError("NOOTA_GOOGLE_DRIVE_ROOT_FOLDER_ID est manquant.")

        files = await self._list_docx_files(root_folder_id, limit)
        imported_items: list[NootaDriveImportedItem] = []
        skipped_files = 0
        scanned_files = len(files)

        for drive_file in files:
            if await _is_already_imported("google_drive", drive_file.id):
                skipped_files += 1
                continue

            content = await self._download_file(drive_file)
            report = _parse_noota_docx(content, drive_file.name)
            imported = await import_noota_report(scope_id, report)
            await _mark_imported("google_drive", drive_file.id, imported.artifact.id)
            imported_items.append(
                NootaDriveImportedItem(
                    external_id=drive_file.id,
                    file_name=drive_file.name,
                    client_name=report.client_name,
                    project_name=report.project_name,
                    artifact_id=imported.artifact.id,
                )
            )

        return NootaDriveSyncResponse(
            scanned_files=scanned_files,
            imported_files=len(imported_items),
            skipped_files=skipped_files,
            items=imported_items,
        )

    async def list_pending(self, folder_id: str | None, limit: int) -> list[NootaDrivePendingItem]:
        root_folder_id = (folder_id or self.settings.noota_google_drive_root_folder_id).strip()
        if not root_folder_id:
            raise NootaDriveSyncError("NOOTA_GOOGLE_DRIVE_ROOT_FOLDER_ID est manquant.")

        files = await self._list_docx_files(root_folder_id, limit)
        pending_items: list[NootaDrivePendingItem] = []

        for drive_file in files:
            if await _is_already_imported("google_drive", drive_file.id):
                continue

            _, report, formatted_report, suggested_appointments = await self._build_pending_report(drive_file)
            pending_items.append(
                NootaDrivePendingItem(
                    external_id=drive_file.id,
                    file_name=drive_file.name,
                    client_name=report.client_name,
                    project_name=report.project_name,
                    meeting_title=report.meeting_title,
                    meeting_at=report.meeting_at,
                    formatted_report=formatted_report,
                    suggested_appointments=suggested_appointments,
                )
            )

        return pending_items

    async def import_one(self, scope_id: str, external_id: str, folder_id: str | None = None) -> NootaDriveImportedItem:
        if await _is_already_imported("google_drive", external_id):
            raise NootaDriveSyncError("Ce compte rendu est deja importe.")

        root_folder_id = (folder_id or self.settings.noota_google_drive_root_folder_id).strip()
        if not root_folder_id:
            raise NootaDriveSyncError("NOOTA_GOOGLE_DRIVE_ROOT_FOLDER_ID est manquant.")

        files = await self._list_docx_files(root_folder_id, self.settings.noota_google_drive_scan_limit)
        drive_file = next((item for item in files if item.id == external_id), None)
        if not drive_file:
            raise NootaDriveSyncError("Compte rendu introuvable dans Google Drive.")

        _, report, _, _ = await self._build_pending_report(drive_file)
        imported = await import_noota_report(scope_id, report)
        await _mark_imported("google_drive", drive_file.id, imported.artifact.id)
        return NootaDriveImportedItem(
            external_id=drive_file.id,
            file_name=drive_file.name,
            client_name=report.client_name,
            project_name=report.project_name,
            artifact_id=imported.artifact.id,
        )

    async def get_pending_report(self, external_id: str, folder_id: str | None = None) -> tuple[DriveFile, NootaReportImport, str, list[CalendarEventSuggestion]]:
        root_folder_id = (folder_id or self.settings.noota_google_drive_root_folder_id).strip()
        if not root_folder_id:
            raise NootaDriveSyncError("NOOTA_GOOGLE_DRIVE_ROOT_FOLDER_ID est manquant.")

        files = await self._list_docx_files(root_folder_id, self.settings.noota_google_drive_scan_limit)
        drive_file = next((item for item in files if item.id == external_id), None)
        if not drive_file:
            raise NootaDriveSyncError("Compte rendu introuvable dans Google Drive.")
        return await self._build_pending_report(drive_file)

    async def get_status(self, folder_id: str | None, limit: int) -> NootaDriveStatusResponse:
        root_folder_id = (folder_id or self.settings.noota_google_drive_root_folder_id).strip()
        if not root_folder_id:
            raise NootaDriveSyncError("NOOTA_GOOGLE_DRIVE_ROOT_FOLDER_ID est manquant.")

        files = await self._list_docx_files(root_folder_id, max(limit, 20))
        pending_count = 0
        for drive_file in files:
            if not await _is_already_imported("google_drive", drive_file.id):
                pending_count += 1

        return NootaDriveStatusResponse(
            checked_at=datetime.now(timezone.utc).isoformat(),
            scanned_files=len(files),
            pending_files=pending_count,
            latest_files=[
                NootaDriveFileInfo(
                    external_id=item.id,
                    file_name=item.name,
                    modified_time=item.modified_time,
                )
                for item in files[: min(limit, 10)]
            ],
        )

    async def _build_pending_report(self, drive_file: DriveFile) -> tuple[DriveFile, NootaReportImport, str, list[CalendarEventSuggestion]]:
        content = await self._download_file(drive_file)
        report = _parse_noota_docx(content, drive_file.name)
        formatted_report = format_noota_report(report, report.client_name, report.project_name)
        suggested_appointments = _extract_suggested_appointments(report, formatted_report, self.settings.booking_timezone_default)
        return drive_file, report, formatted_report, suggested_appointments

    async def _list_docx_files(self, root_folder_id: str, limit: int) -> list[DriveFile]:
        access_token = await self._get_access_token()
        collected: list[DriveFile] = []
        pending = [root_folder_id]

        async with httpx.AsyncClient(timeout=30) as client:
            while pending:
                folder = pending.pop(0)
                next_page_token = None
                while True:
                    params = {
                        "q": f"'{folder}' in parents and trashed = false",
                        "fields": "nextPageToken,files(id,name,mimeType,modifiedTime)",
                        "pageSize": 100,
                        "orderBy": "modifiedTime desc,name_natural",
                        "supportsAllDrives": "true",
                        "includeItemsFromAllDrives": "true",
                    }
                    if next_page_token:
                        params["pageToken"] = next_page_token

                    response = await client.get(
                        "https://www.googleapis.com/drive/v3/files",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params=params,
                    )
                    if response.status_code >= 400:
                        raise NootaDriveSyncError(f"Impossible de lister le dossier Google Drive ({response.status_code}).")

                    payload = response.json()
                    for item in payload.get("files", []):
                        mime_type = item.get("mimeType", "")
                        if mime_type == "application/vnd.google-apps.folder":
                            pending.append(item["id"])
                            continue
                        if item.get("mimeType") == "application/vnd.google-apps.document" or item.get("name", "").lower().endswith(".docx"):
                            collected.append(
                                DriveFile(
                                    id=item["id"],
                                    name=item["name"],
                                    mime_type=mime_type,
                                    modified_time=item.get("modifiedTime", ""),
                                )
                            )

                    next_page_token = payload.get("nextPageToken")
                    if not next_page_token:
                        break

        collected.sort(key=lambda item: item.modified_time or "", reverse=True)
        return collected[:limit]

    async def _download_file(self, drive_file: DriveFile) -> bytes:
        access_token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=60) as client:
            if drive_file.mime_type == "application/vnd.google-apps.document":
                response = await client.get(
                    f"https://www.googleapis.com/drive/v3/files/{drive_file.id}/export",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    },
                )
            else:
                response = await client.get(
                    f"https://www.googleapis.com/drive/v3/files/{drive_file.id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"alt": "media", "supportsAllDrives": "true"},
                )
        if response.status_code >= 400:
            raise NootaDriveSyncError(f"Impossible de telecharger le fichier Google Drive ({response.status_code}).")
        return response.content

    async def _get_access_token(self) -> str:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:
            raise NootaDriveSyncError("La dependance google-auth est requise pour utiliser Google Drive.") from exc

        if not self.settings.google_service_account_file:
            raise NootaDriveSyncError("GOOGLE_SERVICE_ACCOUNT_FILE est manquant.")

        def load_token() -> str:
            credentials = service_account.Credentials.from_service_account_file(
                self.settings.google_service_account_file,
                scopes=[self._scope],
            )
            if self.settings.google_service_account_subject:
                credentials = credentials.with_subject(self.settings.google_service_account_subject)
            credentials.refresh(Request())
            if not credentials.token:
                raise NootaDriveSyncError("Impossible d'obtenir un jeton Google Drive.")
            return str(credentials.token)

        return await asyncio.to_thread(load_token)


def _parse_noota_docx(content: bytes, file_name: str) -> NootaReportImport:
    paragraphs = _extract_docx_paragraphs(content)
    sections = _split_sections(paragraphs)
    stem = Path(file_name).stem
    title = paragraphs[0] if paragraphs else stem
    client_name, project_name = _infer_client_and_project(stem)
    participants = [_parse_participant(line) for line in sections.get("Participants", []) if line.strip()]
    participants = [item for item in participants if item["name"]]
    actions = sections.get("Actions", [])
    action_items = []
    for action in actions:
        cleaned = action.strip()
        if not cleaned or "aucune action" in cleaned.lower():
            continue
        action_items.append({"description": cleaned, "owner": "", "due_date": ""})

    summary_parts = []
    for section_name in ["Ordre du jour", "Themes abordes", "Perspectives"]:
        for item in sections.get(section_name, []):
            if item.strip():
                summary_parts.append(item.strip())

    return NootaReportImport(
        client_name=client_name,
        project_name=project_name,
        meeting_title=title,
        meeting_at=_extract_date(sections.get("Date", [])),
        summary="\n".join(summary_parts).strip(),
        key_points=sections.get("Themes abordes", []),
        decisions=[],
        action_items=action_items,
        transcript="\n".join(paragraphs).strip(),
        participants=participants,
        source_url="",
        external_id=stem,
    )


def _extract_suggested_appointments(
    report: NootaReportImport,
    formatted_report: str,
    timezone_name: str,
) -> list[CalendarEventSuggestion]:
    candidates: list[str] = []
    candidates.extend(item.description.strip() for item in report.action_items if item.description.strip())
    candidates.extend(line.strip() for line in report.key_points if line.strip())
    candidates.extend(line.strip() for line in report.summary.splitlines() if line.strip())
    candidates.extend(line.strip() for line in formatted_report.splitlines() if line.strip())
    candidates.extend(line.strip() for line in report.transcript.splitlines() if line.strip())

    reference_date = _reference_date(report.meeting_at, timezone_name)
    results: list[CalendarEventSuggestion] = []
    seen: set[tuple[str, str]] = set()

    for line in candidates:
        if not _looks_like_appointment_line(line):
            continue
        start_dt = _extract_suggested_start(line, reference_date, timezone_name)
        if start_dt is None:
            continue

        title = _build_suggestion_title(report, line)
        key = (title, start_dt.isoformat())
        if key in seen:
            continue
        seen.add(key)

        results.append(
            CalendarEventSuggestion(
                title=title,
                start=start_dt.isoformat(),
                end=(start_dt + timedelta(hours=1)).isoformat(),
                timezone=timezone_name,
                source_excerpt=line[:500],
                confidence=0.86,
            )
        )

    results.sort(key=lambda item: item.start)
    return results[:5]


def _reference_date(value: str | None, timezone_name: str) -> date:
    if value:
        parsed = _parse_explicit_date(value, datetime.now(ZoneInfo(timezone_name)).date())
        if parsed is not None:
            return parsed
    return datetime.now(ZoneInfo(timezone_name)).date()


def _looks_like_appointment_line(value: str) -> bool:
    normalized = _normalize_text(value)
    return any(
        marker in normalized
        for marker in (
            "rendez-vous",
            "rendez vous",
            "rdv",
            "prochaine reunion",
            "prochain point",
            "prochain appel",
            "prochain echange",
            "meet",
            "visio",
            "call",
        )
    )


def _build_suggestion_title(report: NootaReportImport, source_line: str) -> str:
    cleaned = source_line.strip(" -")
    if len(cleaned) <= 90:
        return cleaned
    base = f"Rendez-vous - {report.client_name}"
    if report.project_name:
        return f"{base} / {report.project_name}"
    return base


def _extract_suggested_start(value: str, reference_date: date, timezone_name: str) -> datetime | None:
    suggested_date = _extract_relative_or_named_date(value, reference_date)
    if suggested_date is None:
        suggested_date = _parse_explicit_date(value, reference_date)
    suggested_time = _extract_time_hint(value)
    if suggested_date is None or suggested_time is None:
        return None
    return datetime.combine(suggested_date, suggested_time, tzinfo=ZoneInfo(timezone_name))


def _extract_relative_or_named_date(value: str, reference_date: date) -> date | None:
    normalized = _normalize_text(value)
    if "apres-demain" in normalized or "apres demain" in normalized:
        return reference_date + timedelta(days=2)
    if "demain" in normalized:
        return reference_date + timedelta(days=1)

    weekdays = {
        "lundi": 0,
        "mardi": 1,
        "mercredi": 2,
        "jeudi": 3,
        "vendredi": 4,
        "samedi": 5,
        "dimanche": 6,
    }
    for label, weekday in weekdays.items():
        if label in normalized:
            delta = (weekday - reference_date.weekday()) % 7
            delta = 7 if delta == 0 else delta
            return reference_date + timedelta(days=delta)
    return None


def _parse_explicit_date(value: str, reference_date: date) -> date | None:
    iso_match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", value)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            return None

    fr_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}|\d{2}))?\b", value)
    if fr_match:
        year_group = fr_match.group(3)
        year = reference_date.year
        if year_group:
            year = int(year_group)
            if year < 100:
                year = 2000 + year if year <= 69 else 1900 + year
        try:
            candidate = date(year, int(fr_match.group(2)), int(fr_match.group(1)))
        except ValueError:
            return None
        if not year_group and candidate < reference_date:
            try:
                candidate = date(year + 1, int(fr_match.group(2)), int(fr_match.group(1)))
            except ValueError:
                return None
        return candidate

    month_names = {
        "janvier": 1,
        "fevrier": 2,
        "février": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "aout": 8,
        "août": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "decembre": 12,
        "décembre": 12,
    }
    month_match = re.search(
        r"\b(\d{1,2})\s+(janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre)(?:\s+(20\d{2}))?\b",
        value,
        flags=re.IGNORECASE,
    )
    if month_match:
        month_label = month_match.group(2).lower()
        year = int(month_match.group(3)) if month_match.group(3) else reference_date.year
        try:
            candidate = date(year, month_names[month_label], int(month_match.group(1)))
        except ValueError:
            return None
        if not month_match.group(3) and candidate < reference_date:
            try:
                candidate = date(year + 1, month_names[month_label], int(month_match.group(1)))
            except ValueError:
                return None
        return candidate
    return None


def _extract_time_hint(value: str) -> time | None:
    match = re.search(r"\b(\d{1,2})[:h](\d{2})?\b", value, flags=re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "00")
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _normalize_text(value: str) -> str:
    return (
        value.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("â", "a")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ô", "o")
        .replace("ù", "u")
        .replace("ç", "c")
    )


def _extract_docx_paragraphs(content: bytes) -> list[str]:
    from xml.etree import ElementTree as ET

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(re.sub(r"\s+", " ", line))
    return paragraphs


def _split_sections(paragraphs: list[str]) -> dict[str, list[str]]:
    known_sections = {
        "Participants": "Participants",
        "Date": "Date",
        "Ordre du jour": "Ordre du jour",
        "Thèmes abordés": "Themes abordes",
        "Actions": "Actions",
        "Perspectives": "Perspectives",
    }
    sections: dict[str, list[str]] = {}
    current = "General"
    sections[current] = []
    for paragraph in paragraphs[1:]:
        matched_inline = False
        for heading, normalized in known_sections.items():
            if paragraph == heading:
                current = normalized
                sections.setdefault(current, [])
                matched_inline = True
                break
            if paragraph.startswith(f"{heading} "):
                current = normalized
                sections.setdefault(current, [])
                remainder = paragraph[len(heading) :].strip(" :-")
                if remainder:
                    sections[current].append(remainder)
                matched_inline = True
                break
        if matched_inline:
            continue
        sections.setdefault(current, []).append(paragraph)
    return sections


def _infer_client_and_project(stem: str) -> tuple[str, str]:
    parts = [item.strip() for item in stem.split(" - ") if item.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1]
    if len(parts) == 2:
        return parts[0], ""
    return "Client a qualifier", ""


def _parse_participant(line: str) -> dict[str, str]:
    cleaned = re.sub(r"^-\s*", "", line).strip()
    return {
        "name": cleaned,
        "email": "",
        "role": "",
        "company": "",
    }


def _extract_date(lines: list[str]) -> str | None:
    for line in lines:
        cleaned = line.strip()
        match = re.search(r"(\d{4}-\d{2}-\d{2})", cleaned)
        if match:
            return f"{match.group(1)}T09:00:00+02:00"
    return None


async def _is_already_imported(provider: str, external_id: str) -> bool:
    async with db.acquire() as connection:
        return bool(
            await connection.fetchval(
                "SELECT 1 FROM external_imports WHERE provider = $1 AND external_id = $2",
                provider,
                external_id,
            )
        )


async def _mark_imported(provider: str, external_id: str, artifact_id: str) -> None:
    async with db.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO external_imports(provider, external_id, artifact_id)
            VALUES($1, $2, $3::uuid)
            ON CONFLICT(provider, external_id) DO NOTHING
            """,
            provider,
            external_id,
            artifact_id,
        )

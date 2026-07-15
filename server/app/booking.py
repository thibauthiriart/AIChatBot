from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from email.utils import parseaddr
from typing import Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from server.app.config import Settings, get_settings
from server.app.schemas import BookingConfirmation, BookingRequest, BookingResult, BookingSlot, CalendarEventRequest, ConversationMessage


class BookingProviderError(RuntimeError):
    pass


class BookingProvider(Protocol):
    async def list_available_slots(self, requested_day: date, timezone_name: str) -> list[BookingSlot]:
        ...

    async def create_appointment(self, request: BookingRequest) -> BookingConfirmation:
        ...

    async def create_event(self, request: CalendarEventRequest) -> BookingConfirmation:
        ...


@dataclass
class BookingContext:
    name: str | None = None
    email: str | None = None
    timezone_name: str | None = None
    requested_day: date | None = None
    requested_time: time | None = None
    requested_period: str | None = None
    pending_start: datetime | None = None


class BookingService:
    def __init__(self, settings: Settings | None = None, provider: BookingProvider | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or _build_provider(self.settings)

    async def handle_message(self, message: str, history: list[ConversationMessage]) -> BookingResult:
        context = self._build_context(message, history)
        if _is_confirmation_message(message) and context.pending_start is not None:
            return await self._confirm_appointment(context)

        missing_fields = self._missing_fields(context)
        if missing_fields:
            return BookingResult(status="needs_info", message=self._build_missing_info_message(missing_fields))

        if context.requested_day is None:
            return BookingResult(
                status="needs_info",
                message=(
                    "Je peux vous aider a reserver. Indiquez au minimum une date explicite au format JJ/MM/AAAA "
                    "ou AAAA-MM-JJ."
                ),
            )

        try:
            slots = await self.provider.list_available_slots(context.requested_day, context.timezone_name or self.settings.booking_timezone_default)
        except BookingProviderError as exc:
            return BookingResult(status="error", message=str(exc))

        if not slots:
            formatted_day = context.requested_day.strftime("%d/%m/%Y")
            return BookingResult(
                status="error",
                message=f"Aucun creneau n'est disponible le {formatted_day}. Proposez une autre date.",
            )

        selected_slot = _match_slot(slots, context.requested_time)
        if selected_slot is None:
            suggested_slots = _select_suggested_slots(slots, context, self.settings.booking_max_suggestions)
            return BookingResult(
                status="slot_selection",
                message=_format_slot_prompt(
                    context.requested_day,
                    context.timezone_name or self.settings.booking_timezone_default,
                    suggested_slots,
                ),
                slots=suggested_slots,
            )

        return BookingResult(
            status="confirmation",
            message=(
                f"Je recapitule : rendez-vous le {selected_slot.start[:10]} a {selected_slot.label.split(' ')[-1]} "
                f"({selected_slot.timezone}), au nom de {context.name}, email {context.email}. "
                "Confirmez-vous la reservation ?"
            ),
            slots=[selected_slot],
        )

    async def _confirm_appointment(self, context: BookingContext) -> BookingResult:
        if context.pending_start is None or context.name is None or context.email is None:
            return BookingResult(
                status="needs_info",
                message="Il me manque encore le nom, l'email ou le creneau a confirmer.",
            )

        timezone_name = context.timezone_name or self.settings.booking_timezone_default
        start = context.pending_start
        end = start + timedelta(minutes=self.settings.booking_slot_duration_minutes)
        request = BookingRequest(
            name=context.name,
            email=context.email,
            start=start.isoformat(),
            end=end.isoformat(),
            timezone=timezone_name,
            summary=self.settings.booking_event_summary,
            description=f"Reservation creee par l'assistant pour {context.name} ({context.email}).",
        )
        try:
            confirmation = await self.provider.create_appointment(request)
        except BookingProviderError as exc:
            return BookingResult(status="error", message=str(exc))

        local_start = start.astimezone(ZoneInfo(timezone_name))
        return BookingResult(
            status="confirmed",
            message=(
                f"Votre rendez-vous est confirme pour le {local_start.strftime('%d/%m/%Y')} a "
                f"{local_start.strftime('%H:%M')} ({timezone_name})."
            ),
            confirmation=confirmation,
            request=request,
        )

    def _build_context(self, message: str, history: list[ConversationMessage]) -> BookingContext:
        visitor_text = "\n".join(item.content for item in history if item.role == "visitor")
        combined_visitor_text = "\n".join(part for part in [visitor_text, message] if part.strip())
        last_agent_message = next((item.content for item in reversed(history) if item.role == "agent"), "")
        requested_identity_fields = _extract_requested_identity_fields(last_agent_message)

        timezone_name = _extract_timezone(combined_visitor_text) or self.settings.booking_timezone_default
        requested_day = _extract_date(combined_visitor_text, timezone_name)
        requested_time = _extract_time(combined_visitor_text)
        requested_period = _extract_period(combined_visitor_text)
        pending_start = _extract_pending_start(last_agent_message, timezone_name)
        direct_name = _extract_direct_name_reply(message, requested_identity_fields)
        direct_email = _extract_direct_email_reply(message, requested_identity_fields)
        return BookingContext(
            name=_extract_name(combined_visitor_text) or direct_name,
            email=_extract_email(combined_visitor_text) or direct_email,
            timezone_name=timezone_name,
            requested_day=requested_day,
            requested_time=requested_time,
            requested_period=requested_period,
            pending_start=pending_start,
        )

    @staticmethod
    def _missing_fields(context: BookingContext) -> list[str]:
        missing: list[str] = []
        if context.name is None:
            missing.append("name")
        if context.email is None:
            missing.append("email")
        return missing

    @staticmethod
    def _build_missing_info_message(missing_fields: list[str]) -> str:
        labels = {
            "name": "votre nom",
            "email": "votre email",
        }
        requested = ", ".join(labels[item] for item in missing_fields)
        return f"Pour reserver, j'ai besoin de {requested}."


class GoogleCalendarBookingProvider:
    _scope = "https://www.googleapis.com/auth/calendar"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def list_available_slots(self, requested_day: date, timezone_name: str) -> list[BookingSlot]:
        self._validate_configuration()
        day_timezone = ZoneInfo(timezone_name)
        day_start = datetime.combine(requested_day, time(self.settings.booking_workday_start_hour, 0), tzinfo=day_timezone)
        day_end = datetime.combine(requested_day, time(self.settings.booking_workday_end_hour, 0), tzinfo=day_timezone)

        busy_ranges = await self._fetch_busy_ranges(day_start, day_end, timezone_name)
        slots: list[BookingSlot] = []
        slot_cursor = day_start
        slot_duration = timedelta(minutes=self.settings.booking_slot_duration_minutes)
        while slot_cursor + slot_duration <= day_end:
            slot_end = slot_cursor + slot_duration
            if not _has_overlap(slot_cursor, slot_end, busy_ranges):
                slots.append(
                    BookingSlot(
                        start=slot_cursor.isoformat(),
                        end=slot_end.isoformat(),
                        timezone=timezone_name,
                        label=slot_cursor.strftime("%H:%M"),
                    )
                )
            slot_cursor += slot_duration
        return slots

    async def create_appointment(self, request: BookingRequest) -> BookingConfirmation:
        return await self.create_event(
            CalendarEventRequest(
                summary=request.summary,
                start=request.start,
                end=request.end,
                timezone=request.timezone,
                description=request.description,
                attendee_name=request.name,
                attendee_email=request.email,
            )
        )

    async def create_event(self, request: CalendarEventRequest) -> BookingConfirmation:
        self._validate_configuration()
        start_at = datetime.fromisoformat(request.start)
        end_at = datetime.fromisoformat(request.end)
        busy_ranges = await self._fetch_busy_ranges(start_at, end_at, request.timezone)
        if _has_overlap(start_at, end_at, busy_ranges):
            raise BookingProviderError(
                f"Le creneau {start_at.astimezone(ZoneInfo(request.timezone)).strftime('%d/%m/%Y %H:%M')} "
                f"({request.timezone}) est deja occupe."
            )
        access_token = await self._get_access_token()
        calendar_id = quote(self.settings.google_calendar_id, safe="")
        payload = {
            "summary": request.summary,
            "description": request.description,
            "start": {"dateTime": request.start, "timeZone": request.timezone},
            "end": {"dateTime": request.end, "timeZone": request.timezone},
        }
        if self.settings.google_service_account_subject and request.attendee_email.strip():
            payload["attendees"] = [{"email": request.attendee_email.strip(), "displayName": request.attendee_name.strip()}]

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise BookingProviderError(
                f"Impossible de creer le rendez-vous Google Calendar ({response.status_code}): "
                f"{_extract_google_error_detail(response)}"
            )

        data = response.json()
        return BookingConfirmation(event_id=str(data.get("id", "")), html_link=data.get("htmlLink"))

    def _validate_configuration(self) -> None:
        if self.settings.booking_provider != "google_calendar":
            raise BookingProviderError("Le provider de reservation n'est pas configure pour Google Calendar.")
        if not self.settings.google_calendar_id:
            raise BookingProviderError("GOOGLE_CALENDAR_ID est manquant.")
        if not self.settings.google_service_account_file:
            raise BookingProviderError("GOOGLE_SERVICE_ACCOUNT_FILE est manquant.")

    async def _fetch_busy_ranges(
        self,
        day_start: datetime,
        day_end: datetime,
        timezone_name: str,
    ) -> list[tuple[datetime, datetime]]:
        access_token = await self._get_access_token()
        payload = {
            "timeMin": day_start.isoformat(),
            "timeMax": day_end.isoformat(),
            "timeZone": timezone_name,
            "items": [{"id": self.settings.google_calendar_id}],
        }

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise BookingProviderError(
                f"Impossible de lire les disponibilites Google Calendar ({response.status_code}): "
                f"{_extract_google_error_detail(response)}"
            )

        data = response.json()
        raw_busy = data.get("calendars", {}).get(self.settings.google_calendar_id, {}).get("busy", [])
        return [
            (
                datetime.fromisoformat(item["start"]),
                datetime.fromisoformat(item["end"]),
            )
            for item in raw_busy
        ]

    async def _get_access_token(self) -> str:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:
            raise BookingProviderError(
                "La dependance google-auth est requise pour utiliser Google Calendar."
            ) from exc

        def load_token() -> str:
            credentials = service_account.Credentials.from_service_account_file(
                self.settings.google_service_account_file,
                scopes=[self._scope],
            )
            if self.settings.google_service_account_subject:
                credentials = credentials.with_subject(self.settings.google_service_account_subject)
            credentials.refresh(Request())
            if not credentials.token:
                raise BookingProviderError("Impossible d'obtenir un jeton Google Calendar.")
            return str(credentials.token)

        return await asyncio.to_thread(load_token)


def is_booking_follow_up(message: str, history: list[ConversationMessage]) -> bool:
    if is_appointment_lookup_request(message, history):
        return False
    if _contains_booking_keyword(message):
        return True
    last_agent_message = next((item.content for item in reversed(history) if item.role == "agent"), "")
    if not last_agent_message:
        return False
    follow_up_markers = (
        "Pour reserver",
        "Quel creneau",
        "Confirmez-vous la reservation",
        "Proposez une autre date",
    )
    return any(marker.lower() in last_agent_message.lower() for marker in follow_up_markers)


def is_appointment_lookup_request(message: str, history: list[ConversationMessage]) -> bool:
    combined_history = " ".join(item.content for item in history[-6:] if item.role in {"visitor", "agent"})
    normalized = _normalize(message)
    normalized_history = _normalize(combined_history)
    has_appointment_term = any(term in normalized for term in ("rendez-vous", "rendez vous", "rdv"))
    if not has_appointment_term:
        return False

    has_booking_action_marker = any(
        marker in normalized
        for marker in ("je veux", "prendre", "reserver", "reservation", "creneau", "disponibilite", "appel")
    )
    if has_booking_action_marker:
        return False

    has_time_marker = any(
        marker in normalized
        for marker in ("aujourd'hui", "aujourdhui", "du jour", "ce jour", "today")
    )
    has_lookup_marker = any(
        marker in normalized
        for marker in (
            "quels",
            "quel",
            "liste",
            "affiche",
            "montre",
            "donne",
            "combien",
            "les rdv",
            "les rendez-vous",
            "les rendez vous",
            "y a t il",
            "est ce qu'il y a",
            "est ce qu il y a",
            "ont ete",
            "etaient",
            "pris",
        )
    )
    has_state_marker = any(
        marker in normalized
        for marker in (
            "programme",
            "programmes",
            "prevu",
            "prevus",
            "planifie",
            "planifies",
            "reserve",
            "reserves",
            "pris",
            "prises",
        )
    )
    has_meeting_context = any(
        marker in f"{normalized} {normalized_history}"
        for marker in ("reunion", "reunions", "meeting", "compte rendu", "compte-rendu", "ces reunions", "cette reunion")
    )
    return (has_lookup_marker or has_state_marker) and (has_time_marker or has_meeting_context or has_state_marker)


def _build_provider(settings: Settings) -> BookingProvider:
    if settings.booking_provider == "google_calendar":
        return GoogleCalendarBookingProvider(settings)
    raise BookingProviderError(f"Provider de reservation non supporte: {settings.booking_provider}")


def _contains_booking_keyword(message: str) -> bool:
    lowered = _normalize(message)
    return any(
        keyword in lowered
        for keyword in (
            "rendez-vous",
            "rendez vous",
            "rdv",
            "reserver",
            "reservation",
            "creneau",
            "appel",
            "disponibilite",
        )
    )


def _normalize(value: str) -> str:
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


def _extract_google_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] if text else "aucun detail retourne par Google"

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        status = str(error.get("status", "")).strip()
        details = []
        if status:
            details.append(status)
        if message:
            details.append(message)
        if details:
            return " - ".join(details)
    return str(payload)[:300] if payload else "aucun detail retourne par Google"


def _extract_email(text: str) -> str | None:
    match = re.search(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", text, flags=re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip()
    _, parsed_email = parseaddr(candidate)
    return parsed_email or None


def _extract_name(text: str) -> str | None:
    patterns = (
        r"\bje m[' ]appelle\s+([A-Za-zÀ-ÿ' -]{2,80})",
        r"\bmon nom est\s+([A-Za-zÀ-ÿ' -]{2,80})",
        r"\bnom\s*[:=]\s*([A-Za-zÀ-ÿ' -]{2,80})",
        r"\bnom\s+([A-Za-zÀ-ÿ' -]{2,80})",
        r"\bc[' ]est\s+([A-Za-zÀ-ÿ' -]{2,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!?:;")
    return None


def _extract_requested_identity_fields(last_agent_message: str) -> set[str]:
    normalized = _normalize(last_agent_message)
    if "pour reserver" not in normalized:
        return set()

    requested: set[str] = set()
    if "nom" in normalized:
        requested.add("name")
    if "email" in normalized:
        requested.add("email")
    return requested


def _extract_timezone(text: str) -> str | None:
    match = re.search(r"\b([A-Za-z_]+/[A-Za-z_]+)\b", text)
    if match:
        timezone_name = match.group(1)
        try:
            ZoneInfo(timezone_name)
            return timezone_name
        except Exception:
            return None
    return None


def _extract_date(text: str, timezone_name: str) -> date | None:
    normalized = _normalize(text)
    now = datetime.now(ZoneInfo(timezone_name)).date()

    if "apres-demain" in normalized or "apres demain" in normalized:
        return now + timedelta(days=2)
    if "demain" in normalized:
        return now + timedelta(days=1)
    if "aujourd'hui" in text.lower() or "aujourdhui" in normalized:
        return now

    iso_match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if iso_match:
        return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))

    fr_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", text)
    if fr_match:
        return date(int(fr_match.group(3)), int(fr_match.group(2)), int(fr_match.group(1)))

    fr_short_year_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2})\b", text)
    if fr_short_year_match:
        year = int(fr_short_year_match.group(3))
        full_year = 2000 + year if year <= 69 else 1900 + year
        return date(full_year, int(fr_short_year_match.group(2)), int(fr_short_year_match.group(1)))
    return None


def _extract_time(text: str) -> time | None:
    match = re.search(r"\b(\d{1,2})[:h](\d{2})?\b", text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\ba\s*(\d{1,2})\b", _normalize(text))
    if not match:
        return None
    hour = int(match.group(1))
    minute = int((match.group(2) if len(match.groups()) > 1 else None) or "00")
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _extract_period(text: str) -> str | None:
    normalized = _normalize(text)
    if "apres midi" in normalized or "apres-midi" in normalized:
        return "afternoon"
    if "matin" in normalized:
        return "morning"
    if "plus tard" in normalized:
        return "later"
    if "plus tot" in normalized or "plus tot le matin" in normalized:
        return "earlier"
    return None


def _extract_direct_name_reply(message: str, requested_fields: set[str]) -> str | None:
    if "name" not in requested_fields:
        return None

    labeled_name = _extract_name(message)
    if labeled_name is not None:
        return labeled_name

    candidate = message.strip(" \n\t.,!?;:")
    if not candidate or len(candidate) < 2 or len(candidate) > 80:
        return None
    if _extract_email(candidate) is not None:
        return None
    if _extract_date(candidate, "Europe/Paris") is not None or _extract_time(candidate) is not None:
        return None
    if _contains_booking_keyword(candidate) or _is_confirmation_message(candidate):
        return None
    if not re.fullmatch(r"[A-Za-zÀ-ÿ' -]{2,80}", candidate):
        return None
    return candidate


def _extract_direct_email_reply(message: str, requested_fields: set[str]) -> str | None:
    if "email" not in requested_fields:
        return None
    return _extract_email(message)


def _extract_pending_start(last_agent_message: str, timezone_name: str) -> datetime | None:
    match = re.search(r"rendez-vous le (\d{4}-\d{2}-\d{2}) a (\d{2}:\d{2})", last_agent_message)
    if not match:
        return None
    return datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}:00").replace(tzinfo=ZoneInfo(timezone_name))


def _is_confirmation_message(message: str) -> bool:
    normalized = _normalize(message.strip())
    if normalized in {"oui", "oui.", "ok", "ok.", "je confirme", "confirme", "c'est confirme", "go"}:
        return True
    return bool(re.search(r"\b(oui|ok)\b", normalized) and re.search(r"\bconfirm", normalized))


def _match_slot(slots: list[BookingSlot], requested_time: time | None) -> BookingSlot | None:
    if requested_time is None:
        return None
    for slot in slots:
        slot_start = datetime.fromisoformat(slot.start)
        if slot_start.time().hour == requested_time.hour and slot_start.time().minute == requested_time.minute:
            return slot
    return None


def _select_suggested_slots(slots: list[BookingSlot], context: BookingContext, max_suggestions: int) -> list[BookingSlot]:
    if len(slots) <= max_suggestions:
        return slots

    prioritized = slots
    if context.requested_time is not None:
        prioritized = [
            slot
            for slot in slots
            if datetime.fromisoformat(slot.start).time() >= context.requested_time
        ] or slots
    elif context.requested_period in {"afternoon", "later"}:
        prioritized = [
            slot
            for slot in slots
            if datetime.fromisoformat(slot.start).time() >= time(12, 0)
        ] or slots
    elif context.requested_period in {"morning", "earlier"}:
        prioritized = [
            slot
            for slot in slots
            if datetime.fromisoformat(slot.start).time() < time(12, 0)
        ] or slots

    return prioritized[:max_suggestions]


def _format_slot_prompt(requested_day: date, timezone_name: str, slots: list[BookingSlot]) -> str:
    slot_labels = ", ".join(slot.label for slot in slots)
    return (
        f"Je peux vous proposer ces creneaux le {requested_day.strftime('%d/%m/%Y')} "
        f"({timezone_name}) : {slot_labels}. Quel creneau choisissez-vous ?"
    )


def _has_overlap(start: datetime, end: datetime, busy_ranges: list[tuple[datetime, datetime]]) -> bool:
    for busy_start, busy_end in busy_ranges:
        if start < busy_end and end > busy_start:
            return True
    return False

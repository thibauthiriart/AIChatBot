from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app.booking import BookingService
from server.app.config import get_settings
from server.app.schemas import BookingRequest


async def main() -> None:
    settings = get_settings()
    service = BookingService(settings)
    target_day = date.today() + timedelta(days=1)
    slots = await service.provider.list_available_slots(target_day, settings.booking_timezone_default)
    if not slots:
        raise RuntimeError("No available slots found")

    slot = slots[0]
    request = BookingRequest(
        name="Thibaut Hiriart",
        email="thibaut.hiriart@gmail.com",
        start=slot.start,
        end=slot.end,
        timezone=slot.timezone,
        summary="Test Booking AgentIA",
        description="Rendez-vous de test cree automatiquement depuis AgentIA.",
    )
    try:
        confirmation = await service.provider.create_appointment(request)
        print("event_id", confirmation.event_id)
        print("html_link", confirmation.html_link or "")
        print("start", slot.start)
        print("end", slot.end)
    except Exception as exc:
        provider = service.provider
        access_token = await provider._get_access_token()
        calendar_id = quote(settings.google_calendar_id, safe="")
        payload = {
            "summary": request.summary,
            "description": request.description,
            "start": {"dateTime": request.start, "timeZone": request.timezone},
            "end": {"dateTime": request.end, "timeZone": request.timezone},
            "attendees": [{"email": request.email, "displayName": request.name}],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
        print("creation_error", type(exc).__name__, str(exc))
        print("status_code", response.status_code)
        print("response_body", response.text)
        raise


if __name__ == "__main__":
    asyncio.run(main())

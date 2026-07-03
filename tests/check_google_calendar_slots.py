from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app.booking import BookingService
from server.app.config import get_settings


async def main() -> None:
    settings = get_settings()
    service = BookingService(settings)
    target_day = date.today() + timedelta(days=1)
    slots = await service.provider.list_available_slots(target_day, settings.booking_timezone_default)
    print("slots_ok", len(slots))
    for slot in slots:
        print(slot.start, slot.end, slot.timezone)


if __name__ == "__main__":
    asyncio.run(main())

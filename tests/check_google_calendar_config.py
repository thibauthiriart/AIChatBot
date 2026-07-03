from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app.booking import GoogleCalendarBookingProvider
from server.app.config import get_settings


async def main() -> None:
    settings = get_settings()
    provider = GoogleCalendarBookingProvider(settings)
    provider._validate_configuration()
    token = await provider._get_access_token()
    print("google_access_token_ok", bool(token))


if __name__ == "__main__":
    asyncio.run(main())

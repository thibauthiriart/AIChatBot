from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app.main import chat
from server.app.schemas import ChatRequest, ConversationMessage


async def main() -> None:
    history: list[ConversationMessage] = []

    steps = [
        "Je veux prendre rendez-vous",
        "Je m'appelle Thibaut Hiriart, mon email est thibaut.hiriart@gmail.com, je veux un rendez-vous le 2026-07-04",
        "09h30",
        "oui",
    ]

    for index, message in enumerate(steps, start=1):
        response = await chat(
            ChatRequest(
                site_id="booking-test",
                message=message,
                history=history,
            )
        )
        print(f"step_{index}_user", message)
        print(f"step_{index}_bot", response.answer)
        history.append(ConversationMessage(role="visitor", content=message))
        history.append(ConversationMessage(role="agent", content=response.answer))


if __name__ == "__main__":
    asyncio.run(main())

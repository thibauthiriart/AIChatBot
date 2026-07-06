from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app.main import _build_search_messages, app
from server.app.schemas import ChatRequest, ConversationMessage, RouteDecision
from server.app.security import _requests


class ChatSchemaTests(unittest.TestCase):
    def test_accepts_history_within_limits(self) -> None:
        payload = ChatRequest(
            site_id="site_123",
            message="Pouvez-vous m'aider ?",
            history=[
                ConversationMessage(role="visitor", content="Bonjour"),
                ConversationMessage(role="agent", content="Bien sur."),
            ],
        )
        self.assertEqual(payload.history[0].content, "Bonjour")

    def test_rejects_message_too_long(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(site_id="site_123", message="a" * 1201, history=[])

    def test_rejects_history_longer_than_twelve_messages(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(
                site_id="site_123",
                message="Bonjour",
                history=[ConversationMessage(role="visitor", content=f"Message {index}") for index in range(13)],
            )

    def test_rejects_history_message_too_long(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(
                site_id="site_123",
                message="Bonjour",
                history=[ConversationMessage(role="visitor", content="a" * 2001)],
            )


class SearchMessageHistoryTests(unittest.TestCase):
    def test_build_search_messages_uses_recent_history(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je cherche une formation courte"),
            ConversationMessage(role="agent", content="Nous avons plusieurs formations"),
            ConversationMessage(role="visitor", content="pour les independants"),
        ]

        candidates = _build_search_messages(
            "et la plus longue ?",
            history,
            "Quelle est la formation la plus longue pour les independants ?",
        )

        self.assertEqual(candidates[0], "Quelle est la formation la plus longue pour les independants ?")
        self.assertIn("Je cherche une formation courte pour les independants et la plus longue ?", candidates)
        self.assertIn(
            "Je cherche une formation courte Nous avons plusieurs formations pour les independants et la plus longue ?",
            candidates,
        )


class ChatEndpointSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        _requests.clear()
        self.patches = [
            patch("server.app.main.db.connect", new=AsyncMock()),
            patch("server.app.main.db.close", new=AsyncMock()),
        ]
        for active_patch in self.patches:
            active_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for active_patch in reversed(self.patches):
            active_patch.stop()
        _requests.clear()

    def test_rejects_disallowed_origin(self) -> None:
        response = self.client.post(
            "/chat",
            headers={"Origin": "https://evil.example"},
            json={"site_id": "site_123", "message": "Bonjour", "history": []},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Origin not allowed")

    def test_rejects_payload_with_too_many_characters(self) -> None:
        response = self.client.post(
            "/chat",
            headers={"Origin": "http://localhost:5173"},
            json={"site_id": "site_123", "message": "a" * 1201, "history": []},
        )
        self.assertEqual(response.status_code, 422)

    def test_rate_limit_blocks_after_configured_threshold(self) -> None:
        mocked_route = AsyncMock(return_value=(RouteDecision(decision="allow", category="greeting", reason="ok"), None))
        mocked_settings = SimpleNamespace(
            chat_rate_limit_per_minute=2,
            cors_origins=["http://localhost:5173"],
        )
        with patch("server.app.main.route_user_message", mocked_route), patch(
            "server.app.security.get_settings",
            return_value=mocked_settings,
        ):
            for _ in range(2):
                response = self.client.post(
                    "/chat",
                    headers={"Origin": "http://localhost:5173"},
                    json={"site_id": "site_123", "message": "Bonjour", "history": []},
                )
                self.assertEqual(response.status_code, 200)

            blocked = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={"site_id": "site_123", "message": "Bonjour", "history": []},
            )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"], "Too many requests")


if __name__ == "__main__":
    unittest.main()

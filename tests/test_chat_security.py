from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app.main import _build_search_messages, _get_client_ip, app
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
            patch("server.app.main._ensure_chat_logging_schema", new=AsyncMock()),
            patch("server.app.main._log_chat_interaction", new=AsyncMock()),
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

    def test_widget_config_reflects_widget_flag(self) -> None:
        mocked_settings = SimpleNamespace(
            widget_enabled=False,
            cors_origins=["http://localhost:5173"],
        )
        with patch("server.app.main.settings", mocked_settings), patch(
            "server.app.security.get_settings",
            return_value=mocked_settings,
        ):
            response = self.client.get(
                "/widget-config",
                headers={"Origin": "http://localhost:5173"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"widget_enabled": False})

    def test_chat_returns_unavailable_when_service_flag_is_disabled(self) -> None:
        mocked_settings = SimpleNamespace(
            chat_service_enabled=False,
            cors_origins=["http://localhost:5173"],
            chat_rate_limit_per_minute=20,
        )
        with patch("server.app.main.settings", mocked_settings), patch(
            "server.app.security.get_settings",
            return_value=mocked_settings,
        ):
            response = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={"site_id": "site_123", "message": "Bonjour", "history": []},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "service indisponible")

    def test_chat_logs_message_response_and_forwarded_ip(self) -> None:
        mocked_route = AsyncMock(return_value=(RouteDecision(decision="allow", category="greeting", reason="ok"), None))
        mocked_logger = AsyncMock()
        with patch("server.app.main.route_user_message", mocked_route), patch(
            "server.app.main._log_chat_interaction",
            mocked_logger,
        ):
            response = self.client.post(
                "/chat",
                headers={
                    "Origin": "http://localhost:5173",
                    "X-Forwarded-For": "203.0.113.10, 10.0.0.1",
                },
                json={"site_id": "11111111-1111-1111-1111-111111111111", "message": "Bonjour", "history": []},
            )

        self.assertEqual(response.status_code, 200)
        mocked_logger.assert_awaited_once_with(
            site_id="11111111-1111-1111-1111-111111111111",
            client_ip="203.0.113.10",
            user_message="Bonjour",
            assistant_answer=response.json()["answer"],
        )


class ClientIpExtractionTests(unittest.TestCase):
    def test_get_client_ip_prefers_forwarded_for(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-for": "198.51.100.8, 10.0.0.2"},
            client=SimpleNamespace(host="127.0.0.1"),
        )

        self.assertEqual(_get_client_ip(request), "198.51.100.8")

    def test_get_client_ip_falls_back_to_socket_client(self) -> None:
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

        self.assertEqual(_get_client_ip(request), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app.client_memory import resolve_client_for_chat
from server.app.main import _build_search_messages, _get_client_ip, app
from server.app.schemas import ChatRequest, ConversationMessage, RouteDecision
from server.app.security import _requests

VALID_SCOPE_ID = "11111111-1111-1111-1111-111111111111"


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


class ClientResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_client_for_chat_uses_rewritten_message_for_partial_name(self) -> None:
        mocked_rows = [
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "site_id": VALID_SCOPE_ID,
                "name": "Acme Industrie",
                "short_name": "Acme",
                "aliases": ["Acme SAS"],
                "sector": "Industrie",
                "status": "actif",
                "summary": "Client historique.",
                "external_ref": "CRM-42",
            }
        ]
        mocked_connection = AsyncMock()
        mocked_connection.fetch.return_value = mocked_rows

        class _AcquireContext:
            async def __aenter__(self_inner):
                return mocked_connection

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("server.app.client_memory.db.acquire", return_value=_AcquireContext()):
            resolved = await resolve_client_for_chat(
                VALID_SCOPE_ID,
                "Et pour ce client ?",
                [ConversationMessage(role="visitor", content="On parlait du compte Acme")],
                rewritten_message="Que sais-tu sur le client Acme Industrie ?",
            )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["name"], "Acme Industrie")

    async def test_resolve_client_for_chat_matches_multi_word_name_without_exact_substring(self) -> None:
        mocked_rows = [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "site_id": VALID_SCOPE_ID,
                "name": "Banque Populaire",
                "short_name": "",
                "aliases": [],
                "sector": "Banque",
                "status": "actif",
                "summary": "",
                "external_ref": "",
            }
        ]
        mocked_connection = AsyncMock()
        mocked_connection.fetch.return_value = mocked_rows

        class _AcquireContext:
            async def __aenter__(self_inner):
                return mocked_connection

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        with patch("server.app.client_memory.db.acquire", return_value=_AcquireContext()):
            resolved = await resolve_client_for_chat(
                VALID_SCOPE_ID,
                "Que sait-on sur la banque du client populaire ?",
                [],
            )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["name"], "Banque Populaire")


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
            json={"site_id": VALID_SCOPE_ID, "message": "Bonjour", "history": []},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Origin not allowed")

    def test_rejects_payload_with_too_many_characters(self) -> None:
        response = self.client.post(
            "/chat",
            headers={"Origin": "http://localhost:5173"},
            json={"site_id": VALID_SCOPE_ID, "message": "a" * 1201, "history": []},
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
                    json={"site_id": VALID_SCOPE_ID, "message": "Bonjour", "history": []},
                )
                self.assertEqual(response.status_code, 200)

            blocked = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={"site_id": VALID_SCOPE_ID, "message": "Bonjour", "history": []},
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
                json={"site_id": VALID_SCOPE_ID, "message": "Bonjour", "history": []},
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
                json={"site_id": VALID_SCOPE_ID, "message": "Bonjour", "history": []},
            )

        self.assertEqual(response.status_code, 200)
        mocked_logger.assert_awaited_once_with(
            site_id=VALID_SCOPE_ID,
            client_ip="203.0.113.10",
            user_message="Bonjour",
            assistant_answer=response.json()["answer"],
        )

    def test_chat_uses_client_memory_when_client_is_resolved(self) -> None:
        mocked_route = AsyncMock(return_value=(RouteDecision(decision="allow", category="knowledge", reason="ok"), None))
        mocked_rewrite = AsyncMock(return_value=(SimpleNamespace(rewritten_message="Que s'est-il passe chez Acme ?", used_history=False), None))
        mocked_client = {
            "id": "22222222-2222-2222-2222-222222222222",
            "site_id": "11111111-1111-1111-1111-111111111111",
            "name": "Acme Industrie",
            "short_name": "Acme",
            "aliases": ["Acme SAS"],
            "sector": "Industrie",
            "status": "actif",
            "summary": "Client historique.",
            "external_ref": "CRM-42",
        }
        mocked_client_context = {
            "client": mocked_client,
            "projects": [],
            "artifacts": [],
            "recent_events": [],
            "blocks": [
                {
                    "content": "Historique recent du client Acme Industrie: 2026-07-08: meeting - COPIL hebdomadaire",
                    "url": "client://22222222-2222-2222-2222-222222222222/timeline",
                    "title": "Timeline Acme Industrie",
                    "score": 1.2,
                }
            ],
        }
        mocked_generate = AsyncMock(return_value=("Voici le dernier contexte Acme.", None))
        with patch("server.app.main.route_user_message", mocked_route), patch(
            "server.app.main.rewrite_user_message",
            mocked_rewrite,
        ), patch(
            "server.app.main.resolve_client_for_chat",
            AsyncMock(return_value=mocked_client),
        ), patch(
            "server.app.main.retrieve_client_context",
            AsyncMock(return_value=mocked_client_context),
        ), patch(
            "server.app.main.retrieve_context",
            AsyncMock(return_value=[]),
        ), patch(
            "server.app.main.generate_answer",
            mocked_generate,
        ):
            response = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={
                    "site_id": VALID_SCOPE_ID,
                    "message": "Que s'est-il passe chez Acme ?",
                    "history": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer"], "Voici le dernier contexte Acme.")
        self.assertEqual(payload["client"]["name"], "Acme Industrie")
        self.assertEqual(payload["sources"][0]["url"], "client://22222222-2222-2222-2222-222222222222/timeline")

    def test_chat_uses_recent_global_client_context_when_no_client_is_resolved(self) -> None:
        mocked_route = AsyncMock(return_value=(RouteDecision(decision="allow", category="knowledge", reason="ok"), None))
        mocked_rewrite = AsyncMock(
            return_value=(SimpleNamespace(rewritten_message="Je viens de faire une reunion, check si le compte rendu est fait.", used_history=False), None)
        )
        mocked_global_context = [
            {
                "content": "Document recent pour Acme Industrie - noota_report - COPIL hebdomadaire: Compte rendu disponible.",
                "url": "client://22222222-2222-2222-2222-222222222222/artifacts/33333333-3333-3333-3333-333333333333",
                "title": "COPIL hebdomadaire",
                "score": 1.3,
            }
        ]
        mocked_generate = AsyncMock(return_value=("Oui, le compte rendu recent est disponible.", None))
        with patch("server.app.main.route_user_message", mocked_route), patch(
            "server.app.main.rewrite_user_message",
            mocked_rewrite,
        ), patch(
            "server.app.main.resolve_client_for_chat",
            AsyncMock(return_value=None),
        ), patch(
            "server.app.main.retrieve_recent_global_context",
            AsyncMock(return_value=mocked_global_context),
        ), patch(
            "server.app.main.retrieve_context",
            AsyncMock(return_value=[]),
        ), patch(
            "server.app.main.generate_answer",
            mocked_generate,
        ):
            response = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={
                    "site_id": VALID_SCOPE_ID,
                    "message": "je viens de faire une reunion, check si le compte rendu est fait.",
                    "history": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer"], "Oui, le compte rendu recent est disponible.")
        self.assertEqual(payload["sources"][0]["title"], "COPIL hebdomadaire")

    def test_chat_checks_drive_reports_when_user_asks_for_report_status(self) -> None:
        mocked_route = AsyncMock(return_value=(RouteDecision(decision="allow", category="knowledge", reason="ok"), None))
        mocked_pending = [
            SimpleNamespace(
                external_id="drive-1",
                meeting_title="COPIL hebdomadaire",
                client_name="Acme Industrie",
            )
        ]
        with patch("server.app.main.route_user_message", mocked_route), patch(
            "server.app.main.noota_drive_sync_service.list_pending",
            AsyncMock(return_value=mocked_pending),
        ), patch(
            "server.app.main._fetch_recent_imported_reports",
            AsyncMock(return_value=[]),
        ):
            response = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={
                    "site_id": VALID_SCOPE_ID,
                    "message": "Check si le compte rendu est fait sur le drive",
                    "history": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("j'ai verifie le Drive".lower(), payload["answer"].lower())
        self.assertIn("COPIL hebdomadaire", payload["answer"])
        self.assertEqual(payload["sources"][0]["url"], "drive://pending/drive-1")

    def test_chat_keeps_generic_report_question_on_database_context(self) -> None:
        mocked_route = AsyncMock(return_value=(RouteDecision(decision="allow", category="knowledge", reason="ok"), None))
        mocked_rewrite = AsyncMock(
            return_value=(SimpleNamespace(rewritten_message="Que peux-tu me dire sur le compte rendu COPIL hebdomadaire pour Acme ?", used_history=False), None)
        )
        mocked_client = {
            "id": "22222222-2222-2222-2222-222222222222",
            "site_id": VALID_SCOPE_ID,
            "name": "Acme Industrie",
            "short_name": "Acme",
            "aliases": ["Acme SAS"],
            "sector": "Industrie",
            "status": "actif",
            "summary": "Client historique.",
            "external_ref": "CRM-42",
        }
        mocked_client_context = {
            "client": mocked_client,
            "projects": [],
            "artifacts": [],
            "recent_events": [],
            "blocks": [
                {
                    "content": "Document client noota_report - COPIL hebdomadaire: Decision prise et prochaines actions.",
                    "url": "client://22222222-2222-2222-2222-222222222222/artifacts/33333333-3333-3333-3333-333333333333",
                    "title": "COPIL hebdomadaire",
                    "score": 1.4,
                }
            ],
        }
        mocked_generate = AsyncMock(return_value=("Le compte rendu COPIL hebdomadaire mentionne une decision et des prochaines actions.", None))
        mocked_pending = AsyncMock(return_value=[])
        with patch("server.app.main.route_user_message", mocked_route), patch(
            "server.app.main.rewrite_user_message",
            mocked_rewrite,
        ), patch(
            "server.app.main.resolve_client_for_chat",
            AsyncMock(return_value=mocked_client),
        ), patch(
            "server.app.main.retrieve_client_context",
            AsyncMock(return_value=mocked_client_context),
        ), patch(
            "server.app.main.retrieve_context",
            AsyncMock(return_value=[]),
        ), patch(
            "server.app.main.generate_answer",
            mocked_generate,
        ), patch(
            "server.app.main.noota_drive_sync_service.list_pending",
            mocked_pending,
        ):
            response = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={
                    "site_id": VALID_SCOPE_ID,
                    "message": "Que peux-tu me dire sur le compte rendu COPIL hebdomadaire pour Acme ?",
                    "history": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["answer"],
            "Le compte rendu COPIL hebdomadaire mentionne une decision et des prochaines actions.",
        )
        self.assertEqual(
            payload["sources"][0]["url"],
            "client://22222222-2222-2222-2222-222222222222/artifacts/33333333-3333-3333-3333-333333333333",
        )
        mocked_pending.assert_not_awaited()

    def test_chat_reformats_pending_drive_report_when_user_requests_it(self) -> None:
        mocked_pending = [
            SimpleNamespace(
                external_id="drive-1",
                file_name="Google Meet - meet.google.com_fkk-pkds-uyz.docx",
                meeting_title="COPIL hebdomadaire",
                client_name="Acme Industrie",
                project_name="Projet Support",
                formatted_report="Compte rendu Noota - COPIL hebdomadaire",
            )
        ]
        with patch(
            "server.app.main.noota_drive_sync_service.list_pending",
            AsyncMock(return_value=mocked_pending),
        ):
            response = self.client.post(
                "/chat",
                headers={"Origin": "http://localhost:5173"},
                json={
                    "site_id": VALID_SCOPE_ID,
                    "message": "remet en forme Google Meet - meet.google.com_fkk-pkds-uyz",
                    "history": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("je l'ai remis en forme", payload["answer"].lower())
        self.assertIn("Compte rendu Noota - COPIL hebdomadaire", payload["answer"])
        self.assertEqual(payload["sources"][0]["url"], "drive://pending/drive-1")

    def test_chat_does_not_summarize_drive_report_for_reschedule_question(self) -> None:
        response = self.client.post(
            "/chat",
            headers={"Origin": "http://localhost:5173"},
            json={
                "site_id": VALID_SCOPE_ID,
                "message": "tu serais en capacite de deplacer le creneau de rdv ?",
                "history": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("deplacer automatiquement un rendez-vous existant", payload["answer"])
        self.assertEqual(payload["sources"], [])


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

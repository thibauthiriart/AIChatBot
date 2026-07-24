from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.app.booking import BookingProviderError
from server.app.main import app
from server.app.noota import _create_tasks_from_report, format_noota_report, import_noota_report_with_override
from server.app.schemas import (
    BookingConfirmation,
    CalendarEventSuggestion,
    ClientArtifactSummary,
    ClientEventSummary,
    ClientSummary,
    NootaDriveImportedItem,
    NootaImportResponse,
    NootaActionItem,
    NootaReportImport,
)


class NootaFormattingTests(unittest.TestCase):
    def test_format_noota_report_contains_sections(self) -> None:
        payload = NootaReportImport(
            client_name="Acme Industrie",
            project_name="Assistant SAV",
            meeting_title="COPIL hebdomadaire",
            meeting_at="2026-07-10T09:00:00+02:00",
            summary="Validation du lot support.",
            key_points=["Point 1", "Point 2"],
            decisions=["Decision 1"],
            transcript="Transcript complet",
        )

        content = format_noota_report(payload, "Acme Industrie", "Assistant SAV")

        self.assertIn("Compte rendu Noota - COPIL hebdomadaire", content)
        self.assertIn("Client: Acme Industrie", content)
        self.assertIn("Projet: Assistant SAV", content)
        self.assertIn("Synthese", content)
        self.assertIn("Decisions", content)
        self.assertIn("Transcript", content)


class NootaTaskExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_with_selected_tasks_marks_artifact_as_processed(self) -> None:
        report = NootaReportImport(
            client_name="Acme Industrie",
            project_name="Assistant SAV",
            meeting_title="COPIL hebdomadaire",
        )
        client = {
            "id": "11111111-1111-1111-1111-111111111111",
            "site_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "name": "Acme Industrie",
        }
        project = {
            "id": "33333333-3333-3333-3333-333333333333",
            "client_id": client["id"],
            "name": "Assistant SAV",
            "status": "en cours",
            "summary": "",
            "started_on": None,
            "due_on": None,
        }
        artifact = {
            "id": "22222222-2222-2222-2222-222222222222",
            "client_id": client["id"],
            "project_id": project["id"],
            "title": "COPIL hebdomadaire",
            "kind": "noota_report",
        }
        event = {
            "id": "44444444-4444-4444-4444-444444444444",
            "client_id": client["id"],
            "project_id": project["id"],
            "title": "COPIL hebdomadaire",
            "event_type": "meeting_report",
            "details": "",
            "event_at": "2026-07-24T10:00:00+02:00",
        }

        with patch("server.app.noota._resolve_or_create_client", AsyncMock(return_value=client)), patch(
            "server.app.noota._resolve_or_create_project",
            AsyncMock(return_value=project),
        ), patch("server.app.noota._create_artifact", AsyncMock(return_value=artifact)), patch(
            "server.app.noota._create_tasks_from_report",
            AsyncMock(return_value=1),
        ), patch("server.app.noota.mark_client_artifact_tasks_processed", AsyncMock()) as mocked_mark, patch(
            "server.app.noota._create_event",
            AsyncMock(return_value=event),
        ):
            await import_noota_report_with_override(
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                report,
                selected_task_keys={"preparer le planning||"},
            )

        mocked_mark.assert_awaited_once_with(artifact["id"], 1)

    async def test_validation_creates_tasks_from_final_report_text(self) -> None:
        report = NootaReportImport(
            client_name="Acme Industrie",
            meeting_title="COPIL hebdomadaire",
            action_items=[
                NootaActionItem(
                    description="Envoyer le recap support",
                    owner="Julie",
                    due_date="2026-07-24",
                )
            ],
        )
        formatted_report = "\n".join(
            [
                "Compte rendu Noota - COPIL hebdomadaire",
                "",
                "Actions",
                "- Envoyer le recap support | Responsable: Julie | Echeance: 2026-07-24",
                "- Preparer le planning de deploiement | Responsable: Marc | Echeance: 2026-07-31",
            ]
        )

        with patch("server.app.noota.create_client_project_task", AsyncMock()) as mocked_create_task:
            await _create_tasks_from_report(
                "11111111-1111-1111-1111-111111111111",
                None,
                "22222222-2222-2222-2222-222222222222",
                report,
                formatted_report,
            )

        created_titles = [call.args[3] for call in mocked_create_task.await_args_list]
        self.assertIn("Envoyer le recap support", created_titles)
        self.assertIn("Preparer le planning de deploiement", created_titles)

    async def test_task_extraction_filters_table_headers_dates_and_names(self) -> None:
        report = NootaReportImport(
            client_name="Acme Industrie",
            meeting_title="COPIL hebdomadaire",
            action_items=[
                NootaActionItem(description="Action"),
                NootaActionItem(description="Responsable"),
                NootaActionItem(description="Echeance"),
                NootaActionItem(description="21 juillet"),
                NootaActionItem(description="Clara"),
                NootaActionItem(description="Preparer la presentation client"),
            ],
        )
        formatted_report = "\n".join(
            [
                "Compte rendu Noota - COPIL hebdomadaire",
                "",
                "Actions",
                "- Action",
                "- Responsable",
                "- Echeance",
                "- 21 juillet",
                "- Clara",
                "- Plusieurs sujets ont ete discutes :",
                "- Preparer la presentation client",
                "- Corriger les anomalies critiques",
            ]
        )

        with patch("server.app.noota.create_client_project_task", AsyncMock()) as mocked_create_task:
            await _create_tasks_from_report(
                "11111111-1111-1111-1111-111111111111",
                None,
                "22222222-2222-2222-2222-222222222222",
                report,
                formatted_report,
            )

        created_titles = [call.args[3] for call in mocked_create_task.await_args_list]
        self.assertEqual(
            created_titles,
            [
                "Preparer la presentation client",
                "Corriger les anomalies critiques",
            ],
        )

    async def test_task_extraction_keeps_client_wishes_as_tasks(self) -> None:
        report = NootaReportImport(
            client_name="Acme Industrie",
            meeting_title="Atelier besoins",
            action_items=[
                NootaActionItem(description="Si possible ajouter un mode sombre"),
                NootaActionItem(description="J'aimerais exporter les donnees en Excel"),
            ],
        )
        formatted_report = "\n".join(
            [
                "Compte rendu Noota - Atelier besoins",
                "",
                "Synthese",
                "- Le client souhaite synchroniser les notifications avec Teams",
                "Il faudrait permettre la validation par service.",
                "Ce serait bien de garder un historique des modifications.",
                "",
                "Actions",
                "- Si possible ajouter un mode sombre",
                "- J'aimerais exporter les donnees en Excel",
            ]
        )

        with patch("server.app.noota.create_client_project_task", AsyncMock()) as mocked_create_task:
            await _create_tasks_from_report(
                "11111111-1111-1111-1111-111111111111",
                None,
                "22222222-2222-2222-2222-222222222222",
                report,
                formatted_report,
            )

        created_titles = [call.args[3] for call in mocked_create_task.await_args_list]
        self.assertIn("Si possible ajouter un mode sombre", created_titles)
        self.assertIn("J'aimerais exporter les donnees en Excel", created_titles)
        self.assertIn("Le client souhaite synchroniser les notifications avec Teams", created_titles)
        self.assertIn("Il faudrait permettre la validation par service.", created_titles)
        self.assertIn("Ce serait bien de garder un historique des modifications.", created_titles)

    async def test_task_extraction_keeps_compromises_discussions_and_repeated_mentions(self) -> None:
        report = NootaReportImport(
            client_name="Acme Industrie",
            meeting_title="Atelier arbitrages",
        )
        formatted_report = "\n".join(
            [
                "Compte rendu Noota - Atelier arbitrages",
                "",
                "Synthese",
                "- Compromis sur le mode sombre pour le portail client",
                "- Longue discussion autour de l'export Excel avance",
                "- Le sujet de la synchronisation Teams revient dans plusieurs rapports",
                "- Arbitrage a trancher sur les droits d'acces administrateur",
            ]
        )

        with patch("server.app.noota.create_client_project_task", AsyncMock()) as mocked_create_task:
            await _create_tasks_from_report(
                "11111111-1111-1111-1111-111111111111",
                None,
                "22222222-2222-2222-2222-222222222222",
                report,
                formatted_report,
            )

        created_titles = [call.args[3] for call in mocked_create_task.await_args_list]
        self.assertIn("Compromis sur le mode sombre pour le portail client", created_titles)
        self.assertIn("Longue discussion autour de l'export Excel avance", created_titles)
        self.assertIn("Le sujet de la synchronisation Teams revient dans plusieurs rapports", created_titles)
        self.assertIn("Arbitrage a trancher sur les droits d'acces administrateur", created_titles)


class NootaEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patches = [
            patch("server.app.main.db.connect", new=AsyncMock()),
            patch("server.app.main.db.close", new=AsyncMock()),
            patch("server.app.main._ensure_chat_logging_schema", new=AsyncMock()),
            patch("server.app.main.ensure_client_memory_schema", new=AsyncMock()),
            patch("server.app.main._ensure_default_scope", new=AsyncMock()),
        ]
        for active_patch in self.patches:
            active_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for active_patch in reversed(self.patches):
            active_patch.stop()

    def test_ingest_noota_report_endpoint_returns_imported_objects(self) -> None:
        mocked_response = NootaImportResponse(
            client=ClientSummary(
                id="11111111-1111-1111-1111-111111111111",
                site_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                name="Acme Industrie",
            ),
            project=None,
            artifact=ClientArtifactSummary(
                id="22222222-2222-2222-2222-222222222222",
                client_id="11111111-1111-1111-1111-111111111111",
                title="COPIL hebdomadaire",
                kind="noota_report",
            ),
            event=ClientEventSummary(
                id="33333333-3333-3333-3333-333333333333",
                client_id="11111111-1111-1111-1111-111111111111",
                title="COPIL hebdomadaire",
                event_type="meeting_report",
                details="Validation du lot support.",
                event_at="2026-07-10T09:00:00+02:00",
            ),
            formatted_report="Compte rendu Noota - COPIL hebdomadaire",
        )

        with patch("server.app.main.import_noota_report", AsyncMock(return_value=mocked_response)), patch(
            "server.app.main._resolve_scope_id",
            AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ), patch(
            "server.app.security.get_settings",
            return_value=type("Settings", (), {"noota_ingest_token": "secret", "admin_api_token": "", "cors_origins": ["http://localhost:5173"]})(),
        ):
            response = self.client.post(
                "/integrations/noota/report",
                headers={"X-Noota-Token": "secret"},
                json={
                    "client_name": "Acme Industrie",
                    "meeting_title": "COPIL hebdomadaire",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["client"]["name"], "Acme Industrie")
        self.assertEqual(payload["artifact"]["kind"], "noota_report")

    def test_import_and_email_also_schedules_detected_appointments(self) -> None:
        report = NootaReportImport(
            client_name="Acme Industrie",
            project_name="Assistant SAV",
            meeting_title="COPIL hebdomadaire",
            meeting_at="2026-07-10T09:00:00+02:00",
            summary="Validation du lot support.",
        )
        imported_item = NootaDriveImportedItem(
            external_id="drive-1",
            file_name="copil.docx",
            client_name="Acme Industrie",
            project_name="Assistant SAV",
            artifact_id="artifact-1",
        )
        suggestion = CalendarEventSuggestion(
            title="Relance projet",
            start="2026-07-12T10:00:00+02:00",
            end="2026-07-12T10:30:00+02:00",
            timezone="Europe/Paris",
            source_excerpt="Planifier une relance.",
            confidence=0.92,
        )

        with patch(
            "server.app.main._resolve_scope_id",
            AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ), patch(
            "server.app.main.noota_drive_sync_service.get_pending_report",
            AsyncMock(return_value=(type("DriveFile", (), {"id": "drive-1"})(), report, "Compte rendu formate", [suggestion])),
        ), patch(
            "server.app.main.mailer.send_report",
            AsyncMock(),
        ), patch(
            "server.app.main.booking_service.provider.create_event",
            AsyncMock(return_value=BookingConfirmation(event_id="evt_123", html_link="https://calendar.google.com/event?eid=123")),
        ) as mocked_create_event, patch(
            "server.app.main._log_appointment_notification",
            AsyncMock(return_value="notif_123"),
        ), patch(
            "server.app.main.noota_drive_sync_service.import_one",
            AsyncMock(return_value=imported_item),
        ), patch(
            "server.app.security.get_settings",
            return_value=type("Settings", (), {"noota_ingest_token": "", "admin_api_token": "", "cors_origins": ["http://localhost:5173"]})(),
        ):
            response = self.client.post(
                "/integrations/noota/google-drive/import-and-email",
                headers={"Origin": "http://localhost:5173"},
                json={
                    "site_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "external_id": "drive-1",
                    "recipient_email": "contact@acme.fr",
                    "client_name": "Acme Industrie Valide",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["imported_item"]["artifact_id"], "artifact-1")
        self.assertEqual(len(payload["scheduled_appointments"]), 1)
        self.assertEqual(payload["scheduled_appointments"][0]["event_id"], "evt_123")
        mocked_create_event.assert_awaited_once()

    def test_import_and_email_keeps_import_when_schedule_creation_fails(self) -> None:
        report = NootaReportImport(
            client_name="Client a qualifier",
            project_name="Assistant SAV",
            meeting_title="COPIL hebdomadaire",
            meeting_at="2026-07-10T09:00:00+02:00",
            summary="Validation du lot support.",
        )
        imported_item = NootaDriveImportedItem(
            external_id="drive-1",
            file_name="copil.docx",
            client_name="Mme Martin",
            project_name="Assistant SAV",
            artifact_id="artifact-1",
        )
        suggestion = CalendarEventSuggestion(
            title="Relance projet",
            start="2026-07-12T10:00:00+02:00",
            end="2026-07-12T10:30:00+02:00",
            timezone="Europe/Paris",
            source_excerpt="Planifier une relance.",
            confidence=0.92,
        )

        with patch(
            "server.app.main._resolve_scope_id",
            AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ), patch(
            "server.app.main.noota_drive_sync_service.get_pending_report",
            AsyncMock(return_value=(type("DriveFile", (), {"id": "drive-1"})(), report, "Compte rendu formate", [suggestion])),
        ), patch(
            "server.app.main.mailer.send_report",
            AsyncMock(),
        ), patch(
            "server.app.main.noota_drive_sync_service.import_one",
            AsyncMock(return_value=imported_item),
        ) as mocked_import_one, patch(
            "server.app.main.booking_service.provider.create_event",
            AsyncMock(side_effect=BookingProviderError("Le creneau est deja occupe.")),
        ), patch(
            "server.app.security.get_settings",
            return_value=type("Settings", (), {"noota_ingest_token": "", "admin_api_token": "", "cors_origins": ["http://localhost:5173"]})(),
        ):
            response = self.client.post(
                "/integrations/noota/google-drive/import-and-email",
                headers={"Origin": "http://localhost:5173"},
                json={
                    "site_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "external_id": "drive-1",
                    "recipient_email": "contact@acme.fr",
                    "client_name": "Mme Martin",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["imported_item"]["client_name"], "Mme Martin")
        self.assertEqual(payload["scheduled_appointments"], [])
        mocked_import_one.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

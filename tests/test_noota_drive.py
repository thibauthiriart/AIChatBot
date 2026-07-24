from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from server.app.config import Settings
from server.app.noota_drive import DriveFile, GoogleDriveNootaSyncService, NootaDriveSyncError
from server.app.schemas import NootaReportImport


class NootaDriveOrderingTests(unittest.TestCase):
    def test_recent_files_should_be_preferred(self) -> None:
        files = [
            DriveFile(id="1", name="ancien.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-14T08:00:00Z"),
            DriveFile(id="2", name="recent.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-15T09:00:00Z"),
            DriveFile(id="3", name="milieu.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-15T07:00:00Z"),
        ]

        files.sort(key=lambda item: item.modified_time or "", reverse=True)

        self.assertEqual([item.id for item in files], ["2", "3", "1"])


class NootaDrivePendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_scan_continues_after_recent_imported_files(self) -> None:
        settings = Settings(noota_google_drive_root_folder_id="root", noota_google_drive_scan_limit=10)
        service = GoogleDriveNootaSyncService(settings)
        files = [
            DriveFile(id="imported-1", name="importe-1.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-15T11:00:00Z"),
            DriveFile(id="imported-2", name="importe-2.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-15T10:00:00Z"),
            DriveFile(id="pending-1", name="nouveau.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-15T09:00:00Z"),
        ]
        report = NootaReportImport(client_name="Acme Industrie", meeting_title="Nouveau COPIL")

        with patch.object(service, "_list_docx_files", AsyncMock(return_value=files)) as mocked_list_files, patch(
            "server.app.noota_drive._is_already_imported",
            AsyncMock(side_effect=lambda _provider, external_id: external_id.startswith("imported")),
        ), patch.object(
            service,
            "_build_pending_report",
            AsyncMock(
                return_value=(
                    files[2],
                    report,
                    "Compte rendu formate\n\nActions\n- Preparer le planning | Responsable: Marc | Echeance: 2026-07-31",
                    [],
                )
            ),
        ):
            pending = await service.list_pending(None, 1)

        mocked_list_files.assert_awaited_once_with("root", 10)
        self.assertEqual([item.external_id for item in pending], ["pending-1"])
        self.assertEqual(pending[0].suggested_tasks[0].title, "Preparer le planning")

    async def test_pending_scan_skips_unreadable_files(self) -> None:
        settings = Settings(noota_google_drive_root_folder_id="root", noota_google_drive_scan_limit=10)
        service = GoogleDriveNootaSyncService(settings)
        files = [
            DriveFile(id="broken", name="cassé.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-15T10:00:00Z"),
            DriveFile(id="pending-1", name="nouveau.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", modified_time="2026-07-15T09:00:00Z"),
        ]
        report = NootaReportImport(client_name="Acme Industrie", meeting_title="Nouveau COPIL")

        async def build_pending_report(file: DriveFile):
            if file.id == "broken":
                raise NootaDriveSyncError("Document illisible")
            return file, report, "Compte rendu formate", []

        with patch.object(service, "_list_docx_files", AsyncMock(return_value=files)), patch(
            "server.app.noota_drive._is_already_imported",
            AsyncMock(return_value=False),
        ), patch.object(
            service,
            "_build_pending_report",
            AsyncMock(side_effect=build_pending_report),
        ):
            pending = await service.list_pending(None, 1)

        self.assertEqual([item.external_id for item in pending], ["pending-1"])

    async def test_import_one_passes_selected_task_keys(self) -> None:
        settings = Settings(noota_google_drive_root_folder_id="root", noota_google_drive_scan_limit=10)
        service = GoogleDriveNootaSyncService(settings)
        file = DriveFile(id="pending-1", name="nouveau.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        report = NootaReportImport(client_name="Acme Industrie", meeting_title="Nouveau COPIL")
        selected_keys = {"preparer le planning|marc|2026-07-31"}
        imported = SimpleNamespace(
            artifact=SimpleNamespace(id="artifact-1"),
            client=SimpleNamespace(name="Acme Industrie"),
        )

        with patch.object(service, "_list_docx_files", AsyncMock(return_value=[file])), patch(
            "server.app.noota_drive._is_already_imported",
            AsyncMock(return_value=False),
        ), patch.object(
            service,
            "_build_pending_report",
            AsyncMock(return_value=(file, report, "Compte rendu formate", [])),
        ), patch(
            "server.app.noota_drive.import_noota_report_with_override",
            AsyncMock(return_value=imported),
        ) as mocked_import, patch(
            "server.app.noota_drive._mark_imported",
            AsyncMock(),
        ):
            await service.import_one("site-1", file.id, selected_task_keys=selected_keys)

        mocked_import.assert_awaited_once_with(
            "site-1",
            report,
            None,
            None,
            selected_keys,
        )


if __name__ == "__main__":
    unittest.main()

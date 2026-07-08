from __future__ import annotations

import unittest
from datetime import date

from server.app.booking import BookingService
from server.app.config import Settings
from server.app.schemas import BookingConfirmation, BookingRequest, BookingSlot, ConversationMessage


class FakeBookingProvider:
    def __init__(self) -> None:
        self.created_request: BookingRequest | None = None

    async def list_available_slots(self, requested_day: date, timezone_name: str) -> list[BookingSlot]:
        self.last_requested_day = requested_day
        self.last_timezone_name = timezone_name
        return [
            BookingSlot(
                start="2026-07-04T09:00:00+02:00",
                end="2026-07-04T09:30:00+02:00",
                timezone=timezone_name,
                label="09:00",
            ),
            BookingSlot(
                start="2026-07-04T09:30:00+02:00",
                end="2026-07-04T10:00:00+02:00",
                timezone=timezone_name,
                label="09:30",
            ),
            BookingSlot(
                start="2026-07-04T14:00:00+02:00",
                end="2026-07-04T14:30:00+02:00",
                timezone=timezone_name,
                label="14:00",
            ),
            BookingSlot(
                start="2026-07-04T15:00:00+02:00",
                end="2026-07-04T15:30:00+02:00",
                timezone=timezone_name,
                label="15:00",
            ),
        ]

    async def create_appointment(self, request: BookingRequest) -> BookingConfirmation:
        self.created_request = request
        return BookingConfirmation(event_id="evt_123", html_link="https://calendar.google.com/event?eid=123")


class BookingServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.provider = FakeBookingProvider()
        self.settings = Settings(
            booking_provider="google_calendar",
            booking_timezone_default="Europe/Paris",
            booking_slot_duration_minutes=30,
            booking_max_suggestions=3,
            google_calendar_id="calendar@example.com",
            google_service_account_file="/tmp/service-account.json",
        )
        self.service = BookingService(settings=self.settings, provider=self.provider)

    async def test_asks_for_missing_identity(self) -> None:
        result = await self.service.handle_message("Je veux prendre rendez-vous demain", [])
        self.assertEqual(result.status, "needs_info")
        self.assertIn("nom", result.message)
        self.assertIn("email", result.message)

    async def test_lists_slots_when_date_known(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je m'appelle Alice Martin"),
            ConversationMessage(role="visitor", content="Mon email est alice@example.com"),
        ]
        result = await self.service.handle_message("Je veux un rendez-vous le 04/07/2026", history)
        self.assertEqual(result.status, "slot_selection")
        self.assertIn("14:00", result.message)
        self.assertEqual(len(result.slots), 3)

    async def test_accepts_short_french_year_format(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je m'appelle Alice Martin"),
            ConversationMessage(role="visitor", content="Mon email est alice@example.com"),
        ]
        result = await self.service.handle_message("Je veux un rendez-vous le 20/07/26", history)
        self.assertEqual(result.status, "slot_selection")
        self.assertIn("20/07/2026", result.message)

    async def test_requests_confirmation_for_selected_slot(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je m'appelle Alice Martin"),
            ConversationMessage(role="visitor", content="Mon email est alice@example.com"),
            ConversationMessage(role="visitor", content="Je veux un rendez-vous le 04/07/2026"),
        ]
        result = await self.service.handle_message("15h", history)
        self.assertEqual(result.status, "confirmation")
        self.assertIn("Confirmez-vous la reservation", result.message)

    async def test_accepts_direct_name_reply_after_prompt(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Mon email est alice@example.com"),
            ConversationMessage(role="visitor", content="Je veux un rendez-vous le 04/07/2026"),
            ConversationMessage(role="visitor", content="15h"),
            ConversationMessage(role="agent", content="Pour reserver, j'ai besoin de votre nom."),
        ]
        result = await self.service.handle_message("Alice", history)
        self.assertEqual(result.status, "confirmation")
        self.assertIn("au nom de Alice, email alice@example.com", result.message)

    async def test_accepts_structured_email_and_name_reply(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je veux un rendez-vous le 04/07/2026"),
            ConversationMessage(role="visitor", content="15h"),
            ConversationMessage(role="agent", content="Pour reserver, j'ai besoin de votre nom, votre email."),
        ]
        result = await self.service.handle_message("thibaut@gmail.com et nom : Hiriart", history)
        self.assertEqual(result.status, "confirmation")
        self.assertIn("au nom de Hiriart, email thibaut@gmail.com", result.message)

    async def test_prefers_afternoon_slots_when_user_asks_later(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je m'appelle Alice Martin"),
            ConversationMessage(role="visitor", content="Mon email est alice@example.com"),
            ConversationMessage(role="visitor", content="Je veux un rendez-vous le 04/07/2026"),
            ConversationMessage(
                role="agent",
                content="Je peux vous proposer ces creneaux le 04/07/2026 (Europe/Paris) : 09:00, 09:30, 14:00. Quel creneau choisissez-vous ?",
            ),
        ]
        result = await self.service.handle_message("Plus tard dans l'apres midi", history)
        self.assertEqual(result.status, "slot_selection")
        self.assertIn("14:00", result.message)
        self.assertIn("15:00", result.message)
        self.assertNotIn("09:00", result.message)

    async def test_creates_event_after_confirmation(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je m'appelle Alice Martin"),
            ConversationMessage(role="visitor", content="Mon email est alice@example.com"),
            ConversationMessage(
                role="agent",
                content=(
                    "Je recapitule : rendez-vous le 2026-07-04 a 15:00 "
                    "(Europe/Paris), au nom de Alice Martin, email alice@example.com. "
                    "Confirmez-vous la reservation ?"
                ),
            ),
        ]
        result = await self.service.handle_message("oui", history)
        self.assertEqual(result.status, "confirmed")
        self.assertIn("04/07/2026", result.message)
        self.assertIsNotNone(self.provider.created_request)
        self.assertEqual(self.provider.created_request.email, "alice@example.com")

    async def test_creates_event_after_natural_confirmation_phrase(self) -> None:
        history = [
            ConversationMessage(role="visitor", content="Je m'appelle Alice Martin"),
            ConversationMessage(role="visitor", content="Mon email est alice@example.com"),
            ConversationMessage(
                role="agent",
                content=(
                    "Je recapitule : rendez-vous le 2026-07-04 a 15:00 "
                    "(Europe/Paris), au nom de Alice Martin, email alice@example.com. "
                    "Confirmez-vous la reservation ?"
                ),
            ),
        ]
        result = await self.service.handle_message("oui je confirme", history)
        self.assertEqual(result.status, "confirmed")
        self.assertIn("04/07/2026", result.message)


if __name__ == "__main__":
    unittest.main()

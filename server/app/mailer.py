from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from server.app.config import Settings, get_settings


class MailerError(RuntimeError):
    pass


class SmtpMailer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_report(self, recipient_email: str, subject: str, body: str) -> None:
        self._validate_configuration()
        await asyncio.to_thread(self._send_blocking, recipient_email, subject, body)

    def _validate_configuration(self) -> None:
        if not self.settings.smtp_host:
            raise MailerError("SMTP_HOST est manquant.")
        if not self.settings.smtp_from_email:
            raise MailerError("SMTP_FROM_EMAIL est manquant.")

    def _send_blocking(self, recipient_email: str, subject: str, body: str) -> None:
        message = EmailMessage()
        from_label = self.settings.smtp_from_name.strip()
        if from_label:
            message["From"] = f"{from_label} <{self.settings.smtp_from_email}>"
        else:
            message["From"] = self.settings.smtp_from_email
        message["To"] = recipient_email
        message["Subject"] = subject
        message.set_content(body)

        try:
            if self.settings.smtp_use_ssl:
                server = smtplib.SMTP_SSL(self.settings.smtp_host, self.settings.smtp_port, timeout=20)
            else:
                server = smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20)

            with server:
                if self.settings.smtp_use_starttls and not self.settings.smtp_use_ssl:
                    server.starttls()
                if self.settings.smtp_username:
                    server.login(self.settings.smtp_username, self.settings.smtp_password)
                server.send_message(message)
        except Exception as exc:  # pragma: no cover - network dependent
            raise MailerError(f"Impossible d'envoyer l'email ({exc}).") from exc

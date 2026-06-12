"""SMTP email alerting.

Phase 0 uses this for auth/token failure. Later phases route every operator
event (trade entered/exited, kill-switch, safe-exit, feed disconnect, recon
mismatch, EOD summary) through here. If SMTP is unconfigured it logs a warning
rather than crashing — alerts must never take the engine down.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import parseaddr

from common.logging import get_logger
from config.settings import Settings, get_settings

log = get_logger("alerts")


class Alerter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()

    async def send_async(self, subject: str, body: str, html: str | None = None) -> bool:
        """Non-blocking send for async callers (SMTP is synchronous and can stall
        the event loop for seconds — run it in a worker thread)."""
        return await asyncio.to_thread(self.send, subject, body, html)

    def _from_header(self):
        """From header, with an optional display name (e.g. 'OutFyld <admin@...>')."""
        addr = self.s.smtp_from or self.s.smtp_user
        name = getattr(self.s, "smtp_from_name", "") or ""
        if name and addr:
            user, _, domain = parseaddr(addr)[1].partition("@")
            if user and domain:
                return Address(name, user, domain)
        return addr

    def send(self, subject: str, body: str, html: str | None = None) -> bool:
        """Send a plain-text alert, optionally with an HTML alternative (rich reports)."""
        if not self.s.smtp_host or not self.s.alert_email_to:
            log.warning("alert_not_sent_smtp_unconfigured", subject=subject)
            return False
        msg = EmailMessage()
        msg["Subject"] = f"[ATS] {subject}"
        msg["From"] = self._from_header()
        msg["To"] = self.s.alert_email_to
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as server:
                if self.s.smtp_use_tls:
                    server.starttls()
                if self.s.smtp_user:
                    server.login(self.s.smtp_user, self.s.smtp_password)
                server.send_message(msg)
            log.info("alert_sent", subject=subject)
            return True
        except Exception as exc:  # alerts must not crash the caller
            log.error("alert_send_failed", subject=subject, error=str(exc))
            return False

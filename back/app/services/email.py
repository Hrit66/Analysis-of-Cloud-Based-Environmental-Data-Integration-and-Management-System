"""Email delivery abstraction.

In development (or when SMTP is not configured) messages are logged and can be
read from the ``email_outbox`` collection.  Configure SMTP_HOST etc. for real
delivery in production.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.config import get_settings
from app.database import db

logger = logging.getLogger(__name__)


def _send_smtp(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        smtp.send_message(message)


async def send_email(to: str, subject: str, body: str) -> bool:
    settings = get_settings()
    delivered = False
    if settings.SMTP_HOST:
        try:
            await asyncio.to_thread(_send_smtp, to, subject, body)
            delivered = True
        except Exception as exc:  # pragma: no cover - depends on deployment
            logger.error("SMTP delivery failed for %s: %s", to, exc)
    else:
        logger.info("Email (SMTP not configured) to=%s subject=%s\n%s", to, subject, body)
    try:
        if db.db is not None:
            await db.db.email_outbox.insert_one({
                "to": to,
                "subject": subject,
                "body": body,
                "delivered": delivered,
            })
    except Exception:
        pass
    return delivered


def verification_link(token: str) -> str:
    return f"{get_settings().FRONTEND_URL.rstrip('/')}/verify-email?token={token}"


def invite_link(token: str) -> str:
    return f"{get_settings().FRONTEND_URL.rstrip('/')}/accept-invite?token={token}"


def org_contact_link(token: str) -> str:
    return f"{get_settings().FRONTEND_URL.rstrip('/')}/organization/verify?token={token}"


def org_setup_link(token: str) -> str:
    return f"{get_settings().FRONTEND_URL.rstrip('/')}/organization/setup?token={token}"


def password_reset_link(token: str) -> str:
    return f"{get_settings().FRONTEND_URL.rstrip('/')}/reset-password?token={token}"


async def send_verification_email(to: str, token: str) -> bool:
    return await send_email(
        to,
        "Verify your EnvPlatform email",
        "Open this single-use link within 30 minutes to verify your email:\n\n"
        f"{verification_link(token)}\n",
    )


async def send_invite_email(to: str, org_name: str, token: str, role: str) -> bool:
    return await send_email(
        to,
        f"Invitation to join {org_name} on EnvPlatform",
        f"You have been invited to join {org_name} as {role}.\n\n"
        f"Open this single-use link within 7 days:\n{invite_link(token)}\n",
    )


async def send_org_contact_email(to: str, org_name: str, token: str) -> bool:
    return await send_email(
        to,
        f"Verify the contact email for {org_name}",
        "Confirm that you control this mailbox to continue the organization "
        f"application:\n\n{org_contact_link(token)}\n",
    )


async def send_org_setup_email(to: str, org_name: str, token: str) -> bool:
    return await send_email(
        to,
        f"Set up your {org_name} administrator account",
        "Your organization was approved. Set your password with this single-use "
        f"link:\n\n{org_setup_link(token)}\n",
    )


async def send_decision_email(to: str, org_name: str, approved: bool, reason: Optional[str] = None) -> bool:
    if approved:
        return await send_email(to, f"{org_name} was approved", "Your organization application was approved.")
    return await send_email(
        to,
        f"{org_name} application update",
        f"Your organization application was not approved. {reason or ''}".strip(),
    )

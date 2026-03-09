"""IMAP client for connecting to Proton Bridge."""

import logging
from dataclasses import dataclass
from datetime import datetime

from imap_tools import AND, OR, FolderInfo, MailBox, MailMessage, MailBoxUnencrypted

from protoncalbridge.exceptions import IMAPAuthenticationError, IMAPConnectionError

logger = logging.getLogger(__name__)


@dataclass
class IMAPConfig:
    host: str
    port: int = 1143
    username: str = ""
    password: str = ""
    use_ssl: bool = True


@dataclass
class EmailMessage:
    message_id: str
    subject: str
    sender: str
    recipient: str | None = None
    date: datetime | None = None
    body_text: str | None = None
    body_html: str | None = None
    has_attachments: bool = False


class IMAPClient:
    def __init__(self, config: IMAPConfig):
        self.config = config
        self._mailbox: MailBox | None = None

    def connect(self) -> None:
        try:
            if self.config.use_ssl:
                self._mailbox = MailBox(self.config.host, self.config.port)
            else:
                self._mailbox = MailBoxUnencrypted(self.config.host, self.config.port)
            self._mailbox.login(self.config.username, self.config.password)
            logger.info(f"Connected to IMAP at {self.config.host}:{self.config.port}")
        except Exception as e:
            error_str = str(e).lower()
            if "login" in error_str or "authentication" in error_str:
                logger.error(f"IMAP login failed: {e}")
                raise IMAPAuthenticationError(f"Failed to authenticate: {e}") from e
            logger.error(f"IMAP connection failed: {e}")
            raise IMAPConnectionError(f"Failed to connect: {e}") from e

    def disconnect(self) -> None:
        if self._mailbox:
            self._mailbox.logout()
            self._mailbox = None
            logger.info("Disconnected from IMAP")

    def get_folders(self) -> list[FolderInfo]:
        if not self._mailbox:
            raise IMAPConnectionError("Not connected to IMAP")
        return self._mailbox.folder.list()

    def fetch_emails(
        self,
        folder: str = "INBOX",
        keywords: list[str] | None = None,
        senders: list[str] | None = None,
        recipients: list[str] | None = None,
        unread_only: bool = True,
        include_attachments: bool = False,
        date_since_days: int | None = None,
        limit: int = 50,
    ) -> list[EmailMessage]:
        if not self._mailbox:
            raise IMAPConnectionError("Not connected to IMAP")

        criteria = self._build_criteria(
            keywords=keywords,
            senders=senders,
            recipients=recipients,
            unread_only=unread_only,
            date_since_days=date_since_days,
        )

        try:
            self._mailbox.folder.set(folder)
            messages: list[EmailMessage] = []

            for msg in self._mailbox.fetch(criteria, limit=limit, reverse=True):
                email_msg = self._parse_message(msg, include_attachments)
                messages.append(email_msg)

            logger.info(f"Fetched {len(messages)} emails from {folder}")
            return messages

        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            raise IMAPConnectionError(f"Failed to fetch emails: {e}") from e

    def _build_criteria(
        self,
        keywords: list[str] | None = None,
        senders: list[str] | None = None,
        recipients: list[str] | None = None,
        unread_only: bool = True,
        date_since_days: int | None = None,
    ) -> AND | OR:
        conditions = []

        if unread_only:
            conditions.append(AND(seen=False))

        if senders:
            sender_conditions = [OR(from_=s) for s in senders]
            conditions.append(OR(*sender_conditions))

        if recipients:
            recipient_conditions = [OR(to_=r) for r in recipients]
            conditions.append(OR(*recipient_conditions))

        if keywords:
            keyword_conditions = [OR(subject=k, body=k) for k in keywords]
            conditions.append(OR(*keyword_conditions))

        if not conditions:
            return AND(all=True)

        return AND(*conditions)

    def _parse_message(self, msg, include_attachments: bool) -> EmailMessage:
        has_attachments = len(msg.attachments) > 0 if include_attachments else False

        return EmailMessage(
            message_id=msg.uid or "",
            subject=msg.subject or "",
            sender=str(msg.from_) or "",
            recipient=str(msg.to[0]) if msg.to else None,
            date=msg.date,
            body_text=self._get_text_body(msg),
            body_html=self._get_html_body(msg),
            has_attachments=has_attachments,
        )

    def _get_text_body(self, msg) -> str | None:
        try:
            for part in msg.text_parts:
                if part.content_type == "text/plain":
                    return part.content
        except Exception:
            pass
        return None

    def _get_html_body(self, msg) -> str | None:
        try:
            for part in msg.text_parts:
                if part.content_type == "text/html":
                    return part.content
        except Exception:
            pass
        return None

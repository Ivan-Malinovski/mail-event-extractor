"""IMAP client for connecting to any IMAP server."""

import logging
from dataclasses import dataclass
from datetime import datetime

from imap_tools import AND, OR, FolderInfo, MailBox, MailBoxUnencrypted

from mail_events_to_caldav.exceptions import (
    IMAPAuthenticationError,
    IMAPConnectionError,
)

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
    folder: str | None = None
    recipient: str | None = None
    date: datetime | None = None
    body_text: str | None = None
    body_html: str | None = None
    has_attachments: bool = False
    attachment_texts: list[str] | None = None


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

            try:
                msg_list = list(
                    self._mailbox.fetch(criteria, limit=limit, reverse=True)
                )
            except Exception as fetch_err:
                err_msg = (
                    str(fetch_err)
                    .encode("utf-8", errors="replace")
                    .decode("utf-8", errors="replace")
                )
                logger.error(f"IMAP fetch error: {err_msg}")
                raise IMAPConnectionError(
                    f"Failed to fetch emails: {err_msg}"
                ) from fetch_err

            for msg in msg_list:
                try:
                    email_msg = self._parse_message(msg, folder, include_attachments)
                    messages.append(email_msg)
                except Exception as parse_err:
                    logger.warning(f"Failed to parse email: {parse_err}")
                    continue

            logger.info(f"Fetched {len(messages)} emails from {folder}")
            return messages

        except IMAPConnectionError:
            raise
        except Exception as e:
            err_msg = (
                str(e)
                .encode("utf-8", errors="replace")
                .decode("utf-8", errors="replace")
            )
            logger.error(f"Failed to fetch emails: {err_msg}")
            raise IMAPConnectionError(f"Failed to fetch emails: {err_msg}") from e

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

    def _parse_message(
        self, msg, folder: str, include_attachments: bool
    ) -> EmailMessage:
        has_attachments = len(msg.attachments) > 0 if include_attachments else False
        attachment_texts = None

        if include_attachments and has_attachments:
            attachment_texts = self._extract_attachment_texts(msg.attachments)

        def safe_str(value) -> str:
            if value is None:
                return ""
            try:
                return str(value)
            except UnicodeEncodeError:
                return str(value.encode("utf-8", errors="replace"), "utf-8")

        return EmailMessage(
            message_id=safe_str(msg.uid),
            subject=safe_str(msg.subject),
            sender=safe_str(msg.from_),
            folder=folder,
            recipient=safe_str(msg.to[0]) if msg.to else None,
            date=msg.date,
            body_text=self._get_text_body(msg),
            body_html=self._get_html_body(msg),
            has_attachments=has_attachments,
            attachment_texts=attachment_texts,
        )

    def _extract_attachment_texts(self, attachments) -> list[str]:
        texts = []
        for att in attachments:
            try:
                filename = att.filename or ""
                if filename.lower().endswith(".pdf"):
                    payload = att.payload
                    if hasattr(att, "content") and att.content:
                        payload = att.content
                    text = self._extract_pdf_text(payload)
                    if text:
                        logger.info(f"Extracted {len(text)} chars from PDF: {filename}")
                        texts.append(f"[PDF: {filename}]\n{text}")
                    else:
                        logger.warning(f"No text extracted from PDF: {filename}")
            except Exception as e:
                logger.warning(f"Failed to extract attachment {att.filename}: {e}")
        return texts

    def _extract_pdf_text(self, payload) -> str | None:
        try:
            import io

            from pypdf import PdfReader

            if isinstance(payload, str):
                import base64

                payload = base64.b64decode(payload)
            reader = PdfReader(io.BytesIO(payload))
            text_parts = []
            for i, page in enumerate(reader.pages):
                if i >= 2:
                    break
                text_parts.append(page.extract_text())
            return "\n".join(text_parts) if text_parts else None
        except Exception as e:
            logger.warning(f"Failed to extract PDF text: {e}")
            return None

    def _get_text_body(self, msg) -> str | None:
        try:
            if msg.text:
                return msg.text
            if msg.html:
                return self._strip_html(msg.html)
        except Exception:
            pass
        return None

    def _strip_html(self, html: str) -> str:
        import re

        text = html
        text = re.sub(
            r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(
            r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        text = re.sub(r"&#\d+;", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _get_html_body(self, msg) -> str | None:
        try:
            for part in msg.text_parts:
                if part.content_type == "text/html":
                    return part.content
        except Exception:
            pass
        return None

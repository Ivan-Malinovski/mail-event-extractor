"""Email filtering logic."""

import logging
import re
from dataclasses import dataclass

from mail_events_to_caldav.imap_client import EmailMessage

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    folders: list[str]
    keywords: list[str]
    keywords_regex: list[str]
    senders: list[str]
    senders_regex: list[str]
    recipients: list[str]
    recipients_regex: list[str]
    include_attachments: bool
    unread_only: bool
    date_since_days: int | None


class EmailFilter:
    def __init__(self, config: FilterConfig):
        self.config = config
        self._compiled_keywords_regex: list[re.Pattern] = []
        self._compiled_senders_regex: list[re.Pattern] = []
        self._compiled_recipients_regex: list[re.Pattern] = []
        self._compile_regexes()

    def _compile_regexes(self) -> None:
        for pattern in self.config.keywords_regex:
            try:
                self._compiled_keywords_regex.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}': {e}")

        for pattern in self.config.senders_regex:
            try:
                self._compiled_senders_regex.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}': {e}")

        for pattern in self.config.recipients_regex:
            try:
                self._compiled_recipients_regex.append(
                    re.compile(pattern, re.IGNORECASE)
                )
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}': {e}")

    def should_process(self, email: EmailMessage) -> bool:
        if not self._check_folders(email):
            logger.warning(f"FILTERED folders: {email.subject[:40]}")
            return False
        if not self._check_keywords(email):
            return False
        if not self._check_keywords_regex(email):
            logger.warning(f"FILTERED keywords_regex: {email.subject[:40]}")
            return False
        if not self._check_senders(email):
            logger.warning(f"FILTERED senders: {email.subject[:40]}")
            return False
        if not self._check_senders_regex(email):
            logger.warning(f"FILTERED senders_regex: {email.subject[:40]}")
            return False
        if not self._check_recipients(email):
            logger.warning(f"FILTERED recipients: {email.subject[:40]}")
            return False
        if not self._check_recipients_regex(email):
            logger.warning(f"FILTERED recipients_regex: {email.subject[:40]}")
            return False
        if not self._check_attachments(email):
            logger.warning(f"FILTERED attachments: {email.subject[:40]}")
            return False
        return True

    def _check_folders(self, email: EmailMessage) -> bool:
        if not self.config.folders:
            return True
        if not email.folder:
            return True
        return email.folder in self.config.folders

    def _check_keywords(self, email: EmailMessage) -> bool:
        if not self.config.keywords:
            return True

        subject_lower = (email.subject or "").lower()
        body_lower = (email.body_text or "").lower()

        for keyword in self.config.keywords:
            kw = keyword.lower()
            in_subject = kw in subject_lower
            in_body = kw in body_lower
            if in_subject or in_body:
                return True

        logger.warning(
            f"KEYWORDS FILTER: '{email.subject[:40]}' - subject='{subject_lower[:30]}', body='{body_lower[:30]}', keywords={self.config.keywords}"
        )
        return False

    def _check_keywords_regex(self, email: EmailMessage) -> bool:
        if not self._compiled_keywords_regex:
            return True

        subject = email.subject or ""
        body = email.body_text or ""

        for pattern in self._compiled_keywords_regex:
            if pattern.search(subject) or pattern.search(body):
                return True

        return False

    def _check_senders(self, email: EmailMessage) -> bool:
        if not self.config.senders:
            return True

        sender_lower = email.sender.lower()
        for sender in self.config.senders:
            if sender.lower() in sender_lower:
                return True

        return False

    def _check_senders_regex(self, email: EmailMessage) -> bool:
        if not self._compiled_senders_regex:
            return True

        sender = email.sender or ""

        for pattern in self._compiled_senders_regex:
            if pattern.search(sender):
                return True

        return False

    def _check_recipients(self, email: EmailMessage) -> bool:
        if not self.config.recipients:
            return True

        if not email.recipient:
            return False

        recipient_lower = email.recipient.lower()
        for recipient in self.config.recipients:
            if recipient.lower() in recipient_lower:
                return True

        return False

    def _check_recipients_regex(self, email: EmailMessage) -> bool:
        if not self._compiled_recipients_regex:
            return True

        if not email.recipient:
            return False

        for pattern in self._compiled_recipients_regex:
            if pattern.search(email.recipient):
                return True

        return False

    def _check_attachments(self, email: EmailMessage) -> bool:
        if not self.config.include_attachments:
            return True
        return email.has_attachments is True


def extract_email_address(email_str: str) -> str | None:
    match = re.search(r"<(.+?)>", email_str)
    if match:
        return match.group(1)
    if "@" in email_str:
        return email_str
    return None

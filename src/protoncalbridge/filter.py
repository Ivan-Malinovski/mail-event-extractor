"""Email filtering logic."""

import logging
import re
from dataclasses import dataclass

from protoncalbridge.imap_client import EmailMessage

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    folders: list[str]
    keywords: list[str]
    senders: list[str]
    recipients: list[str]
    include_attachments: bool
    unread_only: bool
    date_since_days: int | None


class EmailFilter:
    def __init__(self, config: FilterConfig):
        self.config = config

    def should_process(self, email: EmailMessage) -> bool:
        if not self._check_folders(email):
            return False
        if not self._check_keywords(email):
            return False
        if not self._check_senders(email):
            return False
        if not self._check_recipients(email):
            return False
        if not self._check_attachments(email):
            return False
        return True

    def _check_folders(self, email: EmailMessage) -> bool:
        if not self.config.folders:
            return True
        return True

    def _check_keywords(self, email: EmailMessage) -> bool:
        if not self.config.keywords:
            return True

        subject_lower = email.subject.lower()
        body_lower = (email.body_text or "").lower()

        for keyword in self.config.keywords:
            if keyword.lower() in subject_lower or keyword.lower() in body_lower:
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

    def _check_attachments(self, email: EmailMessage) -> bool:
        if not self.config.include_attachments:
            return True
        return email.has_attachments


def extract_email_address(email_str: str) -> str | None:
    match = re.search(r"<(.+?)>", email_str)
    if match:
        return match.group(1)
    if "@" in email_str:
        return email_str
    return None

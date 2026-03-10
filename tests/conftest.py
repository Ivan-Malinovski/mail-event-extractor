"""Test fixtures for ProtonCalBridge tests."""

from datetime import datetime

import pytest

from protoncalbridge.filter import EmailFilter, FilterConfig
from protoncalbridge.imap_client import EmailMessage


@pytest.fixture
def filter_config() -> FilterConfig:
    return FilterConfig(
        folders=["INBOX"],
        keywords=["meeting", "event"],
        keywords_regex=[],
        senders=[],
        senders_regex=[],
        recipients=[],
        recipients_regex=[],
        include_attachments=False,
        unread_only=True,
        date_since_days=None,
    )


@pytest.fixture
def email_filter(filter_config) -> EmailFilter:
    return EmailFilter(filter_config)


@pytest.fixture
def sample_email() -> EmailMessage:
    return EmailMessage(
        message_id="<test@example.com>",
        subject="Team Meeting",
        sender="alice@example.com",
        recipient="bob@example.com",
        date=datetime(2024, 1, 15, 10, 0, 0),
        body_text="Let's have a meeting tomorrow at 2pm",
        body_html=None,
        has_attachments=False,
    )


@pytest.fixture
def sample_email_no_match() -> EmailMessage:
    return EmailMessage(
        message_id="<test2@example.com>",
        subject="Newsletter",
        sender="newsletter@example.com",
        recipient="bob@example.com",
        date=datetime(2024, 1, 15, 10, 0, 0),
        body_text="This is a regular email",
        body_html=None,
        has_attachments=False,
    )

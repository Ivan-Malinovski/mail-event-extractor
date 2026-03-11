"""Tests for email filtering logic."""

from datetime import datetime

from mail_events_to_caldav.filter import EmailFilter, FilterConfig
from mail_events_to_caldav.imap_client import EmailMessage


class TestEmailFilter:
    def test_should_process_with_matching_keyword_in_subject(
        self, email_filter, sample_email
    ):
        assert email_filter.should_process(sample_email) is True

    def test_should_process_without_matching_keyword(
        self, email_filter, sample_email_no_match
    ):
        assert email_filter.should_process(sample_email_no_match) is False

    def test_should_process_with_no_keywords(self):
        config = FilterConfig(
            folders=["INBOX"],
            keywords=[],
            keywords_regex=[],
            senders=[],
            senders_regex=[],
            recipients=[],
            recipients_regex=[],
            include_attachments=False,
            unread_only=True,
            date_since_days=None,
        )
        filter = EmailFilter(config)
        email = EmailMessage(
            message_id="<test@example.com>",
            subject="Random Subject",
            sender="anyone@example.com",
            date=datetime(2024, 1, 15, 10, 0, 0),
            body_text="Some text",
        )
        assert filter.should_process(email) is True

    def test_should_process_with_matching_sender(self):
        config = FilterConfig(
            folders=["INBOX"],
            keywords=[],
            keywords_regex=[],
            senders=["alice@example.com"],
            senders_regex=[],
            recipients=[],
            recipients_regex=[],
            include_attachments=False,
            unread_only=True,
            date_since_days=None,
        )
        filter = EmailFilter(config)
        email = EmailMessage(
            message_id="<test@example.com>",
            subject="Hello",
            sender="Alice Example <alice@example.com>",
            date=datetime(2024, 1, 15, 10, 0, 0),
            body_text="Some text",
        )
        assert filter.should_process(email) is True

    def test_should_process_with_non_matching_sender(self):
        config = FilterConfig(
            folders=["INBOX"],
            keywords=[],
            keywords_regex=[],
            senders=["alice@example.com"],
            senders_regex=[],
            recipients=[],
            recipients_regex=[],
            include_attachments=False,
            unread_only=True,
            date_since_days=None,
        )
        filter = EmailFilter(config)
        email = EmailMessage(
            message_id="<test@example.com>",
            subject="Hello",
            sender="bob@example.com",
            date=datetime(2024, 1, 15, 10, 0, 0),
            body_text="Some text",
        )
        assert filter.should_process(email) is False

    def test_should_process_with_matching_recipient(self):
        config = FilterConfig(
            folders=["INBOX"],
            keywords=[],
            keywords_regex=[],
            senders=[],
            senders_regex=[],
            recipients=["bob@example.com"],
            recipients_regex=[],
            include_attachments=False,
            unread_only=True,
            date_since_days=None,
        )
        filter = EmailFilter(config)
        email = EmailMessage(
            message_id="<test@example.com>",
            subject="Hello",
            sender="alice@example.com",
            recipient="Bob Example <bob@example.com>",
            date=datetime(2024, 1, 15, 10, 0, 0),
            body_text="Some text",
        )
        assert filter.should_process(email) is True

    def test_should_process_with_keyword_regex(self):
        config = FilterConfig(
            folders=["INBOX"],
            keywords=[],
            keywords_regex=[r"meeting\s*\d+"],
            senders=[],
            senders_regex=[],
            recipients=[],
            recipients_regex=[],
            include_attachments=False,
            unread_only=True,
            date_since_days=None,
        )
        filter = EmailFilter(config)
        email = EmailMessage(
            message_id="<test@example.com>",
            subject="Meeting 123",
            sender="alice@example.com",
            date=datetime(2024, 1, 15, 10, 0, 0),
            body_text="Some text",
        )
        assert filter.should_process(email) is True

    def test_should_process_attachments_required_but_none(self):
        config = FilterConfig(
            folders=["INBOX"],
            keywords=["meeting"],
            keywords_regex=[],
            senders=[],
            senders_regex=[],
            recipients=[],
            recipients_regex=[],
            include_attachments=True,
            unread_only=True,
            date_since_days=None,
        )
        filter = EmailFilter(config)
        email = EmailMessage(
            message_id="<test@example.com>",
            subject="Meeting",
            sender="alice@example.com",
            date=datetime(2024, 1, 15, 10, 0, 0),
            body_text="Some text",
            has_attachments=False,
        )
        assert filter.should_process(email) is False

    def test_should_process_attachments_required_and_has_attachments(self):
        config = FilterConfig(
            folders=["INBOX"],
            keywords=["meeting"],
            keywords_regex=[],
            senders=[],
            senders_regex=[],
            recipients=[],
            recipients_regex=[],
            include_attachments=True,
            unread_only=True,
            date_since_days=None,
        )
        filter = EmailFilter(config)
        email = EmailMessage(
            message_id="<test@example.com>",
            subject="Meeting",
            sender="alice@example.com",
            date=datetime(2024, 1, 15, 10, 0, 0),
            body_text="Some text",
            has_attachments=True,
        )
        assert filter.should_process(email) is True

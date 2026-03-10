"""Tests for CalDAV client."""

from datetime import datetime

import pytest

from protoncalbridge.caldav_client import CalDAVClient, CalDAVConfig, CalendarEvent


@pytest.fixture
def caldav_config() -> CalDAVConfig:
    return CalDAVConfig(
        server_url="https://caldav.example.com",
        username="user",
        password="pass",
        calendar_id="calendar-1",
        verify_ssl=True,
    )


@pytest.fixture
def caldav_client(caldav_config) -> CalDAVClient:
    return CalDAVClient(caldav_config)


@pytest.fixture
def sample_event() -> CalendarEvent:
    return CalendarEvent(
        title="Team Meeting",
        start_time=datetime(2024, 1, 15, 14, 0, 0),
        end_time=datetime(2024, 1, 15, 15, 0, 0),
        location="Conference Room A",
        description="Weekly team sync",
        all_day=False,
    )


class TestCalDAVClient:
    def test_escape_ics_text_none(self, caldav_client):
        assert caldav_client._escape_ics_text(None) == ""

    def test_escape_ics_text_empty(self, caldav_client):
        assert caldav_client._escape_ics_text("") == ""

    def test_escape_ics_text_backslash(self, caldav_client):
        result = caldav_client._escape_ics_text("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_ics_text_comma(self, caldav_client):
        result = caldav_client._escape_ics_text("a, b, c")
        assert result == "a\\, b\\, c"

    def test_escape_ics_text_semicolon(self, caldav_client):
        result = caldav_client._escape_ics_text("a; b; c")
        assert result == "a\\; b\\; c"

    def test_escape_ics_text_newline(self, caldav_client):
        result = caldav_client._escape_ics_text("line1\nline2")
        assert result == "line1\\nline2"

    def test_escape_ics_text_carriage_return(self, caldav_client):
        result = caldav_client._escape_ics_text("line1\r\nline2")
        assert result == "line1\\nline2"

    def test_escape_ics_text_all(self, caldav_client):
        result = caldav_client._escape_ics_text("a\\b;c,d\n")
        assert result == "a\\\\b\\;c\\,d\\n"

    def test_create_ics_with_special_characters(self, caldav_client):
        event = CalendarEvent(
            title="Meeting, with, commas",
            start_time=datetime(2024, 1, 15, 14, 0, 0),
            end_time=datetime(2024, 1, 15, 15, 0, 0),
            location="Room A; B",
            description="Line1\nLine2",
            all_day=False,
        )
        ics = caldav_client._create_ics(event)
        assert "Meeting\\, with\\, commas" in ics
        assert "Room A\\; B" in ics
        assert "Line1\\nLine2" in ics

    def test_create_ics_all_day_event(self, caldav_client):
        event = CalendarEvent(
            title="All Day Event",
            start_time=datetime(2024, 1, 15, 0, 0, 0),
            end_time=datetime(2024, 1, 16, 0, 0, 0),
            location=None,
            description=None,
            all_day=True,
        )
        ics = caldav_client._create_ics(event)
        assert "DTSTART:20240115" in ics
        assert "DTEND:20240116" in ics

    def test_create_ics_timed_event(self, caldav_client):
        event = CalendarEvent(
            title="Timed Event",
            start_time=datetime(2024, 1, 15, 14, 0, 0),
            end_time=datetime(2024, 1, 15, 15, 0, 0),
            location=None,
            description=None,
            all_day=False,
        )
        ics = caldav_client._create_ics(event)
        assert "DTSTART:20240115T140000Z" in ics
        assert "DTEND:20240115T150000Z" in ics

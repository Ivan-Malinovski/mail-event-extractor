"""Tests for config service."""

import pytest
from protoncalbridge.config_service import (
    build_caldav_config,
    build_filter_config,
    build_imap_config,
    build_llm_config,
    build_processing_config,
    build_scheduler_config,
    ensure_event_times,
    event_to_dict,
)
from protoncalbridge.llm_parser import CalendarEvent


class TestConfigService:
    def test_build_imap_config(self):
        config = {
            "imap": {
                "host": "mail.example.com",
                "port": 993,
                "username": "user@example.com",
                "password": "secret",
                "use_ssl": True,
            }
        }
        imap = build_imap_config(config)
        assert imap.host == "mail.example.com"
        assert imap.port == 993
        assert imap.username == "user@example.com"
        assert imap.password == "secret"
        assert imap.use_ssl is True

    def test_build_imap_config_defaults(self):
        config = {}
        imap = build_imap_config(config)
        assert imap.host == "127.0.0.1"
        assert imap.port == 1143
        assert imap.use_ssl is True

    def test_build_filter_config(self):
        config = {
            "filter": {
                "folders": ["INBOX", "Sent"],
                "keywords": ["meeting", "event"],
                "keywords_regex": [".*urgent.*"],
                "senders": ["boss@company.com"],
                "senders_regex": [".*@company\\.com"],
                "recipients": [],
                "recipients_regex": [],
                "include_attachments": True,
                "unread_only": False,
                "date_since_days": 7,
            }
        }
        filter_cfg = build_filter_config(config)
        assert filter_cfg.folders == ["INBOX", "Sent"]
        assert filter_cfg.keywords == ["meeting", "event"]
        assert filter_cfg.keywords_regex == [".*urgent.*"]
        assert filter_cfg.senders == ["boss@company.com"]
        assert filter_cfg.include_attachments is True
        assert filter_cfg.unread_only is False
        assert filter_cfg.date_since_days == 7

    def test_build_llm_config(self):
        config = {
            "llm": {
                "provider": "openai-compatible",
                "api_key": "sk-test",
                "model": "gpt-4",
                "base_url": "https://api.example.com",
                "temperature": 0.5,
                "max_tokens": 2000,
                "system_prompt": "Custom prompt",
            },
            "timezone": "Europe/Copenhagen",
        }
        llm = build_llm_config(config)
        assert llm.provider == "openai-compatible"
        assert llm.api_key == "sk-test"
        assert llm.model == "gpt-4"
        assert llm.base_url == "https://api.example.com"
        assert llm.temperature == 0.5
        assert llm.max_tokens == 2000
        assert llm.system_prompt == "Custom prompt"
        assert llm.tz == "Europe/Copenhagen"

    def test_build_llm_config_no_api_key(self):
        config = {"llm": {}}
        llm = build_llm_config(config)
        assert llm is None

    def test_build_caldav_config(self):
        config = {
            "caldav": {
                "server_url": "https://cal.example.com/dav",
                "username": "user",
                "password": "secret",
                "calendar_id": "work",
                "verify_ssl": True,
            }
        }
        caldav = build_caldav_config(config)
        assert caldav.server_url == "https://cal.example.com/dav"
        assert caldav.username == "user"
        assert caldav.calendar_id == "work"

    def test_build_caldav_config_no_url(self):
        config = {"caldav": {}}
        caldav = build_caldav_config(config)
        assert caldav is None

    def test_build_processing_config(self):
        config = {
            "processing": {
                "auto_create": False,
                "update_existing": True,
                "delete_rejected": True,
                "grace_period_minutes": 10,
            }
        }
        proc = build_processing_config(config)
        assert proc.auto_create is False
        assert proc.update_existing is True
        assert proc.delete_rejected is True
        assert proc.grace_period_minutes == 10

    def test_build_scheduler_config(self):
        config = {
            "scheduler": {
                "check_interval_minutes": 10,
                "active_hours_start": 8,
                "active_hours_end": 18,
            }
        }
        sched = build_scheduler_config(config)
        assert sched.check_interval_minutes == 10
        assert sched.active_hours_start == 8
        assert sched.active_hours_end == 18


class TestEventHelpers:
    def test_event_to_dict(self):
        event = CalendarEvent(
            title="Test Meeting",
            start_time=None,
            end_time=None,
            location="Conference Room",
            description="Test description",
            all_day=False,
        )
        result = event_to_dict(event)
        assert result["title"] == "Test Meeting"
        assert result["location"] == "Conference Room"

    def test_event_to_dict_none(self):
        result = event_to_dict(None)
        assert result is None

    def test_ensure_event_times_no_times(self):
        event = CalendarEvent(
            title="All Day Event",
            start_time=None,
            end_time=None,
            location=None,
            description=None,
            all_day=True,
        )
        result = ensure_event_times(event)
        assert result.start_time is not None
        assert result.end_time is not None
        assert result.all_day is True

    def test_ensure_event_times_with_times(self):
        from datetime import datetime
        event = CalendarEvent(
            title="Meeting",
            start_time=datetime(2026, 3, 15, 10, 0),
            end_time=datetime(2026, 3, 15, 11, 0),
            location="Room A",
            description="Test",
            all_day=False,
        )
        result = ensure_event_times(event)
        assert result.start_time.hour == 10

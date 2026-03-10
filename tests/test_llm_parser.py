"""Tests for LLM parser timezone handling."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from protoncalbridge.llm_parser import LLMParser, LLMConfig, DEFAULT_TIMEZONE


class TestLLMParserTimezone:
    def test_parse_datetime_with_timezone_copenhagen(self):
        config = LLMConfig(
            provider="openai",
            api_key="test",
            model="test",
            tz="Europe/Copenhagen",
        )
        parser = LLMParser(config)
        
        result = parser._parse_datetime("2026-03-11T07:00:00", "Europe/Copenhagen")
        
        assert result is not None
        assert result.hour == 6
        assert result.minute == 0
        
    def test_parse_datetime_with_timezone_utc(self):
        config = LLMConfig(
            provider="openai",
            api_key="test",
            model="test",
            tz="UTC",
        )
        parser = LLMParser(config)
        
        result = parser._parse_datetime("2026-03-11T07:00:00", "UTC")
        
        assert result is not None
        assert result.hour == 7
        assert result.tzinfo == timezone.utc

    def test_parse_datetime_with_explicit_utc(self):
        config = LLMConfig(
            provider="openai",
            api_key="test",
            model="test",
            tz="Europe/Copenhagen",
        )
        parser = LLMParser(config)
        
        result = parser._parse_datetime("2026-03-11T07:00:00Z", "Europe/Copenhagen")
        
        assert result is not None
        assert result.hour == 7

    def test_parse_datetime_none_input(self):
        config = LLMConfig(provider="openai", api_key="test", model="test")
        parser = LLMParser(config)
        
        result = parser._parse_datetime(None)
        assert result is None

    def test_default_timezone(self):
        assert DEFAULT_TIMEZONE == "Europe/Copenhagen"

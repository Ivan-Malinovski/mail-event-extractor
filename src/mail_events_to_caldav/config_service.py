"""Configuration service for building config objects from stored settings."""

from datetime import datetime
from typing import Any

from mail_events_to_caldav.caldav_client import CalDAVConfig
from mail_events_to_caldav.filter import FilterConfig
from mail_events_to_caldav.imap_client import IMAPConfig
from mail_events_to_caldav.llm_parser import CalendarEvent, LLMConfig
from mail_events_to_caldav.scheduler import ProcessingConfig, SchedulerConfig


def build_imap_config(config: dict[str, Any]) -> IMAPConfig:
    imap_data = config.get("imap", {})
    return IMAPConfig(
        host=imap_data.get("host", "127.0.0.1"),
        port=imap_data.get("port", 1143),
        username=imap_data.get("username", ""),
        password=imap_data.get("password", ""),
        use_ssl=imap_data.get("use_ssl", True),
    )


def build_filter_config(config: dict[str, Any]) -> FilterConfig:
    filter_data = config.get("filter", {})
    return FilterConfig(
        folders=filter_data.get("folders", ["INBOX"]),
        keywords=filter_data.get("keywords", []),
        keywords_regex=filter_data.get("keywords_regex", []),
        senders=filter_data.get("senders", []),
        senders_regex=filter_data.get("senders_regex", []),
        recipients=filter_data.get("recipients", []),
        recipients_regex=filter_data.get("recipients_regex", []),
        include_attachments=filter_data.get("include_attachments", False),
        unread_only=filter_data.get("unread_only", True),
        date_since_days=filter_data.get("date_since_days"),
    )


def build_llm_config(config: dict[str, Any]) -> LLMConfig | None:
    llm_data = config.get("llm", {})
    if not llm_data.get("api_key"):
        return None
    return LLMConfig(
        provider=llm_data.get("provider", "openai"),
        api_key=llm_data.get("api_key", ""),
        model=llm_data.get("model", "gpt-4o-mini"),
        base_url=llm_data.get("base_url"),
        temperature=llm_data.get("temperature", 0.0),
        max_tokens=llm_data.get("max_tokens", 1000),
        system_prompt=llm_data.get("system_prompt", ""),
        tz=config.get("timezone", "Europe/Copenhagen"),
    )


def build_caldav_config(config: dict[str, Any]) -> CalDAVConfig | None:
    caldav_data = config.get("caldav", {})
    if not caldav_data.get("server_url"):
        return None
    return CalDAVConfig(
        server_url=caldav_data.get("server_url", ""),
        username=caldav_data.get("username", ""),
        password=caldav_data.get("password", ""),
        calendar_id=caldav_data.get("calendar_id", ""),
        verify_ssl=caldav_data.get("verify_ssl", True),
    )


def build_processing_config(config: dict[str, Any]) -> ProcessingConfig:
    processing_data = config.get("processing", {})
    return ProcessingConfig(
        auto_create=processing_data.get("auto_create", True),
        update_existing=processing_data.get("update_existing", True),
        delete_rejected=processing_data.get("delete_rejected", False),
        grace_period_minutes=processing_data.get("grace_period_minutes", 0),
    )


def build_scheduler_config(config: dict[str, Any]) -> SchedulerConfig:
    scheduler_data = config.get("scheduler", {})
    return SchedulerConfig(
        check_interval_minutes=scheduler_data.get("check_interval_minutes", 5),
        active_hours_start=scheduler_data.get("active_hours_start"),
        active_hours_end=scheduler_data.get("active_hours_end"),
    )


def ensure_event_times(event: CalendarEvent) -> CalendarEvent:
    if not event.start_time:
        event.start_time = datetime.combine(datetime.now().date(), datetime.min.time())
        event.end_time = event.start_time
        event.all_day = True
    return event


def ensure_events_times(events: list[CalendarEvent]) -> list[CalendarEvent]:
    return [ensure_event_times(e) for e in events]

"""Configuration manager for storing and retrieving app settings."""

import copy
import json
import logging
from typing import Any

from sqlalchemy import delete, select

from mail_events_to_caldav.database import Config, async_session

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "imap": {
        "host": "127.0.0.1",
        "port": 1143,
        "username": "",
        "password": "",
        "use_ssl": True,
    },
    "filter": {
        "folders": ["INBOX"],
        "keywords": [],
        "keywords_regex": [],
        "senders": [],
        "senders_regex": [],
        "recipients": [],
        "recipients_regex": [],
        "include_attachments": False,
        "unread_only": True,
        "date_since_days": None,
    },
    "scheduler": {
        "check_interval_minutes": 5,
        "active_hours_start": None,
        "active_hours_end": None,
    },
    "llm": {
        "provider": "openai",
        "api_key": "",
        "model": "gpt-4o-mini",
        "base_url": None,
        "temperature": 0.0,
        "max_tokens": 1000,
        "system_prompt": 'You are an email calendar event parser. Extract calendar events from emails. Feel free to rephrase titles for brevity, and add a fitting emoji in front of the title. If description is relevant, ensure it\'s easily human readable. If there are more events, output each as separate JSON objects. If you consider it a task, put task as true.\nReturn a JSON object with: title, start_time, end_time, location, description, all_day (boolean), task (boolean).\nIf no valid event found, return {"error": "no_event"}.\nTimes must be in ISO 8601 format.',
    },
    "caldav": {
        "server_url": "",
        "username": "",
        "password": "",
        "calendar_id": "",
        "verify_ssl": True,
    },
    "processing": {
        "auto_create": True,
        "update_existing": True,
        "delete_rejected": False,
        "grace_period_minutes": 0,
    },
    "web": {
        "host": "0.0.0.0",
        "port": 8080,
        "auth_enabled": False,
        "password": "",
    },
    "timezone": "UTC",
    "time_format": "24h",
    "logging": {
        "level": "INFO",
        "retention_days": 30,
    },
}


PRESETS: dict = {
    "meeting": {
        "name": "Meeting Invites",
        "keywords": [
            "meeting",
            "invite",
            "invitation",
            "zoom",
            "teams",
            "google meet",
            "call",
        ],
        "keywords_regex": [],
    },
    "event": {
        "name": "Calendar Events",
        "keywords": ["event", "appointment", "reservation", "booking"],
        "keywords_regex": [],
    },
    "reminder": {
        "name": "Reminders",
        "keywords": ["reminder", "remind", "upcoming", "don't forget"],
        "keywords_regex": [],
    },
    "flight": {
        "name": "Flight Tickets",
        "keywords": ["flight", "boarding", "airline", "departure", "arrival"],
        "keywords_regex": [],
    },
    "hotel": {
        "name": "Hotel Reservations",
        "keywords": ["hotel", "accommodation", "check-in", "check-out", "reservation"],
        "keywords_regex": [],
    },
    "dinner": {
        "name": "Restaurant Reservations",
        "keywords": ["restaurant", "dinner", "lunch", "reservation", "table"],
        "keywords_regex": [],
    },
}


class ConfigManager:
    @staticmethod
    async def get_config() -> dict:
        async with async_session() as session:
            result = await session.execute(select(Config))
            configs = result.scalars().all()

            config = copy.deepcopy(DEFAULT_CONFIG)
            for c in configs:
                if c.value:
                    try:
                        value = json.loads(c.value)
                        keys = c.key.split(".")
                        current = config
                        for k in keys[:-1]:
                            if k not in current:
                                current[k] = {}
                            current = current[k]
                        current[keys[-1]] = value
                    except json.JSONDecodeError:
                        pass

            if "filter" in config and config["filter"]:
                filter_defaults = {
                    "folders": ["INBOX"],
                    "keywords": [],
                    "keywords_regex": [],
                    "senders": [],
                    "senders_regex": [],
                    "recipients": [],
                    "recipients_regex": [],
                    "include_attachments": False,
                    "unread_only": True,
                    "date_since_days": None,
                }
                for key, default_value in filter_defaults.items():
                    if key not in config["filter"] or config["filter"][key] is None:
                        config["filter"][key] = default_value

            return config

    @staticmethod
    async def set_config(key: str, value: Any) -> None:
        from datetime import datetime

        async with async_session() as session:
            json_value = json.dumps(value)
            result = await session.execute(select(Config).where(Config.key == key))
            existing = result.scalar_one_or_none()

            if existing:
                existing.value = json_value
                existing.updated_at = datetime.utcnow()
            else:
                config = Config(key=key, value=json_value)
                session.add(config)

            await session.commit()
            logger.info(f"Config updated: {key}")

    @staticmethod
    async def set_config_section(section: str, values: dict) -> None:
        for key, value in values.items():
            full_key = f"{section}.{key}"
            await ConfigManager.set_config(full_key, value)

    @staticmethod
    async def get_config_value(key: str, default: Any = None) -> Any:
        async with async_session() as session:
            result = await session.execute(select(Config).where(Config.key == key))
            config = result.scalar_one_or_none()
            if config and config.value:
                try:
                    return json.loads(config.value)
                except json.JSONDecodeError:
                    return config.value
            return default

    @staticmethod
    async def delete_config(key: str) -> None:
        async with async_session() as session:
            result = await session.execute(select(Config).where(Config.key == key))
            config = result.scalar_one_or_none()
            if config:
                await session.delete(config)
                await session.commit()
                logger.info(f"Config deleted: {key}")

    @staticmethod
    async def export_config() -> dict:
        return await ConfigManager.get_config()

    @staticmethod
    async def import_config(config: dict) -> None:
        def flatten_dict(d: dict, parent_key: str = "") -> dict:
            items = []
            for k, v in d.items():
                new_key = f"{parent_key}.{k}" if parent_key else k
                if isinstance(v, dict):
                    items.extend(flatten_dict(v, new_key).items())
                else:
                    items.append((new_key, v))
            return dict(items)

        flat_config = flatten_dict(config)
        for key, value in flat_config.items():
            await ConfigManager.set_config(key, value)

    @staticmethod
    async def clear_config() -> None:
        async with async_session() as session:
            await session.execute(delete(Config))
            await session.commit()
            logger.info("Config cleared")

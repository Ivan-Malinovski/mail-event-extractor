"""Configuration manager for storing and retrieving app settings."""

import json
import logging
from typing import Any

from sqlalchemy import select

from protoncalbridge.database import Config, async_session

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
        "senders": [],
        "recipients": [],
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
        "system_prompt": "You are an email calendar event parser. Extract calendar events from emails.\nReturn a JSON object with: title, start_time, end_time, location, description, all_day (boolean).\nIf no valid event found, return {\"error\": \"no_event\"}.\nTimes must be in ISO 8601 format.",
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


class ConfigManager:
    @staticmethod
    async def get_config() -> dict:
        async with async_session() as session:
            result = await session.execute(select(Config))
            configs = result.scalars().all()

            config = DEFAULT_CONFIG.copy()
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

            return config

    @staticmethod
    async def set_config(key: str, value: Any) -> None:
        async with async_session() as session:
            json_value = json.dumps(value)
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
            await session.execute("DELETE FROM config")
            await session.commit()
            logger.info("Config cleared")

"""LLM parser for extracting calendar events from emails."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx

from protoncalbridge.exceptions import LLMError, LLMParseError

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    provider: Literal["openai", "anthropic", "ollama", "openai-compatible"]
    api_key: str
    model: str
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1000
    system_prompt: str = ""


DEFAULT_SYSTEM_PROMPT = """You are an email calendar event parser. Extract calendar events from emails.
Return a JSON object with: title, start_time, end_time, location, description, all_day (boolean).
If no valid event found, return {"error": "no_event"}.
Times must be in ISO 8601 format."""


@dataclass
class CalendarEvent:
    title: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    description: str | None = None
    all_day: bool = False


class LLMParser:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def parse_event(self, email_subject: str, email_body: str) -> CalendarEvent:
        user_prompt = f"""Extract calendar event from this email:

Subject: {email_subject}

Body:
{email_body}

Return JSON with: title, start_time, end_time, location, description, all_day (boolean)."""

        try:
            if self.config.provider == "openai":
                return await self._parse_openai(user_prompt)
            elif self.config.provider == "anthropic":
                return await self._parse_anthropic(user_prompt)
            elif self.config.provider == "ollama":
                return await self._parse_ollama(user_prompt)
            elif self.config.provider == "openai-compatible":
                return await self._parse_openai_compatible(user_prompt)
            else:
                raise LLMError(f"Unknown provider: {self.config.provider}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            raise LLMParseError(f"Invalid JSON response from LLM: {e}") from e
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            raise LLMError(f"LLM request failed: {e}") from e

    async def _parse_openai(self, user_prompt: str) -> CalendarEvent:
        client = await self._get_client()
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_response(content)

    async def _parse_anthropic(self, user_prompt: str) -> CalendarEvent:
        client = await self._get_client()
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "system": self.system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["content"][0]["text"]
        return self._parse_response(content)

    async def _parse_ollama(self, user_prompt: str) -> CalendarEvent:
        base_url = self.config.base_url or "http://localhost:11434"
        client = await self._get_client()
        response = await client.post(
            f"{base_url}/api/generate",
            json={
                "model": self.config.model,
                "prompt": f"{self.system_prompt}\n\n{user_prompt}",
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("response", "")
        return self._parse_response(content)

    async def _parse_openai_compatible(self, user_prompt: str) -> CalendarEvent:
        base_url = self.config.base_url or "http://localhost:8000"
        client = await self._get_client()
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_response(content)

    def _parse_response(self, content: str) -> CalendarEvent:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        data = json.loads(content)

        if "error" in data:
            raise LLMParseError(f"LLM returned no event: {data['error']}")

        return CalendarEvent(
            title=data.get("title", "Untitled Event"),
            start_time=self._parse_datetime(data.get("start_time")),
            end_time=self._parse_datetime(data.get("end_time")),
            location=data.get("location"),
            description=data.get("description"),
            all_day=data.get("all_day", False),
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

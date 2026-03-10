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

Return valid iCalendar (ICS) format with:
- If time is specified: use DTSTART/DTEND with time (e.g., DTSTART:20240315T140000Z)
- If NO time specified: use all-day event with DATE format (e.g., DTSTART;VALUE=DATE:20240315)
- Include SUMMARY, LOCATION if available
- If no valid event found, return {"error": "no_event"}

Example with time:
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20240315T140000Z
DTEND:20240315T150000Z
SUMMARY:Team Meeting
LOCATION:Conference Room A
END:VEVENT
END:VCALENDAR

Example without time (all-day):
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;VALUE=DATE:20240315
DTEND;VALUE=DATE:20240316
SUMMARY:Conference
END:VEVENT
END:VCALENDAR"""


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
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM HTTP error: {e.response.status_code} - {e.response.text}")
            raise LLMError(f"LLM HTTP error: {e.response.status_code} - {e.response.text[:200]}") from e
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
        base_url = base_url.rstrip("/")
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
        if not content:
            raise LLMParseError("LLM returned empty response")
        return self._parse_response(content)

    def _parse_response(self, content: str) -> CalendarEvent:
        content = content.strip()
        logger.info(f"LLM raw response: {content[:500]}")

        if content.startswith("```"):
            lines = content.split("\n")
            if len(lines) > 1:
                content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content[:-3]
        content = content.strip()

        if content.startswith("BEGIN:VCALENDAR"):
            logger.info("Detected ICS format response")
            return self._parse_ics_response(content)

        if content.startswith("BEGIN:VCALENDAR"):
            logger.info("Detected ICS format response")
            return self._parse_ics_response(content)

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[^{}]*\}', content)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            else:
                raise LLMParseError(f"Invalid response from LLM: {content[:200]}")

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                raise LLMParseError(f"Invalid response from LLM: {content[:200]}")

        if "error" in data:
            raise LLMParseError(f"LLM returned no event: {data['error']}")

        start_time = self._parse_datetime(data.get("start_time"))
        end_time = self._parse_datetime(data.get("end_time"))
        all_day = data.get("all_day", False)

        if not start_time and all_day:
            from datetime import date
            start_time = datetime.combine(date.today(), datetime.min.time())
            if end_time:
                end_time = datetime.combine(date.today(), datetime.min.time())

        return CalendarEvent(
            title=data.get("title", "Untitled Event"),
            start_time=start_time,
            end_time=end_time,
            location=data.get("location"),
            description=data.get("description"),
            all_day=all_day,
        )

    def _parse_ics_response(self, content: str) -> CalendarEvent:
        import re
        title = "Untitled Event"
        location = None
        description = None
        start_time = None
        end_time = None
        all_day = False

        match = re.search(r'SUMMARY:(.+?)(?:\r?\n|$)', content)
        if match:
            title = match.group(1).strip()

        match = re.search(r'LOCATION:(.+?)(?:\r?\n|$)', content)
        if match:
            location = match.group(1).strip()

        match = re.search(r'DESCRIPTION:(.+?)(?:\r?\n|$)', content)
        if match:
            description = match.group(1).strip()

        match = re.search(r'DTSTART(;VALUE=DATE)?:(\d{8}(?:T\d{6}Z)?)', content)
        if match:
            is_date = match.group(1) is not None
            value = match.group(2)
            if is_date:
                all_day = True
                start_time = datetime.strptime(value, "%Y%m%d")
            else:
                start_time = datetime.strptime(value.replace("Z", ""), "%Y%m%dT%H%M%S")

        match = re.search(r'DTEND(;VALUE=DATE)?:(\d{8}(?:T\d{6}Z)?)', content)
        if match:
            is_date = match.group(1) is not None
            value = match.group(2)
            if is_date:
                end_time = datetime.strptime(value, "%Y%m%d")
            else:
                end_time = datetime.strptime(value.replace("Z", ""), "%Y%m%dT%H%M%S")

        if not start_time:
            raise LLMParseError("No DTSTART found in ICS response")

        return CalendarEvent(
            title=title,
            start_time=start_time,
            end_time=end_time,
            location=location,
            description=description,
            all_day=all_day,
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

"""LLM parser for extracting calendar events from emails."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from protoncalbridge.exceptions import LLMError, LLMParseError

logger = logging.getLogger(__name__)


DEFAULT_TIMEZONE = "Europe/Copenhagen"


@dataclass
class LLMConfig:
    provider: Literal["openai", "anthropic", "ollama", "openai-compatible"]
    api_key: str
    model: str
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1000
    system_prompt: str = ""
    tz: str = DEFAULT_TIMEZONE


DEFAULT_SYSTEM_PROMPT = """You are an email calendar event parser. Extract calendar events from emails. Feel free to rephrase titles for brevity, and add a fitting emoji in front of the title. If there are more events, output each as separate JSON objects.If you consider it a task, put task as true.
Return a JSON object with: title, start_time, end_time, location, description, all_day (boolean), task (boolean).
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
    task: bool = False


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

    async def parse_event(self, email_subject: str, email_body: str) -> list[CalendarEvent]:
        user_prompt = f"""Extract calendar event from this email:

Subject: {email_subject}

Body:
{email_body}

Return JSON with: title, start_time, end_time, location, description, all_day (boolean), task (boolean). If multiple events, return an array of JSON objects."""

        for attempt in range(3):
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
            except (LLMError, httpx.HTTPStatusError) as e:
                if attempt < 2:
                    delay = 1.0 * (2**attempt)
                    logger.warning(
                        f"LLM request failed (attempt {attempt + 1}/3): {e}. Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"LLM request failed after 3 attempts: {e}")
                    raise LLMError(f"LLM request failed after 3 attempts: {e}") from e

        raise LLMError("Unexpected error in LLM parsing")

    async def _parse_openai(self, user_prompt: str) -> list[CalendarEvent]:
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

    async def _parse_anthropic(self, user_prompt: str) -> list[CalendarEvent]:
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

    async def _parse_ollama(self, user_prompt: str) -> list[CalendarEvent]:
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

    async def _parse_openai_compatible(self, user_prompt: str) -> list[CalendarEvent]:
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

    def _parse_response(self, content: str) -> list[CalendarEvent]:
        content = content.strip()
        truncated = content[:200] + "..." if len(content) > 200 else content
        logger.debug(f"LLM response (truncated): {truncated}")

        if content.startswith("```"):
            lines = content.split("\n")
            if len(lines) > 1:
                content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content[:-3]
        content = content.strip()

        if content.startswith("BEGIN:VCALENDAR"):
            logger.info("Detected ICS format response")
            event = self._parse_ics_response(content)
            return [event]

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\[[\s\S]*\]|\{[\s\S]*\}', content)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    raise LLMParseError(f"Invalid response from LLM: {content[:200]}")
            else:
                raise LLMParseError(f"Invalid response from LLM: {content[:200]}")

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                raise LLMParseError(f"Invalid response from LLM: {content[:200]}")

        events = []
        if isinstance(data, list):
            items = data
        else:
            items = [data]

        for item in items:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    continue

            if not isinstance(item, dict):
                continue

            if "error" in item:
                continue

            start_time = self._parse_datetime(item.get("start_time"), self.config.tz)
            end_time = self._parse_datetime(item.get("end_time"), self.config.tz)
            all_day = item.get("all_day", False)
            task = item.get("task", False)

            if not start_time and all_day:
                from datetime import date
                start_time = datetime.combine(date.today(), datetime.min.time())
                if end_time:
                    end_time = datetime.combine(date.today(), datetime.min.time())

            events.append(CalendarEvent(
                title=item.get("title", "Untitled Event"),
                start_time=start_time,
                end_time=end_time,
                location=item.get("location"),
                description=item.get("description"),
                all_day=all_day,
                task=task,
            ))

        if not events:
            raise LLMParseError("No valid events found in LLM response")

        return events

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

        return [
            CalendarEvent(
                title=title,
                start_time=start_time,
                end_time=end_time,
                location=location,
                description=description,
                all_day=all_day,
            )
        ]

    def _parse_datetime(self, value: str | None, tz: str = DEFAULT_TIMEZONE) -> datetime | None:
        if not value:
            return None
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                local_tz = ZoneInfo(tz)
                dt = dt.replace(tzinfo=local_tz)
            return dt.astimezone(UTC)
        except ValueError:
            return None


def event_to_dict(event: CalendarEvent | None) -> dict[str, Any] | None:
    if not event:
        return None
    result = {}
    for key, value in event.__dict__.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def events_to_dict_list(events: list[CalendarEvent]) -> list[dict[str, Any]]:
    result = []
    for e in events:
        d = event_to_dict(e)
        if d:
            result.append(d)
    return result

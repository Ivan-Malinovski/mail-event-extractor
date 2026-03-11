"""CalDAV client for creating calendar events."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import caldav
from caldav.lib.error import NotFoundError

from mail_events_to_caldav.exceptions import CalDAVAuthenticationError, CalDAVError
from mail_events_to_caldav.llm_parser import CalendarEvent
from mail_events_to_caldav.retry import with_retry

logger = logging.getLogger(__name__)


@dataclass
class CalDAVConfig:
    server_url: str
    username: str
    password: str
    calendar_id: str
    verify_ssl: bool = True


class CalDAVClient:
    def __init__(self, config: CalDAVConfig):
        self.config = config
        self._client: caldav.DAVClient | None = None
        self._calendar: caldav.Calendar | None = None

    def connect(self) -> None:
        try:
            self._client = caldav.DAVClient(
                url=self.config.server_url,
                username=self.config.username,
                password=self.config.password,
                ssl_verify_cert=self.config.verify_ssl,
            )
            principal = self._client.principal()
            calendars = principal.calendars()

            for cal in calendars:
                if (
                    cal.id == self.config.calendar_id
                    or cal.name == self.config.calendar_id
                ):
                    self._calendar = cal
                    break

            if not self._calendar:
                if calendars:
                    self._calendar = calendars[0]
                else:
                    raise CalDAVError("No calendars found")

            logger.info(f"Connected to CalDAV calendar: {self._calendar.name}")

        except caldav.lib.error.AuthorizationError as e:
            logger.error(f"CalDAV authentication failed: {e}")
            raise CalDAVAuthenticationError(f"Failed to authenticate: {e}") from e
        except Exception as e:
            logger.error(f"CalDAV connection failed: {e}")
            raise CalDAVError(f"Failed to connect: {e}") from e

    def disconnect(self) -> None:
        self._client = None
        self._calendar = None
        logger.info("Disconnected from CalDAV")

    def get_calendars(self) -> list[dict]:
        if not self._client:
            raise CalDAVError("Not connected to CalDAV")

        principal = self._client.principal()
        calendars = principal.calendars()

        return [
            {"id": cal.id, "name": cal.name, "url": str(cal.url)} for cal in calendars
        ]

    @with_retry(max_attempts=3, base_delay=1.0, exceptions=(CalDAVError,))
    def create_event(self, event: CalendarEvent, uid: str | None = None) -> str:
        if not self._calendar:
            raise CalDAVError("Not connected to CalDAV")

        ics_content = self._create_ics(event, uid)

        try:
            result = self._calendar.add_event(ics_content)
            event_id = uid or result
            logger.info(f"Created calendar event: {event_id}")
            return event_id
        except Exception as e:
            logger.error(f"Failed to create calendar event: {e}")
            raise CalDAVError(f"Failed to create event: {e}") from e

    def update_event(self, event_id: str, event: CalendarEvent) -> None:
        if not self._calendar:
            raise CalDAVError("Not connected to CalDAV")

        ics_content = self._create_ics(event, event_id)

        try:
            existing = self._calendar.event(event_id)
            existing.edit(ics_content)
            logger.info(f"Updated calendar event: {event_id}")
        except NotFoundError:
            self.create_event(event, event_id)
        except Exception as e:
            logger.error(f"Failed to update calendar event: {e}")
            raise CalDAVError(f"Failed to update event: {e}") from e

    def delete_event(self, event_id: str) -> None:
        if not self._calendar:
            raise CalDAVError("Not connected to CalDAV")

        try:
            event = self._calendar.event(event_id)
            event.delete()
            logger.info(f"Deleted calendar event: {event_id}")
        except NotFoundError:
            logger.warning(f"Event not found: {event_id}")
        except Exception as e:
            logger.error(f"Failed to delete calendar event: {e}")
            raise CalDAVError(f"Failed to delete event: {e}") from e

    def _create_ics(self, event: CalendarEvent, uid: str | None = None) -> str:
        import time

        uid = uid or f"mail_events_to_caldav-{time.time()}"

        if not event.start_time:
            raise CalDAVError("Cannot create event without start_time")

        if event.all_day:
            dtstart = "DTSTART;VALUE=DATE:" + event.start_time.strftime("%Y%m%d")
            if event.end_time:
                dtend = "DTEND;VALUE=DATE:" + event.end_time.strftime("%Y%m%d")
            else:
                dtend = "DTEND;VALUE=DATE:" + (
                    event.start_time + timedelta(days=1)
                ).strftime("%Y%m%d")
        else:
            dtstart = "DTSTART:" + event.start_time.strftime("%Y%m%dT%H%M%S") + "Z"
            if event.end_time:
                dtend = "DTEND:" + event.end_time.strftime("%Y%m%dT%H%M%S") + "Z"
            else:
                dtend = (
                    "DTEND:"
                    + (event.start_time + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
                    + "Z"
                )

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//mail_events_to_caldav//EN",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
            "UID:" + uid,
            dtstart,
            dtend,
            "SUMMARY:" + self._escape_ics_text(event.title),
        ]

        if event.location:
            lines.append("LOCATION:" + self._escape_ics_text(event.location))

        if event.description:
            lines.append("DESCRIPTION:" + self._escape_ics_text(event.description))

        lines.extend(
            [
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        )

        return "\r\n".join(lines)

    def _escape_ics_text(self, text: str) -> str:
        if not text:
            return ""
        text = text.replace("\\", "\\\\")
        text = text.replace(",", "\\,")
        text = text.replace(";", "\\;")
        text = text.replace("\n", "\\n")
        text = text.replace("\r", "")
        text = text.replace("<", "\\<")
        text = text.replace(">", "\\>")
        return text

    def _format_ics_datetime(
        self,
        dt: datetime | None,
        all_day: bool,
        offset_hours: int = 0,
        offset_days: int = 0,
    ) -> str:
        if not dt:
            return ""
        if offset_hours:
            dt = dt.replace(hour=dt.hour + offset_hours)
        if offset_days:
            dt = dt.replace(day=dt.day + offset_days)
        if all_day:
            return dt.strftime("%Y%m%d")
        return dt.strftime("%Y%m%dT%H%M%SZ")

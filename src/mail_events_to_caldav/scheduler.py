"""Polling scheduler for checking emails periodically."""

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mail_events_to_caldav.caldav_client import CalDAVClient, CalDAVConfig
from mail_events_to_caldav.database import Email, async_session
from mail_events_to_caldav.filter import EmailFilter, FilterConfig
from mail_events_to_caldav.imap_client import EmailMessage, IMAPClient, IMAPConfig
from mail_events_to_caldav.llm_parser import (
    CalendarEvent,
    LLMConfig,
    LLMParser,
    events_to_dict_list,
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessingConfig:
    auto_create: bool = True
    update_existing: bool = True
    delete_rejected: bool = False
    grace_period_minutes: int = 0


@dataclass
class SchedulerConfig:
    check_interval_minutes: int = 5
    active_hours_start: int | None = None
    active_hours_end: int | None = None


class Poller:
    def __init__(
        self,
        imap_config: IMAPConfig,
        filter_config: FilterConfig,
        llm_config: LLMConfig | None,
        caldav_config: CalDAVConfig | None,
        processing_config: ProcessingConfig,
        scheduler_config: SchedulerConfig,
    ):
        self.imap_config = imap_config
        self.filter_config = filter_config
        self.llm_config = llm_config
        self.caldav_config = caldav_config
        self.processing_config = processing_config
        self.scheduler_config = scheduler_config

        self._imap_client: IMAPClient | None = None
        self._llm_parser: LLMParser | None = None
        self._caldav_client: CalDAVClient | None = None
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Poller started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._disconnect_imap()
        if self._llm_parser:
            await self._llm_parser.close()
        if self._caldav_client:
            self._caldav_client.disconnect()
        logger.info("Poller stopped")

    async def _ensure_imap_connected(self) -> None:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if self._imap_client is None:
                    self._imap_client = IMAPClient(self.imap_config)
                    await asyncio.to_thread(self._imap_client.connect)
                    return
                else:
                    await asyncio.to_thread(self._imap_client._mailbox.noop)
                    return
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"IMAP connection attempt {attempt + 1} failed: {e}. Retrying..."
                    )
                    await self._disconnect_imap()
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    logger.error(
                        f"IMAP connection failed after {max_retries} attempts: {e}"
                    )
                    raise

    async def _disconnect_imap(self) -> None:
        if self._imap_client:
            try:
                self._imap_client.disconnect()
            except Exception:
                pass
            self._imap_client = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._check_and_process()
                if self.processing_config.grace_period_minutes > 0:
                    await self._process_grace_period_emails()
                if self.processing_config.delete_rejected:
                    await self._process_rejected_emails()
            except Exception as e:
                logger.error(f"Error in poller loop: {e}")

            await asyncio.sleep(self.scheduler_config.check_interval_minutes * 60)

    async def process_now(self) -> dict:
        try:
            await self._check_and_process()
            return {"success": True, "message": "Processing triggered"}
        except Exception as e:
            logger.error(f"Error in manual processing: {e}")
            return {"success": False, "error": str(e)}

    async def _check_and_process(self) -> None:
        if not self._is_within_active_hours():
            logger.debug("Outside active hours, skipping check")
            return

        logger.info("Checking for new emails...")

        folders = (
            self.filter_config.folders if self.filter_config.folders else ["INBOX"]
        )

        await self._ensure_imap_connected()

        email_filter = EmailFilter(self.filter_config)

        all_emails: list[EmailMessage] = []
        for folder in folders:
            emails = await asyncio.to_thread(
                self._imap_client.fetch_emails,
                folder=folder,
                keywords=self.filter_config.keywords,
                senders=self.filter_config.senders,
                recipients=self.filter_config.recipients,
                unread_only=self.filter_config.unread_only,
                include_attachments=self.filter_config.include_attachments,
                date_since_days=self.filter_config.date_since_days,
            )
            all_emails.extend(emails)

        if self.llm_config:
            self._llm_parser = LLMParser(self.llm_config)

        if self.caldav_config:
            self._caldav_client = CalDAVClient(self.caldav_config)
            self._caldav_client.connect()

        try:
            logger.info(f"Found {len(all_emails)} emails to process")
            for email in all_emails:
                att_text = ""
                if email.attachment_texts:
                    att_text = f", {len(email.attachment_texts)} attachments ({sum(len(t) for t in email.attachment_texts)} chars)"
                subject = (email.subject or "")[:40]
                logger.info(
                    f"  Email: {subject}... (has_attachments={email.has_attachments}{att_text})"
                )
                await self._process_email(email, email_filter)
        finally:
            if self._llm_parser:
                await self._llm_parser.close()
                self._llm_parser = None
            if self._caldav_client:
                self._caldav_client.disconnect()
                self._caldav_client = None

    async def _process_email(
        self, email: EmailMessage, email_filter: EmailFilter
    ) -> None:
        if not email_filter.should_process(email):
            subject = (email.subject or "")[:40]
            logger.info(f"Email filtered out by filter: {subject}")
            return

        async with async_session() as session:
            existing = await self._get_existing_email(session, email.message_id)
            if existing and existing.status not in (
                "llm_error",
                "caldav_error",
                "rejected",
                "pending",
            ):
                subject = (email.subject or "")[:40]
                logger.info(
                    f"Email already processed successfully, skipping: {subject}"
                )
                return

            await self._save_email(session, email)
            subject = (email.subject or "")[:40]
            logger.info(f"Processing email: {subject}...")

            if self.llm_config:
                await self._process_with_llm(session, email)
            else:
                logger.warning("LLM not configured, skipping parsing")

    async def _process_with_llm(
        self, session: AsyncSession, email: EmailMessage
    ) -> None:
        if not self.llm_config or not self._llm_parser:
            return

        try:
            attachment_text = ""
            if email.attachment_texts:
                attachment_text = "\n\n[Attachments]:\n" + "\n\n".join(
                    email.attachment_texts
                )
                logger.info(f"PDF attachment text length: {len(attachment_text)} chars")

            logger.info(f"Email body text length: {len(email.body_text or '')} chars")

            combined_body = (email.body_text or "") + attachment_text
            subject = (email.subject or "")[:50]
            logger.info(
                f"Sending to LLM - subject: {subject}..., body length: {len(combined_body)}"
            )
            if "Ticket" in email.subject:
                logger.info(f"FULL BODY for Ticket: {combined_body[:1000]}...")

            events = await self._llm_parser.parse_event(
                email_subject=email.subject,
                email_body=combined_body,
            )

            await self._update_email_with_events(session, email.message_id, events)

            if self.processing_config.auto_create and self.caldav_config:
                await self._create_calendar_events(session, email.message_id, events)

            if (
                not self.processing_config.auto_create
                and self.processing_config.grace_period_minutes > 0
            ):
                logger.info(
                    f"Auto-create disabled, waiting {self.processing_config.grace_period_minutes}min grace period"
                )

        except Exception as e:
            logger.error(f"LLM parsing failed for {email.message_id}: {e}")
            await self._update_email_status(session, email.message_id, "llm_error")

    async def _create_calendar_events(
        self, session: AsyncSession, message_id: str, events: list[CalendarEvent]
    ) -> None:
        if not self.caldav_config or not self._caldav_client:
            return

        existing_email = await self._get_existing_email(session, message_id)
        existing_caldav_ids = (
            existing_email.caldav_event_id.split(",")
            if existing_email and existing_email.caldav_event_id
            else []
        )

        created_ids = []
        try:
            for i, event in enumerate(events):
                if (
                    self.processing_config.update_existing
                    and i < len(existing_caldav_ids)
                    and existing_caldav_ids[i]
                ):
                    existing_id = existing_caldav_ids[i]
                    try:
                        self._caldav_client.update_event(existing_id, event)
                        created_ids.append(str(existing_id))
                        logger.info(f"Updated calendar event: {existing_id}")
                    except Exception as e:
                        logger.warning(
                            f"Failed to update event {existing_id}, creating new: {e}"
                        )
                        event_id = self._caldav_client.create_event(event)
                        if event_id:
                            created_ids.append(str(event_id))
                else:
                    event_id = self._caldav_client.create_event(event)
                    if event_id:
                        created_ids.append(str(event_id))

            if created_ids:
                await self._update_caldav_event_id(
                    session, message_id, ",".join(created_ids)
                )
                await self._update_email_status(session, message_id, "created")
            else:
                await self._update_email_status(session, message_id, "caldav_error")
        except Exception as e:
            logger.error(f"Failed to create calendar events: {e}")
            await self._update_email_status(session, message_id, "caldav_error")

    def _is_within_active_hours(self) -> bool:
        if not self.scheduler_config.active_hours_start:
            return True
        current_hour = datetime.now().hour
        start = self.scheduler_config.active_hours_start
        end = self.scheduler_config.active_hours_end or 23
        return start <= current_hour <= end

    async def _get_existing_email(
        self, session: AsyncSession, message_id: str
    ) -> Email | None:
        result = await session.execute(
            select(Email).where(Email.message_id == message_id)
        )
        return result.scalar_one_or_none()

    async def _save_email(self, session: AsyncSession, email: EmailMessage) -> Email:
        existing = await self._get_existing_email(session, email.message_id)
        if existing:
            existing.subject = email.subject
            existing.sender = email.sender
            existing.recipient = email.recipient
            existing.date = email.date
            existing.body_text = email.body_text
            existing.body_html = email.body_html
            existing.has_attachments = email.has_attachments
            existing.status = "pending"
            existing.processed_at = datetime.utcnow()
            existing.event_data = None
            existing.llm_response = None
            existing.caldav_event_id = None
            await session.commit()
            return existing

        db_email = Email(
            message_id=email.message_id,
            subject=email.subject,
            sender=email.sender,
            recipient=email.recipient,
            date=email.date,
            body_text=email.body_text,
            body_html=email.body_html,
            has_attachments=email.has_attachments,
            status="pending",
            processed_at=datetime.utcnow(),
        )
        session.add(db_email)
        await session.commit()
        return db_email

    async def _update_email_with_event(
        self, session: AsyncSession, message_id: str, event: CalendarEvent
    ) -> None:
        await session.execute(
            update(Email)
            .where(Email.message_id == message_id)
            .values(
                status="parsed",
                event_data=asdict(event),
            )
        )
        await session.commit()

    async def _update_email_with_events(
        self, session: AsyncSession, message_id: str, events: list[CalendarEvent]
    ) -> None:
        await session.execute(
            update(Email)
            .where(Email.message_id == message_id)
            .values(
                status="parsed",
                event_data=events_to_dict_list(events),
            )
        )
        await session.commit()

    async def _update_email_status(
        self, session: AsyncSession, message_id: str, status: str
    ) -> None:
        await session.execute(
            update(Email).where(Email.message_id == message_id).values(status=status)
        )
        await session.commit()

    async def _update_caldav_event_id(
        self, session: AsyncSession, message_id: str, event_id: str | None
    ) -> None:
        await session.execute(
            update(Email)
            .where(Email.message_id == message_id)
            .values(caldav_event_id=event_id)
        )
        await session.commit()

    async def _process_grace_period_emails(self) -> None:
        if not self.caldav_config or not self.processing_config.auto_create:
            return

        async with async_session() as session:
            grace_threshold = datetime.now(UTC) - timedelta(
                minutes=self.processing_config.grace_period_minutes
            )
            result = await session.execute(
                select(Email).where(
                    Email.status == "parsed",
                    Email.processed_at <= grace_threshold,
                )
            )
            emails = result.scalars().all()

            if emails:
                logger.info(f"Processing {len(emails)} emails after grace period")

                self._caldav_client = CalDAVClient(self.caldav_config)
                self._caldav_client.connect()

                try:
                    for email in emails:
                        if email.event_data:
                            events = self._event_data_to_events(email.event_data)
                            await self._create_calendar_events(
                                session, email.message_id, events
                            )
                finally:
                    self._caldav_client.disconnect()

    async def _process_rejected_emails(self) -> None:
        if not self.caldav_config:
            return

        async with async_session() as session:
            result = await session.execute(
                select(Email).where(Email.status == "rejected")
            )
            emails = result.scalars().all()

            if emails:
                logger.info(f"Deleting {len(emails)} rejected calendar events")

                self._caldav_client = CalDAVClient(self.caldav_config)
                self._caldav_client.connect()

                try:
                    for email in emails:
                        if email.caldav_event_id:
                            for event_id in email.caldav_event_id.split(","):
                                try:
                                    self._caldav_client.delete_event(event_id.strip())
                                except Exception as e:
                                    logger.warning(
                                        f"Failed to delete event {event_id}: {e}"
                                    )
                            await session.delete(email)
                            await session.commit()
                finally:
                    self._caldav_client.disconnect()

    def _event_data_to_events(self, event_data: list | dict) -> list[CalendarEvent]:
        if isinstance(event_data, list):
            events = []
            for ed in event_data:
                events.append(
                    CalendarEvent(
                        title=ed.get("title", "Untitled"),
                        start_time=ed.get("start_time"),
                        end_time=ed.get("end_time"),
                        location=ed.get("location"),
                        description=ed.get("description"),
                        all_day=ed.get("all_day", False),
                        task=ed.get("task", False),
                    )
                )
            return events
        return [
            CalendarEvent(
                title=event_data.get("title", "Untitled"),
                start_time=event_data.get("start_time"),
                end_time=event_data.get("end_time"),
                location=event_data.get("location"),
                description=event_data.get("description"),
                all_day=event_data.get("all_day", False),
                task=event_data.get("task", False),
            )
        ]

"""Database models and session management."""

import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mail_events_to_caldav.config import settings

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("PCB_DATABASE_URL", settings.database_url)
logger.info(f"Database URL: {DATABASE_URL}")

if DATABASE_URL == "sqlite+aiosqlite:///:memory:":
    logger.warning("Using in-memory database!")


class Base(DeclarativeBase):
    pass


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(1000))
    sender: Mapped[str] = mapped_column(String(500))
    recipient: Mapped[str | None] = mapped_column(String(500), nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    llm_response: Mapped[JSON | None] = mapped_column(JSON, nullable=True)
    event_data: Mapped[JSON | None] = mapped_column(JSON, nullable=True)
    caldav_event_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)


class Config(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


CURRENT_SCHEMA_VERSION = 1


engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_migrations()


async def get_schema_version() -> int:
    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(SchemaVersion).order_by(SchemaVersion.version.desc())
        )
        latest = result.scalar_one_or_none()
        return latest.version if latest else 0


async def _run_migrations() -> None:
    current_version = await get_schema_version()

    if current_version < CURRENT_SCHEMA_VERSION:
        logger.info(
            f"Running migrations from version {current_version} to {CURRENT_SCHEMA_VERSION}"
        )

    for version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        await _apply_migration(version)


async def _apply_migration(version: int) -> None:
    logger.info(f"Applying migration version {version}")
    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(SchemaVersion).where(SchemaVersion.version == version)
        )
        existing = result.scalar_one_or_none()

        if existing:
            return

        session.add(SchemaVersion(version=version))
        await session.commit()
        logger.info(f"Migration version {version} applied")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session

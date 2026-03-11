"""FastAPI application with web UI and API endpoints."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mail_events_to_caldav.caldav_client import CalDAVClient, CalDAVConfig
from mail_events_to_caldav.config import settings
from mail_events_to_caldav.config_manager import ConfigManager
from mail_events_to_caldav.config_service import (
    build_caldav_config,
    build_filter_config,
    build_imap_config,
    build_llm_config,
    build_processing_config,
    build_scheduler_config,
    ensure_events_times,
)
from mail_events_to_caldav.database import Email, async_session, init_db
from mail_events_to_caldav.filter import EmailFilter
from mail_events_to_caldav.imap_client import IMAPClient, IMAPConfig
from mail_events_to_caldav.imap_client import IMAPConnectionError
from mail_events_to_caldav.llm_parser import (
    CalendarEvent,
    LLMConfig,
    LLMParser,
    events_to_dict_list,
)
from mail_events_to_caldav.scheduler import Poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logging.getLogger().setLevel(getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)


class AppState:
    poller: Poller | None = None
    restart_task: asyncio.Task | None = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")
    yield
    if app_state.poller:
        await app_state.poller.stop()


app = FastAPI(title="mail_events_to_caldav", lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent.parent.parent / "templates")


class ConfigUpdate(BaseModel):
    section: str
    values: dict


class TestParseRequest(BaseModel):
    subject: str
    body: str


class TestIMAPRequest(BaseModel):
    host: str
    port: int
    username: str
    password: str
    use_ssl: bool = True


class TestLLMRequest(BaseModel):
    provider: str
    api_key: str
    model: str
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1000


class TestCalDAVRequest(BaseModel):
    server_url: str
    username: str
    password: str
    verify_ssl: bool = True


async def get_session():
    async with async_session() as session:
        yield session


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    config = await ConfigManager.get_config()
    return templates.TemplateResponse(
        "index.html", {"request": request, "config": config}
    )


@app.get("/api/config")
async def get_config():
    return await ConfigManager.get_config()


@app.put("/api/config")
async def update_config(update: ConfigUpdate):
    await ConfigManager.set_config_section(update.section, update.values)
    await restart_poller()
    return {"status": "ok"}


@app.get("/api/history")
async def get_history(limit: int = 100, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Email).order_by(Email.processed_at.desc()).limit(limit)
    )
    emails = result.scalars().all()
    return [
        {
            "id": e.id,
            "message_id": e.message_id,
            "subject": e.subject,
            "sender": e.sender,
            "date": e.date.isoformat() if e.date else None,
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
            "status": e.status,
            "event_data": e.event_data,
            "llm_response": e.llm_response,
            "caldav_event_id": e.caldav_event_id,
        }
        for e in emails
    ]


@app.delete("/api/history/{email_id}")
async def delete_history(email_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if email:
        await session.delete(email)
        await session.commit()
    return {"status": "ok"}


async def _parse_email_with_llm(
    subject: str,
    body_text: str,
    config: dict,
) -> tuple[list[CalendarEvent] | None, dict]:
    llm_config = build_llm_config(config)
    if not llm_config:
        return None, {"error": "LLM not configured"}

    parser = LLMParser(llm_config)
    try:
        events = await parser.parse_event(
            email_subject=subject,
            email_body=body_text,
        )
        return events, {"parsed": True}
    except Exception as e:
        return None, {"error": str(e)}
    finally:
        await parser.close()


async def _create_caldav_event(
    event: CalendarEvent,
    config: dict,
) -> tuple[str | None, str]:
    caldav_config = build_caldav_config(config)
    if not caldav_config:
        return None, "caldav_not_configured"

    client = CalDAVClient(caldav_config)
    client.connect()
    try:
        event_id = client.create_event(event)
        return str(event_id) if event_id else None, "created"
    except Exception as e:
        return None, str(e)
    finally:
        client.disconnect()


@app.post("/api/history/{email_id}/reprocess")
async def reprocess_email(email_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if not email:
        return {"success": False, "error": "Email not found"}

    config = await ConfigManager.get_config()

    email.status = "pending"
    await session.commit()

    events, llm_response = await _parse_email_with_llm(
        subject=email.subject,
        body_text=email.body_text or "",
        config=config,
    )

    if not events:
        email.status = "llm_error"
        email.llm_response = llm_response
        await session.commit()
        return {
            "success": False,
            "error": llm_response.get("error", "LLM parsing failed"),
        }

    email.event_data = events_to_dict_list(events)
    email.llm_response = llm_response

    events = ensure_events_times(events)

    created_ids = []
    errors = []
    for event in events:
        event_id, status = await _create_caldav_event(event, config)
        if event_id:
            created_ids.append(event_id)
        else:
            errors.append(status)

    if created_ids:
        email.caldav_event_id = ",".join(str(id) for id in created_ids)
        email.status = "created"
    elif errors and "caldav_not_configured" in errors:
        email.status = "caldav_not_configured"
    else:
        email.status = "caldav_error"
        email.llm_response["caldav_errors"] = errors

    await session.commit()
    await session.refresh(email)
    return {
        "success": True,
        "status": email.status,
        "event_data": email.event_data,
        "llm_response": email.llm_response,
    }


@app.post("/api/history/clear")
async def clear_history(session: AsyncSession = Depends(get_session)):
    await session.execute(delete(Email))
    await session.commit()
    return {"status": "ok"}


@app.get("/api/emails/preview")
async def preview_emails():
    try:
        config = await ConfigManager.get_config()

        imap_config = build_imap_config(config)
        filter_config = build_filter_config(config)

        client = IMAPClient(imap_config)
        client.connect()

        folders = filter_config.folders if filter_config.folders else ["INBOX"]
        all_emails = []

        for folder in folders:
            emails = client.fetch_emails(
                folder=folder,
                keywords=filter_config.keywords,
                senders=filter_config.senders,
                recipients=filter_config.recipients,
                unread_only=filter_config.unread_only,
                include_attachments=filter_config.include_attachments,
                date_since_days=filter_config.date_since_days,
            )
            all_emails.extend(emails)

        client.disconnect()

        email_filter = EmailFilter(filter_config)
        filtered_emails = [e for e in all_emails if email_filter.should_process(e)]

        return [
            {
                "message_id": e.message_id,
                "subject": e.subject,
                "sender": e.sender,
                "date": e.date.isoformat() if e.date else None,
            }
            for e in filtered_emails
        ]
    except IMAPConnectionError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e).encode("utf-8", errors="replace").decode("utf-8"),
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e).encode("utf-8", errors="replace").decode("utf-8"),
        )


@app.post("/api/emails/process-now")
async def process_now():
    if not app_state.poller:
        config = await ConfigManager.get_config()

        imap_config = build_imap_config(config)
        filter_config = build_filter_config(config)
        llm_config = build_llm_config(config)
        caldav_config = build_caldav_config(config)
        processing_config = build_processing_config(config)
        scheduler_config = build_scheduler_config(config)

        app_state.poller = Poller(
            imap_config=imap_config,
            filter_config=filter_config,
            llm_config=llm_config,
            caldav_config=caldav_config,
            processing_config=processing_config,
            scheduler_config=scheduler_config,
        )

    result = await app_state.poller.process_now()
    return result


@app.post("/api/emails/test-parse")
async def test_parse_email(req: TestParseRequest):
    config = await ConfigManager.get_config()
    llm_config = build_llm_config(config)

    if not llm_config:
        raise HTTPException(status_code=400, detail="LLM API key not configured")

    events, llm_response = await _parse_email_with_llm(
        subject=req.subject,
        body_text=req.body,
        config=config,
    )

    if not events:
        return {"success": False, "error": llm_response.get("error", "Parsing failed")}

    return {
        "success": True,
        "events": [
            {
                "title": e.title,
                "start_time": e.start_time.isoformat() if e.start_time else None,
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "location": e.location,
                "description": e.description,
                "all_day": e.all_day,
                "task": e.task,
            }
            for e in events
        ],
    }


@app.post("/api/test/imap")
async def test_imap_connection(req: TestIMAPRequest):
    try:
        imap_config = IMAPConfig(
            host=req.host,
            port=req.port,
            username=req.username,
            password=req.password,
            use_ssl=req.use_ssl,
        )
        client = IMAPClient(imap_config)
        client.connect()

        folders = client.get_folders()
        client.disconnect()

        return {
            "success": True,
            "message": f"Connected successfully! Found {len(folders)} folders.",
            "folders": [
                {"name": f.name, "flags": list(f.flags) if f.flags else []}
                for f in folders[:10]
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/imap/folders")
async def get_imap_folders(req: TestIMAPRequest):
    try:
        imap_config = IMAPConfig(
            host=req.host,
            port=req.port,
            username=req.username,
            password=req.password,
            use_ssl=req.use_ssl,
        )
        client = IMAPClient(imap_config)
        client.connect()

        folders = client.get_folders()
        client.disconnect()

        return {
            "success": True,
            "folders": [
                {"name": f.name, "flags": list(f.flags) if f.flags else []}
                for f in folders
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/presets")
async def get_presets():
    from mail_events_to_caldav.config_manager import PRESETS

    return {"presets": PRESETS}


class ApplyPresetRequest(BaseModel):
    preset_keys: list[str]


@app.post("/api/presets/apply")
async def apply_preset(req: ApplyPresetRequest):
    from mail_events_to_caldav.config_manager import PRESETS, ConfigManager

    all_keywords = []
    all_keywords_regex = []

    for preset_key in req.preset_keys:
        if preset_key in PRESETS:
            preset = PRESETS[preset_key]
            all_keywords.extend(preset.get("keywords", []))
            all_keywords_regex.extend(preset.get("keywords_regex", []))

    all_keywords = list(set(all_keywords))
    all_keywords_regex = list(set(all_keywords_regex))

    current_config = await ConfigManager.get_config()
    current_keywords = current_config.get("filter", {}).get("keywords", [])
    current_keywords_regex = current_config.get("filter", {}).get("keywords_regex", [])

    combined_keywords = list(set(current_keywords + all_keywords))
    combined_keywords_regex = list(set(current_keywords_regex + all_keywords_regex))

    return {
        "success": True,
        "keywords": combined_keywords,
        "keywords_regex": combined_keywords_regex,
    }


@app.post("/api/test/llm")
async def test_llm_connection(req: TestLLMRequest):
    parser: LLMParser | None = None
    try:
        llm_config = LLMConfig(
            provider=req.provider,
            api_key=req.api_key,
            model=req.model,
            base_url=req.base_url,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            system_prompt="You are a test assistant. Return 'OK' if you receive this message.",
        )
        parser = LLMParser(llm_config)

        await parser.parse_event("Test email", "This is a test message.")
        await parser.close()

        return {
            "success": True,
            "message": "LLM connection successful!",
            "model": req.model,
        }
    except Exception as e:
        if parser:
            try:
                await parser.close()
            except Exception:
                pass
        return {"success": False, "error": str(e)}


class FetchModelsRequest(BaseModel):
    provider: str
    api_key: str
    base_url: str | None = None


@app.post("/api/llm/models")
async def fetch_models(req: FetchModelsRequest):
    import httpx

    base_url = req.base_url or ""
    headers = {"Authorization": f"Bearer {req.api_key}"}

    try:
        if req.provider == "openai":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers=headers,
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                return {"success": True, "models": models}
        elif req.provider == "anthropic":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": req.api_key},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                return {"success": True, "models": models}
        elif req.provider == "ollama":
            url = base_url or "http://localhost:11434"
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{url}/api/tags", timeout=30.0)
                resp.raise_for_status()
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
                return {"success": True, "models": models}
        elif req.provider == "openai-compatible":
            if not base_url:
                raise HTTPException(
                    status_code=400,
                    detail="Base URL required for OpenAI-compatible provider",
                )
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{base_url}/api/v1/models",
                    headers={"Authorization": f"Bearer {req.api_key}"}
                    if req.api_key
                    else {},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                return {"success": True, "models": models}
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported provider: {req.provider}"
            )
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP error: {e.response.status_code} - {e.response.text}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/test/caldav")
async def test_caldav_connection(req: TestCalDAVRequest):
    try:
        caldav_config = CalDAVConfig(
            server_url=req.server_url,
            username=req.username,
            password=req.password,
            calendar_id="",
            verify_ssl=req.verify_ssl,
        )
        client = CalDAVClient(caldav_config)
        client.connect()

        calendars = client.get_calendars()
        client.disconnect()

        return {
            "success": True,
            "message": f"Connected successfully! Found {len(calendars)} calendars.",
            "calendars": [{"id": c["id"], "name": c["name"]} for c in calendars],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/calendars")
async def fetch_calendars():
    config = await ConfigManager.get_config()
    caldav_data = config.get("caldav", {})

    if not caldav_data.get("server_url"):
        raise HTTPException(status_code=400, detail="CalDAV server URL not configured")

    caldav_config = CalDAVConfig(
        server_url=caldav_data.get("server_url", ""),
        username=caldav_data.get("username", ""),
        password=caldav_data.get("password", ""),
        calendar_id=caldav_data.get("calendar_id", ""),
        verify_ssl=caldav_data.get("verify_ssl", True),
    )

    client = CalDAVClient(caldav_config)
    client.connect()

    try:
        calendars = client.get_calendars()
        return calendars
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        client.disconnect()


@app.post("/api/config/export")
async def export_config():
    config = await ConfigManager.export_config()
    return config


@app.post("/api/config/import")
async def import_config(config: dict):
    await ConfigManager.import_config(config)
    await restart_poller()
    return {"status": "ok"}


@app.post("/api/config/reset")
async def reset_config():
    await ConfigManager.clear_config()
    await restart_poller()
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


async def _do_restart_poller():
    if app_state.poller:
        await app_state.poller.stop()

    config = await ConfigManager.get_config()

    imap_config = build_imap_config(config)
    filter_config = build_filter_config(config)
    llm_config = build_llm_config(config)
    caldav_config = build_caldav_config(config)
    processing_config = build_processing_config(config)
    scheduler_config = build_scheduler_config(config)

    app_state.poller = Poller(
        imap_config=imap_config,
        filter_config=filter_config,
        llm_config=llm_config,
        caldav_config=caldav_config,
        processing_config=processing_config,
        scheduler_config=scheduler_config,
    )

    await app_state.poller.start()


async def restart_poller():
    if app_state.restart_task:
        app_state.restart_task.cancel()
        try:
            await app_state.restart_task
        except asyncio.CancelledError:
            pass

    async def delayed_restart():
        await asyncio.sleep(2)
        await _do_restart_poller()

    app_state.restart_task = asyncio.create_task(delayed_restart())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)

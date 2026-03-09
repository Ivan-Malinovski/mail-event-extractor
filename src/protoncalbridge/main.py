"""FastAPI application with web UI and API endpoints."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from protoncalbridge.caldav_client import CalDAVClient, CalDAVConfig
from protoncalbridge.config import settings
from protoncalbridge.config_manager import ConfigManager
from protoncalbridge.database import Email, async_session, init_db
from protoncalbridge.imap_client import IMAPClient, IMAPConfig
from protoncalbridge.llm_parser import LLMConfig, LLMParser
from protoncalbridge.scheduler import FilterConfig, Poller, ProcessingConfig

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

poller: Poller | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poller
    await init_db()
    logger.info("Database initialized")
    yield
    if poller:
        await poller.stop()


app = FastAPI(title="ProtonCalBridge", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


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
    return templates.TemplateResponse("index.html", {"request": request, "config": config})


@app.get("/api/config")
async def get_config():
    return await ConfigManager.get_config()


@app.put("/api/config")
async def update_config(update: ConfigUpdate):
    await ConfigManager.set_config_section(update.section, update.values)
    await restart_poller()
    return {"status": "ok"}


@app.get("/api/history")
async def get_history(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Email).order_by(Email.processed_at.desc()).limit(100)
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


@app.post("/api/history/clear")
async def clear_history(session: AsyncSession = Depends(get_session)):
    await session.execute(delete(Email))
    await session.commit()
    return {"status": "ok"}


@app.get("/api/emails/preview")
async def preview_emails():
    config = await ConfigManager.get_config()

    imap_config = IMAPConfig(
        host=config.get("imap", {}).get("host", "127.0.0.1"),
        port=config.get("imap", {}).get("port", 1143),
        username=config.get("imap", {}).get("username", ""),
        password=config.get("imap", {}).get("password", ""),
        use_ssl=config.get("imap", {}).get("use_ssl", True),
    )

    filter_config = FilterConfig(
        folders=config.get("filter", {}).get("folders", ["INBOX"]),
        keywords=config.get("filter", {}).get("keywords", []),
        keywords_regex=config.get("filter", {}).get("keywords_regex", []),
        senders=config.get("filter", {}).get("senders", []),
        senders_regex=config.get("filter", {}).get("senders_regex", []),
        recipients=config.get("filter", {}).get("recipients", []),
        recipients_regex=config.get("filter", {}).get("recipients_regex", []),
        include_attachments=config.get("filter", {}).get("include_attachments", False),
        unread_only=config.get("filter", {}).get("unread_only", True),
        date_since_days=config.get("filter", {}).get("date_since_days"),
    )

    client = IMAPClient(imap_config)
    client.connect()

    emails = client.fetch_emails(
        folder=filter_config.folders[0] if filter_config.folders else "INBOX",
        keywords=filter_config.keywords,
        senders=filter_config.senders,
        recipients=filter_config.recipients,
        unread_only=filter_config.unread_only,
        include_attachments=filter_config.include_attachments,
        date_since_days=filter_config.date_since_days,
    )

    client.disconnect()

    return [
        {
            "message_id": e.message_id,
            "subject": e.subject,
            "sender": e.sender,
            "date": e.date.isoformat() if e.date else None,
        }
        for e in emails
    ]


@app.post("/api/emails/test-parse")
async def test_parse_email(req: TestParseRequest):
    config = await ConfigManager.get_config()
    llm_config_data = config.get("llm", {})

    if not llm_config_data.get("api_key"):
        raise HTTPException(status_code=400, detail="LLM API key not configured")

    llm_config = LLMConfig(
        provider=llm_config_data.get("provider", "openai"),
        api_key=llm_config_data.get("api_key", ""),
        model=llm_config_data.get("model", "gpt-4o-mini"),
        base_url=llm_config_data.get("base_url"),
        temperature=llm_config_data.get("temperature", 0.0),
        max_tokens=llm_config_data.get("max_tokens", 1000),
        system_prompt=llm_config_data.get("system_prompt", ""),
    )

    parser = LLMParser(llm_config)
    try:
        event = await parser.parse_event(req.subject, req.body)
        return {
            "success": True,
            "event": {
                "title": event.title,
                "start_time": event.start_time.isoformat() if event.start_time else None,
                "end_time": event.end_time.isoformat() if event.end_time else None,
                "location": event.location,
                "description": event.description,
                "all_day": event.all_day,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await parser.close()


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
            "folders": [{"name": f.name, "flags": list(f.flags) if f.flags else []} for f in folders[:10]]
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
            "folders": [{"name": f.name, "flags": list(f.flags) if f.flags else []} for f in folders]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/presets")
async def get_presets():
    from protoncalbridge.config_manager import PRESETS
    return {"presets": PRESETS}


class ApplyPresetRequest(BaseModel):
    preset_keys: list[str]


@app.post("/api/presets/apply")
async def apply_preset(req: ApplyPresetRequest):
    from protoncalbridge.config_manager import PRESETS, ConfigManager
    
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
            "calendars": [{"id": c["id"], "name": c["name"]} for c in calendars]
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


async def restart_poller():
    global poller
    if poller:
        await poller.stop()

    config = await ConfigManager.get_config()

    imap_data = config.get("imap", {})
    filter_data = config.get("filter", {})
    llm_data = config.get("llm", {})
    caldav_data = config.get("caldav", {})
    processing_data = config.get("processing", {})
    scheduler_data = config.get("scheduler", {})

    imap_config = IMAPConfig(
        host=imap_data.get("host", "127.0.0.1"),
        port=imap_data.get("port", 1143),
        username=imap_data.get("username", ""),
        password=imap_data.get("password", ""),
        use_ssl=imap_data.get("use_ssl", True),
    )

    filter_config = FilterConfig(
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

    llm_config = None
    if llm_data.get("api_key"):
        llm_config = LLMConfig(
            provider=llm_data.get("provider", "openai"),
            api_key=llm_data.get("api_key", ""),
            model=llm_data.get("model", "gpt-4o-mini"),
            base_url=llm_data.get("base_url"),
            temperature=llm_data.get("temperature", 0.0),
            max_tokens=llm_data.get("max_tokens", 1000),
            system_prompt=llm_data.get("system_prompt", ""),
        )

    caldav_config = None
    if caldav_data.get("server_url"):
        caldav_config = CalDAVConfig(
            server_url=caldav_data.get("server_url", ""),
            username=caldav_data.get("username", ""),
            password=caldav_data.get("password", ""),
            calendar_id=caldav_data.get("calendar_id", ""),
            verify_ssl=caldav_data.get("verify_ssl", True),
        )

    processing_config = ProcessingConfig(
        auto_create=processing_data.get("auto_create", True),
        update_existing=processing_data.get("update_existing", True),
        delete_rejected=processing_data.get("delete_rejected", False),
        grace_period_minutes=processing_data.get("grace_period_minutes", 0),
    )

    scheduler_config = type("SchedulerConfig", (), {
        "check_interval_minutes": scheduler_data.get("check_interval_minutes", 5),
        "active_hours_start": scheduler_data.get("active_hours_start"),
        "active_hours_end": scheduler_data.get("active_hours_end"),
    })()

    poller = Poller(
        imap_config=imap_config,
        filter_config=filter_config,
        llm_config=llm_config,
        caldav_config=caldav_config,
        processing_config=processing_config,
        scheduler_config=scheduler_config,
    )

    await poller.start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)

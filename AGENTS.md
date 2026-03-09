# AGENTS.md - ProtonCalBridge

## Project Overview

ProtonCalBridge is a self-hosted application that bridges Proton Bridge (IMAP) to CalDAV. It monitors email accounts for calendar-related content, uses an LLM to parse event details, and creates calendar events in a CalDAV server.

**Tech Stack**: Python, FastAPI, Docker

---

## Build / Lint / Test Commands

### Setup
```bash
# Using pip
pip install -r requirements.txt

# Using poetry (preferred)
poetry install
```

### Development
```bash
# Linting
ruff check .

# Format code
ruff format .

# Type checking
mypy .

# Run all tests
pytest

# Run single test
pytest tests/path/to/test_file.py::test_function_name
pytest -k "test_name_pattern"

# Run with coverage
pytest --cov=src --cov-report=html
```

### Docker
```bash
# Build image
docker build -t protoncalbridge .

# Run container
docker run -d -p 8080:8080 --env-file .env protoncalbridge

# Docker Compose
docker-compose up -d
```

---

## Code Style Guidelines

### General
- **Language**: Python 3.11+
- **Type hints**: Required for all functions and variables
- **Line length**: 88 characters (Black default)
- **Quotes**: Double quotes for strings, single for chars only

### Imports
Organize in this order (use `ruff check --select=I --fix`):
1. Standard library
2. Third-party packages
3. Local application imports

```python
# Correct order
import os
import logging
from datetime import datetime

import pydantic
import httpx
from fastapi import FastAPI

from protoncalbridge.config import Settings
from protoncalbridge.models import Event
```

### Naming Conventions
- **Variables/functions**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `SCREAMING_SNAKE_CASE`
- **Private members**: `_leading_underscore`

### Error Handling
- Use custom exception classes inheriting from `ProtonCalBridgeError`
- Never use bare `except:` - always catch specific exceptions
- Log errors with appropriate level before re-raising
- Return meaningful error responses in API

```python
class ProtonCalBridgeError(Exception):
    pass

class IMAPConnectionError(ProtonCalBridgeError):
    pass

# Good pattern:
try:
    await fetch_emails()
except IMAPConnectionError as e:
    logger.error(f"IMAP connection failed: {e}")
    raise
```

### Docstrings
Use Google-style docstrings:

```python
def parse_event(email: EmailMessage) -> CalendarEvent | None:
    """Parse an email to extract calendar event information.

    Args:
        email: The email message to parse.

    Returns:
        A CalendarEvent if one was found, None otherwise.

    Raises:
        LLMParseError: If the LLM fails to parse the event.
    """
```

---

## Architecture

```
┌─────────────┐     ┌──────────┐     ┌──────┐     ┌────────┐
│   IMAP      │────▶│  Filter  │────▶│ LLM  │────▶│ CalDAV │
│  (Proton)   │     │  Emails  │     │ Parse│     │ Server │
└─────────────┘     └──────────┘     └──────┘     └────────┘
                           │                           │
                           ▼                           ▼
                    ┌──────────────┐          ┌──────────────┐
                    │   History    │          │   Calendar   │
                    │   (SQLite)   │          │   Events     │
                    └──────────────┘          └──────────────┘
```

### Data Flow
1. **Poller** checks IMAP at configured intervals
2. **Filter** selects emails matching criteria
3. **LLM Parser** extracts event details (title, time, location, description)
4. **CalDAV Client** creates/pushes events to calendar
5. **Database** stores history, rejections, and processing state

---

## Configuration Options

All configuration is managed via web UI and stored in SQLite.

### 1. IMAP / Proton Bridge Settings
- **Host**: IMAP server hostname (e.g., `127.0.0.1`)
- **Port**: IMAP port (default: `1143`)
- **Username**: Full email address
- **Password**: App password or account password
- **Use SSL/TLS**: Toggle (default: True)

### 2. Email Search Filters
- **Labels/Folders**: Which folders to monitor (e.g., INBOX, Custom)
- **Keywords**: Subject/body must contain these keywords
- **Senders**: Email addresses to filter by sender
- **Recipients**: Filter by To/CC recipients
- **Include attachments**: Toggle (default: False)
- **Unread only**: Toggle (default: True)
- **Date range**: Optional - emails from last N days

### 3. Polling Schedule
- **Check interval**: Minutes between checks (default: 5)
- **Active hours**: Optional - only check during specific hours

### 4. LLM Settings
- **Provider**: OpenAI, Anthropic, Ollama, OpenAI-compatible
- **API Key**: Secret - stored encrypted
- **Model**: e.g., `gpt-4o-mini`, `claude-3-haiku`
- **Base URL**: For Ollama/custom endpoints
- **Temperature**: 0.0-1.0 (default: 0.0)
- **Max tokens**: Response limit
- **System prompt**: Customizable prompt (default provided)

**Default Prompt**:
```
You are an email calendar event parser. Extract calendar events from emails.
Return a JSON object with: title, start_time, end_time, location, description, all_day (boolean).
If no valid event found, return {"error": "no_event"}.
Times must be in ISO 8601 format.
```

### 5. CalDAV Settings
- **Server URL**: Full CalDAV server URL
- **Username**: CalDAV username
- **Password**: App password
- **Calendar**: Which calendar to write to (fetch list from server)
- **SSL/TLS verify**: Toggle (default: True)

### 6. Event Processing
- **Auto-create**: Toggle - create events automatically (default: True)
- **Update existing**: Toggle - update if event UID exists (default: True)
- **Delete rejected**: Toggle - remove events if rejected (default: False)
- **Grace period**: Minutes to wait before finalizing (default: 0)

### 7. Web UI Settings
- **Host**: Listen address (default: `0.0.0.0`)
- **Port**: Listen port (default: `8080`)
- **Authentication**: Enable password protection (default: False)
- **Password**: Web UI password (if enabled)

### 8. Time & Region
- **Timezone**: IANA timezone (e.g., `Europe/Stockholm`)
- **Time format**: 12h or 24h display

### 9. Logging
- **Log level**: DEBUG, INFO, WARNING, ERROR
- **Log retention**: Days to keep logs (default: 30)

### 10. Data Management
- **Export config**: Download all settings as JSON
- **Import config**: Restore settings from JSON
- **Clear history**: Delete all processing history
- **Reset**: Factory reset - clear all data

---

## API Endpoints (Internal)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | Get current configuration |
| PUT | `/api/config` | Update configuration |
| GET | `/api/emails/preview` | Preview which emails match filters |
| POST | `/api/emails/test-parse` | Test LLM parsing on specific email |
| GET | `/api/history` | List processed emails |
| DELETE | `/api/history/{id}` | Remove from history |
| POST | `/api/calendars` | Fetch available calendars |

---

## Database Schema

### Emails Table
- id, message_id, subject, sender, date, processed_at, status, llm_response, event_data, caldav_event_id

### Config Table
- key, value, updated_at

---

## Testing Strategy

- **Unit tests**: Test individual functions (parsers, filters)
- **Integration tests**: Test IMAP connection, CalDAV client
- **Fixtures**: Use mocks for LLM, IMAP, CalDAV in unit tests

---

## Docker Requirements

- Non-root user (UID 1000)
- Health check endpoint (`GET /health`)
- Volume for data persistence (`/data`)
- Environment variable support for secrets

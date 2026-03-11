# Mail Event Extractor

A self-hosted application that monitors email accounts for calendar-related content, uses an LLM to parse event details, and creates calendar events in a CalDAV server.

## ⚠️ DISCLAIMER: Entirely Vibe Coded

**This application was built through trial, error, and AI-assisted coding sessions. It works (mostly), but:**

- No comprehensive test suite
- Error handling is spotty at best
- The code may contain bugs, edge cases, and questionable design decisions
- LLM parsing quality varies and may miss events or extract incorrect data
- Use with a **separate calendar** from your primary calendar

**Use at your own risk. You've been warned.**

---

## How It Works

```
┌─────────────┐     ┌──────────┐     ┌──────┐     ┌────────┐
│   IMAP      │────▶│  Filter  │────▶│ LLM  │────▶│ CalDAV │
│  (any)      │     │  Emails  │     │ Parse│     │ Server │
└─────────────┘     └──────────┘     └──────┘     └────────┘
```

1. **Poller** checks IMAP at configured intervals
2. **Filter** selects emails matching criteria (keywords, senders, folders)
3. **LLM Parser** extracts event details (title, time, location)
4. **CalDAV Client** creates events in your calendar

---

## Features

- **IMAP Support**: Works with Proton Bridge or any IMAP server
- **Email Filtering**: Filter by keywords, senders, recipients, folders, regex patterns
- **Multiple LLM Providers**: OpenAI, Anthropic, Ollama, or any OpenAI-compatible API
- **PDF Attachment Parsing**: Extracts text from PDF attachments for event parsing
- **Multi-Event Support**: Can parse multiple events from a single email
- **Task Support**: Recognizes tasks (VTODO-style) and creates them as all-day events
- **CalDAV Integration**: Works with Nextcloud, ownCloud, or any CalDAV server
- **Web UI**: Full configuration via browser
- **Preview Mode**: See which emails will be processed before they get processed
- **Manual Processing**: Trigger immediate processing without waiting for the next poll
- **Grace Period**: Wait before auto-creating events (for review)
- **Event Updates**: Update existing calendar events when re-processing emails
- **Rejection Handling**: Delete calendar events for rejected emails

---

## Docker Setup (Recommended)

### Prerequisites

- Docker and Docker Compose installed

### Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd mail-event-extractor

# Create .env file
cp .env.example .env

# Edit .env with your settings
nano .env

# Build and run
docker-compose up -d

# View logs
docker-compose logs -f
```

### Configuration

Edit the `.env` file with your settings:

```env
# Database
PCB_DATABASE_URL=sqlite+aiosqlite:///data/mail_events_to_caldav.db

# Logging
PCB_LOG_LEVEL=INFO
```

### Access

- Web UI: http://localhost:8888
- Health check: http://localhost:8888/health

### Docker Commands

```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# View logs
docker-compose logs -f

# Rebuild
docker-compose build --no-cache
```

---

## Manual Setup (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Or with poetry
poetry install

# Run
python -m uvicorn mail_events_to_caldav.main:app --host 0.0.0.0 --port 8888
```

Configure via the web UI at `http://localhost:8888`.

---

## Requirements

- Python 3.11+
- IMAP access (any IMAP server)
- CalDAV server (Nextcloud, ownCloud, etc.)
- LLM API key (OpenAI, Anthropic, or local Ollama)

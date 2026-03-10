# Mail Event Extractor

A self-hosted application that monitors email accounts for calendar-related content, uses an LLM to parse event details, and creates calendar events in a CalDAV server.

## ⚠️ Proof of Concept

**This software is a proof of concept and is NOT ready for production use.**

- Significant polishing and testing required before real use
- LLM parsing quality varies and may miss events or extract incorrect data
- No comprehensive error handling or retry logic
- Use with a **separate calendar** from your primary calendar to avoid polluting it with bad events

## How It Works

```
┌─────────────┐     ┌──────────┐     ┌──────┐     ┌────────┐
│   IMAP      │────▶│  Filter  │────▶│ LLM  │────▶│ CalDAV │
│  (Proton)   │     │  Emails  │     │ Parse│     │ Server │
└─────────────┘     └──────────┘     └──────┘     └────────┘
```

1. **Poller** checks IMAP at configured intervals
2. **Filter** selects emails matching criteria (keywords, senders, folders)
3. **LLM Parser** extracts event details (title, time, location)
4. **CalDAV Client** creates events in your calendar

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Or with poetry
poetry install

# Run
python -m uvicorn protoncalbridge.main:app --host 0.0.0.0 --port 8080
```

Configure via the web UI at `http://localhost:8080`.

## Features

- IMAP/Proton Bridge support
- Configurable email filters (keywords, senders, folders)
- Multiple LLM providers (OpenAI, Anthropic, Ollama, OpenAI-compatible)
- CalDAV calendar integration
- Web UI for configuration

## Requirements

- Python 3.11+
- IMAP access (Proton Bridge or any IMAP server)
- CalDAV server (Nextcloud, etc.)
- LLM API key (OpenAI, Anthropic, or local Ollama)

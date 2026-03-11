FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-root

COPY src/ ./src/
COPY templates/ ./templates/

ENV PYTHONPATH=/app/src:$PYTHONPATH
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1

RUN mkdir -p /app/data /data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "mail_events_to_caldav.main"]

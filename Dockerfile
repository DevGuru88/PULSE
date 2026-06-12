FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── Install uv for faster dependency resolution ─────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# ── Install FastAPI application dependencies ────────────────────────────────
COPY webapp/requirements.txt /tmp/requirements.txt
RUN uv pip install --system --no-cache -r /tmp/requirements.txt && rm /tmp/requirements.txt

# ── FastAPI application ─────────────────────────────────────────────────────
COPY webapp/ webapp/

# ── SDLC Document Pipeline ─────────────────────────────────────────────────
COPY doc_pipeline_tool.py .
COPY pipeline/ pipeline/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/metrics || exit 1

CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8080"]

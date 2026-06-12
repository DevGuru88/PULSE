# Use official lightweight Python image
FROM python:3.11-slim

# ── Install uv for faster dependency resolution ─────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    bash \
    jq \
    ca-certificates \
    gnupg \
&& rm -rf /var/lib/apt/lists/*

# Install gcloud CLI
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    | tee /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update && apt-get install -y google-cloud-cli && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

# Make scripts executable
RUN chmod +x fetch_findings.sh
RUN chmod +x entrypoint.sh

# Environment variables
ENV PYTHONUNBUFFERED=1

# Start pipeline
ENTRYPOINT ["./entrypoint.sh"]
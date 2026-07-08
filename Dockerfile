# SkrobbleDS - Last.fm scrobbler for Linn DS and OpenHome UPnP players

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py ./
COPY Upnp/ ./Upnp/
COPY templates/ ./templates/
COPY favicon.png ./

# Copy config examples
COPY config/*.example ./config/

# Create non-root user and config directory
RUN groupadd -r skrobble && useradd -r -g skrobble skrobble && \
    mkdir -p /app/config && \
    chown -R skrobble:skrobble /app

USER skrobble

# Expose web UI port
EXPOSE 9099

# Set environment variables with defaults
ENV PYTHONUNBUFFERED=1 \
    WEBUI_PORT=9099

# Use exec form to ensure proper signal handling
# IMPORTANT: Must run with --network host for UPnP multicast discovery
ENTRYPOINT ["python3", "-u", "SkrobbleDs.py"]

# url-pdf-service Dockerfile
#
# Builds a lean image containing Python 3.13, uv, Playwright, Chromium,
# and the Comcast corporate root CA certificate so that Playwright can
# verify HTTPS connections that pass through the corporate proxy/VPN.
#
# Multi-stage build:
#   builder  — installs Python deps via uv into /app/.venv
#   runtime  — copies the venv + app code; installs Chromium system libs
#              and the corporate CA certificate

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency manifest and install production deps only
COPY pyproject.toml .
RUN uv sync --no-dev
RUN uv add playwright

# Install Playwright Chromium browser into the venv
RUN uv run playwright install --with-deps chromium


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# System libraries required by Chromium headless
# Ref: https://playwright.dev/docs/docker
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libasound2 \
    libatspi2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libdbus-1-3 \
    fonts-liberation \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install Comcast corporate root CA certificate ─────────────────────────────
# Required so that Playwright/Chromium trusts HTTPS connections that pass
# through the Comcast corporate proxy or VPN.
COPY comcast-corp-root-ca.pem /usr/local/share/ca-certificates/comcast-corp-root-ca.crt
RUN update-ca-certificates

# Copy the venv (includes Playwright + Chromium binary) from the builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# Copy application source
COPY app/ app/

# Activate venv for all subsequent RUN / CMD
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Tell Playwright where the browsers were installed (builder stage used root)
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# Point Python/httpx/requests at the updated system cert bundle so the
# reachability HEAD check also trusts the corporate CA.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

EXPOSE 8001

# Non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app \
    && chmod -R 755 /root/.cache/ms-playwright

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]

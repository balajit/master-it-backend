"""URL-to-PDF microservice.

A stateless FastAPI service that scrapes a URL using Playwright/Chromium
and returns the rendered page as a PDF file.

Endpoints
---------
POST /convert   — Accept a URL, return PDF bytes.
GET  /health    — Liveness check.

This service has no database, no authentication, and no file storage.
It is intended to be called only by the main application over the internal
Docker network (not exposed publicly).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import Response

from app.schemas import ConvertRequest
from app.scraper import check_url_reachable, scrape_url_to_pdf_bytes, url_to_filename

logging.basicConfig(level=logging.INFO)
_LOG = logging.getLogger(__name__)

app = FastAPI(
    title="URL-to-PDF Service",
    description="Stateless Playwright/Chromium URL scraper that returns PDF bytes.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check. Returns 200 when the service is ready."""
    return {"status": "ok"}


@app.post("/convert")
async def convert(request: ConvertRequest) -> Response:
    """Scrape a URL and return the page as a PDF.

    The PDF is returned as ``application/pdf`` binary content.
    Two response headers carry metadata:

    - ``X-Filename``: a URL-derived safe filename (e.g. ``example_com_page.pdf``)
    - ``Content-Disposition``: ``attachment; filename="<filename>"``

    Possible error responses:

    - ``400`` — unsupported URL scheme or URL not reachable
    - ``408`` — page load timed out
    - ``422`` — Playwright navigation error (DNS, SSL, etc.)
    - ``500`` — unexpected internal error
    """
    url_str = str(request.url)
    _LOG.info("Converting URL to PDF: %s", url_str)

    # 1. Reachability check (HEAD request, 5s timeout)
    await check_url_reachable(url_str)

    # 2. Scrape and render to PDF
    pdf_bytes = await scrape_url_to_pdf_bytes(url_str)

    # 3. Derive filename from URL
    filename = url_to_filename(url_str)

    _LOG.info(
        "PDF generated: %s — %d bytes for %s",
        filename,
        len(pdf_bytes),
        url_str,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "X-Filename": filename,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )

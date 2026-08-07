"""HTTP client for the URL-to-PDF microservice.

The main app delegates all Playwright/Chromium work to the url-pdf-service
container. This module provides a single async function that calls the
service's POST /convert endpoint and returns the PDF bytes + derived filename.

Configuration
-------------
Set ``URL_PDF_SERVICE_URL`` in your environment (or .env file) to override
the default. When running in Docker, use the service name:
    URL_PDF_SERVICE_URL=http://url-pdf-service:8001

For local development without Docker:
    URL_PDF_SERVICE_URL=http://localhost:8001
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import HTTPException

_LOG = logging.getLogger(__name__)

# Default: service name when running inside Docker network;
# override to http://localhost:8001 for local dev without Docker.
URL_PDF_SERVICE_URL: str = os.getenv(
    "URL_PDF_SERVICE_URL", "http://localhost:8001"
).rstrip("/")

# Total timeout for the microservice call.
# The service itself has a 30s page-load timeout; add 10s of headroom.
_REQUEST_TIMEOUT: float = 45.0


async def convert_url_to_pdf_bytes(url: str) -> tuple[bytes, str]:
    """Call the url-pdf microservice to scrape a URL and return a PDF.

    Args:
        url: A fully-qualified http/https URL to scrape.

    Returns:
        A 2-tuple of ``(pdf_bytes, filename)`` where ``filename`` is the
        URL-derived slug from the ``X-Filename`` response header.

    Raises:
        HTTPException 400: URL is not reachable or has an invalid scheme
            (propagated from the microservice).
        HTTPException 408: Page load timed out (propagated).
        HTTPException 422: Playwright navigation error (propagated).
        HTTPException 503: The url-pdf-service is unreachable (network error).
        HTTPException 500: Unexpected error from the microservice.
    """
    endpoint = f"{URL_PDF_SERVICE_URL}/convert"
    _LOG.info("Calling url-pdf-service: POST %s  url=%s", endpoint, url)

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(endpoint, json={"url": url})
    except httpx.ConnectError as exc:
        _LOG.error("url-pdf-service unreachable at %s: %s", URL_PDF_SERVICE_URL, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "The URL-to-PDF service is currently unavailable. "
                "Ensure the url-pdf-service container is running."
            ),
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="The URL-to-PDF service did not respond in time.",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Network error communicating with url-pdf-service: {exc}",
        )

    if response.status_code != 200:
        # Detect VPN/proxy intercept: a redirect (3xx) from a non-JSON body
        # means a corporate VPN or captive portal intercepted the request
        # before it reached the url-pdf-service container.
        if response.status_code in (301, 302, 303, 307, 308):
            redirect_target = response.headers.get("location", "unknown")
            _LOG.error(
                "url-pdf-service call intercepted by proxy/VPN — "
                "got %d redirect to %s. "
                "Set URL_PDF_SERVICE_URL to the Docker bridge IP "
                "(e.g. http://192.168.x.x:8001) to bypass VPN interception.",
                response.status_code,
                redirect_target,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "The URL-to-PDF service request was intercepted by a network proxy or VPN. "
                    f"Redirected to: {redirect_target}. "
                    "Set URL_PDF_SERVICE_URL to the Docker container's bridge network IP "
                    "to bypass the proxy (e.g. http://192.168.97.9:8001)."
                ),
            )

        # Propagate other error details from the service
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text or f"HTTP {response.status_code}"
        _LOG.warning(
            "url-pdf-service returned %d for url=%s: %s",
            response.status_code,
            url,
            detail,
        )
        raise HTTPException(status_code=response.status_code, detail=detail)

    pdf_bytes: bytes = response.content
    filename: str = response.headers.get("X-Filename", "document.pdf")

    _LOG.info(
        "url-pdf-service: received %d bytes  filename=%s  url=%s",
        len(pdf_bytes),
        filename,
        url,
    )
    return pdf_bytes, filename

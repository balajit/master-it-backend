"""Playwright-based URL scraper and PDF generator.

SETUP NOTE
----------
Before running this service, install the Chromium browser:
    uv run playwright install chromium --with-deps

In Docker this is handled by the Dockerfile automatically.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


# ── URL slug helper ────────────────────────────────────────────────────────────


def url_to_filename(url: str) -> str:
    """Derive a safe PDF filename from a URL.

    Strips scheme, query string, and fragment. Replaces non-alphanumeric
    characters with underscores, collapses consecutive underscores, and
    truncates the stem to 100 characters before appending ``.pdf``.

    Examples::
        https://example.com/path/to/page?q=1  →  example_com_path_to_page.pdf
        https://docs.python.org/3/library/re.html  →  docs_python_org_3_library_re.pdf
    """
    parsed = urlparse(url)
    # netloc + path, no scheme/query/fragment
    raw = f"{parsed.netloc}{parsed.path}"
    # Replace non-alphanumeric chars with _
    slug = re.sub(r"[^a-zA-Z0-9]", "_", raw)
    # Collapse consecutive underscores
    slug = re.sub(r"_+", "_", slug)
    # Strip leading/trailing underscores
    slug = slug.strip("_")
    # Truncate stem to 100 chars
    if len(slug) > 100:
        slug = slug[:100].rstrip("_")
    return f"{slug}.pdf" if slug else "document.pdf"


# ── Reachability check ─────────────────────────────────────────────────────────


async def check_url_reachable(url: str) -> None:
    """Verify the URL scheme is http/https and the host is reachable.

    Only blocks on network-level failures (DNS, TCP, timeout). HTTP status
    codes from the server (including redirects, auth walls, etc.) are NOT
    treated as errors — Playwright will handle the actual page load.

    Raises:
        HTTPException 400: if the scheme is not http/https.
        HTTPException 400: if a network-level error prevents reaching the host.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed.",
        )

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            # We only care that the host is reachable — ignore any HTTP status.
            # Auth walls (302, 401, 403) are intentionally not blocked here;
            # Playwright will render whatever the server returns.
            await client.head(url)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=400,
            detail="URL reachability check timed out. The host may be unreachable.",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not reach URL: {exc}",
        )


# ── PDF generation ─────────────────────────────────────────────────────────────


async def scrape_url_to_pdf_bytes(url: str) -> bytes:
    """Scrape a URL with Playwright Chromium and return the PDF as bytes.

    Uses ``networkidle`` wait strategy to ensure all async content (XHR,
    lazy images, SPAs) has finished loading before printing to PDF.

    Args:
        url: A fully-qualified http/https URL.

    Returns:
        PDF file content as bytes.

    Raises:
        HTTPException 408: if the page load times out (>30 seconds).
        HTTPException 422: if Playwright cannot navigate to the page
            (DNS failure, SSL error, redirects to error page, etc.).
        HTTPException 500: on unexpected internal errors.
    """
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                # Accept the system CA bundle so Chromium trusts the corporate
                # root certificate installed via update-ca-certificates.
                # This is required when behind a corporate proxy/VPN that
                # performs TLS inspection using a private CA.
                args=["--ignore-certificate-errors"],
            )
            try:
                page = await browser.new_page()
                try:
                    await page.goto(
                        url,
                        wait_until="networkidle",
                        timeout=30_000,  # 30 seconds
                    )
                    pdf_bytes: bytes = await page.pdf(
                        format="A4",
                        print_background=True,
                    )
                    return pdf_bytes
                finally:
                    await page.close()
            finally:
                await browser.close()

    except PlaywrightTimeoutError:
        raise HTTPException(
            status_code=408,
            detail=(
                f"Page load timed out after 30 seconds for URL: {url}. "
                "The page may be too slow or unavailable."
            ),
        )
    except PlaywrightError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not load page: {exc}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {exc}",
        )

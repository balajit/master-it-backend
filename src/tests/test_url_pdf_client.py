"""Tests for the URL-to-PDF httpx client (url_pdf_client.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.url_pdf_client import convert_url_to_pdf_bytes


class TestConvertUrlToPdfBytes:
    @pytest.mark.asyncio
    async def test_success_returns_bytes_and_filename(self) -> None:
        fake_pdf = b"%PDF-1.4 fake content"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_pdf
        mock_response.headers = {"X-Filename": "example_com.pdf"}

        with patch("services.url_pdf_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            pdf_bytes, filename = await convert_url_to_pdf_bytes("https://example.com")

        assert pdf_bytes == fake_pdf
        assert filename == "example_com.pdf"

    @pytest.mark.asyncio
    async def test_missing_x_filename_header_uses_default(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"%PDF fake"
        mock_response.headers = {}  # No X-Filename

        with patch("services.url_pdf_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            _, filename = await convert_url_to_pdf_bytes("https://example.com")

        assert filename == "document.pdf"

    @pytest.mark.asyncio
    async def test_service_400_raises_http_exception(self) -> None:
        from fastapi import HTTPException

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json = MagicMock(return_value={"detail": "Invalid URL scheme"})
        mock_response.text = "Invalid URL scheme"

        with patch("services.url_pdf_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await convert_url_to_pdf_bytes("file:///etc/passwd")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_service_408_raises_http_exception(self) -> None:
        from fastapi import HTTPException

        mock_response = MagicMock()
        mock_response.status_code = 408
        mock_response.json = MagicMock(return_value={"detail": "Page load timed out"})
        mock_response.text = "Page load timed out"

        with patch("services.url_pdf_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await convert_url_to_pdf_bytes("https://slow.example.com")

        assert exc_info.value.status_code == 408

    @pytest.mark.asyncio
    async def test_connect_error_raises_503(self) -> None:
        from fastapi import HTTPException

        with patch("services.url_pdf_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await convert_url_to_pdf_bytes("https://example.com")

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_timeout_raises_504(self) -> None:
        from fastapi import HTTPException

        with patch("services.url_pdf_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timed out")
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await convert_url_to_pdf_bytes("https://example.com")

        assert exc_info.value.status_code == 504

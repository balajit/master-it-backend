"""Pydantic schemas for the URL-to-PDF microservice."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel


class ConvertRequest(BaseModel):
    """Request body for POST /convert."""

    url: AnyHttpUrl

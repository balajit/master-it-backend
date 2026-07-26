"""Smoke tests for the FastAPI application startup and core endpoints."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

# Ensure src/ is on sys.path so `from main import app` works when pytest runs from project root
_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def app():
    """Import the app — verifies all imports resolve correctly."""
    from main import app as _app

    return _app


class TestAppImports:
    """Verify the app module loads without import errors."""

    def test_app_loads(self, app):
        assert app.title == "Master It API"

    def test_health_endpoint(self, app):
        """Health endpoint returns 200 with status ok."""

        async def _hit():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.get("/health")

        import asyncio

        resp = asyncio.run(_hit())
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestProductionStart:
    """Verify start.sh --production works by running uvicorn with --app-dir src."""

    def test_uvicorn_starts_with_app_dir_src(self):
        """Simulate what start.sh --production does: uvicorn main:app --app-dir src."""
        env = os.environ.copy()
        env["JWT_SECRET"] = "test-secret-for-production-smoke"
        env["DATABASE_URL"] = (
            "postgresql+asyncpg://postgres_user:secure_password_here@localhost:5433/learning_platform_testing"
        )

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--app-dir",
                "src",
                "--host",
                "127.0.0.1",
                "--port",
                "5099",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
        )

        try:
            # Wait for the server to start
            time.sleep(5)
            assert proc.poll() is None, (
                f"Server exited early with code {proc.returncode}"
            )

            # Hit health endpoint
            with httpx.Client(base_url="http://127.0.0.1:5099") as client:
                resp = client.get("/health")
                assert resp.status_code == 200
                assert resp.json() == {"status": "ok"}
        finally:
            proc.terminate()
            proc.wait(timeout=5)

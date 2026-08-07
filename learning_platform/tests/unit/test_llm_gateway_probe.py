"""Tests for LLMGatewayProbe."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from learning_platform.agents.llm.gateway_probe import LLMGatewayProbe


def _make_settings(provider: str = "ollama", base_url: str = "http://localhost:11434") -> object:
    s = MagicMock()
    s.llm_provider = provider
    s.llm_base_url = base_url
    return s


class TestLLMGatewayProbe:
    @pytest.mark.asyncio
    async def test_ollama_available(self) -> None:
        settings = _make_settings("ollama")
        mock_llm = MagicMock()
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=MagicMock())
        mock_llm._async_client = mock_client

        with patch(
            "learning_platform.agents.llm.gateway_probe.LLMGatewayProbe._probe",
            new=AsyncMock(),
        ):
            with patch(
                "learning_platform.agents.llm.adapter.LLMFactory.create",
                return_value=mock_llm,
            ):
                probe = LLMGatewayProbe()
                result = await probe.is_available(settings, timeout=5.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_ollama_unavailable_on_timeout(self) -> None:
        import asyncio

        settings = _make_settings("ollama")
        mock_llm = MagicMock()

        async def _slow(*_: object, **__: object) -> None:
            await asyncio.sleep(100)

        with patch(
            "learning_platform.agents.llm.adapter.LLMFactory.create",
            return_value=mock_llm,
        ):
            with patch.object(LLMGatewayProbe, "_probe", new=_slow):
                probe = LLMGatewayProbe()
                result = await probe.is_available(settings, timeout=0.05)
        assert result is False

    @pytest.mark.asyncio
    async def test_unavailable_on_connection_error(self) -> None:
        settings = _make_settings("openai")
        mock_llm = MagicMock()

        async def _fail(*_: object, **__: object) -> None:
            raise ConnectionRefusedError("refused")

        with patch(
            "learning_platform.agents.llm.adapter.LLMFactory.create",
            return_value=mock_llm,
        ):
            with patch.object(LLMGatewayProbe, "_probe", new=_fail):
                probe = LLMGatewayProbe()
                result = await probe.is_available(settings, timeout=5.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_factory_create_failure_returns_false(self) -> None:
        settings = _make_settings("ollama")
        with patch(
            "learning_platform.agents.llm.adapter.LLMFactory.create",
            side_effect=RuntimeError("bad config"),
        ):
            probe = LLMGatewayProbe()
            result = await probe.is_available(settings, timeout=5.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_probe_ollama_calls_list(self) -> None:
        mock_client = MagicMock()
        mock_client.list = AsyncMock(return_value=MagicMock())
        mock_llm = MagicMock()
        mock_llm._async_client = mock_client

        await LLMGatewayProbe._probe(mock_llm, "ollama")
        mock_client.list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_probe_openai_calls_models_list(self) -> None:
        mock_models = MagicMock()
        mock_models.list = AsyncMock(return_value=MagicMock())
        mock_root_client = MagicMock()
        mock_root_client.models = mock_models
        mock_llm = MagicMock()
        mock_llm.root_async_client = mock_root_client

        await LLMGatewayProbe._probe(mock_llm, "openai")
        mock_models.list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_probe_anthropic_calls_models_list(self) -> None:
        mock_models = MagicMock()
        mock_models.list = AsyncMock(return_value=MagicMock())
        mock_async_client = MagicMock()
        mock_async_client.models = mock_models
        mock_llm = MagicMock()
        mock_llm._async_client = mock_async_client

        await LLMGatewayProbe._probe(mock_llm, "anthropic")
        mock_models.list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_probe_unknown_provider_tries_root_async_client(self) -> None:
        mock_models = MagicMock()
        mock_models.list = AsyncMock(return_value=MagicMock())
        mock_root_client = MagicMock()
        mock_root_client.models = mock_models
        mock_llm = MagicMock(spec=[])
        mock_llm.root_async_client = mock_root_client

        await LLMGatewayProbe._probe(mock_llm, "custom-provider")
        mock_models.list.assert_awaited_once()

"""LLM Gateway Probe — checks whether the configured LLM endpoint is reachable.

Uses the LLM instance created by LLMFactory to call the provider's models-list
endpoint. This is provider-agnostic: it works whether llm_provider=openai points
to api.openai.com or to a local LM Studio / vLLM / Ollama-compat server.

Probe calls per provider:
  ollama   → llm._async_client.list()          (ollama.AsyncClient)
  openai   → llm.root_async_client.models.list() (openai.AsyncOpenAI)
  anthropic → llm._async_client.models.list()   (anthropic.AsyncAnthropic)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from learning_platform.config import Settings

_LOG = logging.getLogger(__name__)

_PROBE_TIMEOUT: float = 5.0


class LLMGatewayProbe:
    """Probes the configured LLM gateway using its models-list endpoint."""

    async def is_available(self, settings: Settings, timeout: float = _PROBE_TIMEOUT) -> bool:
        """Return True if the LLM endpoint responds within *timeout* seconds."""
        from learning_platform.agents.llm.adapter import LLMFactory

        try:
            llm = LLMFactory.create(settings)
        except Exception as exc:
            _LOG.warning("LLMGatewayProbe: failed to create LLM instance: %s", exc)
            return False

        provider = settings.llm_provider.lower()
        try:
            await asyncio.wait_for(self._probe(llm, provider), timeout=timeout)
            _LOG.debug("LLMGatewayProbe: gateway available (provider=%s)", provider)
            return True
        except asyncio.TimeoutError:
            _LOG.warning("LLMGatewayProbe: timeout after %.1fs (provider=%s)", timeout, provider)
            return False
        except Exception as exc:
            _LOG.warning("LLMGatewayProbe: unavailable (provider=%s): %s", provider, exc)
            return False

    @staticmethod
    async def _probe(llm: object, provider: str) -> None:
        """Dispatch to the correct client call for the given provider."""
        if provider == "ollama":
            # ollama.AsyncClient — has .list() which returns available models
            client = getattr(llm, "_async_client", None)
            if client is None:
                raise RuntimeError("ChatOllama._async_client not found")
            await client.list()

        elif provider in {"openai", "openai-compatible"}:
            # openai.AsyncOpenAI — accessible via root_async_client
            client = getattr(llm, "root_async_client", None)
            if client is None:
                raise RuntimeError("ChatOpenAI.root_async_client not found")
            await client.models.list()

        elif provider == "anthropic":
            # anthropic.AsyncAnthropic — accessible via _async_client
            client = getattr(llm, "_async_client", None)
            if client is None:
                raise RuntimeError("ChatAnthropic._async_client not found")
            await client.models.list()

        else:
            # Unknown / future provider registered via LLMFactory.register().
            # Attempt a best-effort probe using any known client attribute.
            for attr in ("root_async_client", "_async_client", "async_client"):
                client = getattr(llm, attr, None)
                if client is None:
                    continue
                # Try models.list() first (OpenAI-compat), then list() (Ollama-compat)
                models_client = getattr(client, "models", None)
                if models_client is not None:
                    await models_client.list()
                    return
                list_fn = getattr(client, "list", None)
                if list_fn is not None:
                    await list_fn()
                    return
            raise RuntimeError(
                f"No known async client attribute found on LLM for provider '{provider}'"
            )

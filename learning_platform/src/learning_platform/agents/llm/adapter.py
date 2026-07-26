"""LLM adapter — dynamic provider selection for Ollama, OpenAI, and Anthropic.

Usage:
    from learning_platform.agents.llm import LLMFactory
    from learning_platform.config import get_settings

    settings = get_settings()
    llm = LLMFactory.create(settings)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from learning_platform.config import Settings


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def create(self, settings: Settings) -> BaseChatModel:
        """Create and return a configured chat model instance."""
        ...


class OllamaProvider(LLMProvider):
    """Local Ollama provider via langchain-ollama."""

    def create(self, settings: Settings) -> BaseChatModel:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
        )


class OpenAIProvider(LLMProvider):
    """OpenAI API provider via langchain-openai."""

    def create(self, settings: Settings) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )


class AnthropicProvider(LLMProvider):
    """Anthropic API provider via langchain-anthropic."""

    def create(self, settings: Settings) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )


_REGISTRY: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


class LLMFactory:
    """Factory for creating LLM instances based on provider name.

    Usage::

        llm = LLMFactory.create(settings)
    """

    @staticmethod
    def create(settings: Settings) -> BaseChatModel:
        """Create an LLM instance from settings.

        Args:
            settings: Application settings containing llm_provider and
                      provider-specific configuration.

        Returns:
            A configured BaseChatModel instance.

        Raises:
            ValueError: If the provider is not supported.
        """
        provider_name = settings.llm_provider.lower()

        provider_cls = _REGISTRY.get(provider_name)
        if provider_cls is None:
            supported = ", ".join(sorted(_REGISTRY.keys()))
            raise ValueError(
                f"Unknown LLM provider '{provider_name}'. Supported providers: {supported}"
            )

        return provider_cls().create(settings)

    @staticmethod
    def register(name: str, provider_cls: type[LLMProvider]) -> None:
        """Register a custom LLM provider.

        Args:
            name: Provider name used in settings.
            provider_cls: Provider class implementing LLMProvider.
        """
        _REGISTRY[name] = provider_cls

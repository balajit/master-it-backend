"""Agents module — AI agent infrastructure for the learning platform.

This module provides a foundation for building AI-powered agents using
LangChain.  Each agent is self-contained and can be run independently
or composed into larger workflows.

Modules:
    llm: LLM adapter supporting multiple providers (Ollama, OpenAI, Anthropic)
    curator: Educational content analysis agent
"""

from learning_platform.agents.curator import CuratorAgent
from learning_platform.agents.llm import LLMFactory

__all__ = ["LLMFactory", "CuratorAgent"]

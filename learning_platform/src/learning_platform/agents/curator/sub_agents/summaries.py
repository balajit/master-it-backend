"""SummariesAgent — generates a concise lesson summary.

Follows the same pattern as all sub-agents:
  skip check → cleanup → LLM call → persist → completion marker → raise on failure
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

from learning_platform.models.agent_pipeline import SummaryItem

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from sqlalchemy.ext.asyncio import AsyncSession

_LOG = logging.getLogger(__name__)

AGENT_TYPE: str = "summaries"

SYSTEM_PROMPT = """You are an educational content summarization assistant.

Write a concise summary of the provided lesson from a student's perspective.

Rules:
- The summary must be 2 to 4 sentences.
- Focus on the core concepts and key takeaways.
- Do NOT include examples, formulas, or peripheral details.
- Do NOT invent facts not supported by the lesson.
- Return ONLY valid JSON matching this schema:
  {"summary": "string"}
"""

USER_PROMPT_TEMPLATE = """Summarize the following lesson.

LESSON TITLE: {title}

LESSON CONTENT:
---------------
{content}
---------------

Return JSON only.
"""


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if "```" in cleaned:
        start = cleaned.find("```")
        next_newline = cleaned.find("\n", start)
        if next_newline != -1:
            end = cleaned.rfind("```")
            if end > next_newline:
                cleaned = cleaned[next_newline + 1 : end].strip()
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        cleaned = cleaned[first_brace : last_brace + 1]
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else {"raw": result}
    except json.JSONDecodeError:
        return {"raw": text, "error": "Failed to parse JSON"}


class SummariesAgent:
    """Generates a 2–4 sentence lesson summary using an LLM."""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        self._llm = llm

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            from learning_platform.agents.llm import LLMFactory
            from learning_platform.config import get_settings

            self._llm = LLMFactory.create(get_settings())
        return self._llm

    async def run(
        self,
        lesson_id: UUID,
        lesson_title: str,
        lesson_text: str,
        document_id: UUID,
        agent_process_id: int,
        session: AsyncSession,
    ) -> list[SummaryItem]:
        """Generate a summary for a lesson. Raises on LLM failure."""
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.agent_pipeline_outputs import (
            AgentPipelineOutputRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_pipeline_outputs import (
            SummaryRow,
        )

        completion_repo = AgentLessonCompletionRepository(session)
        output_repo = AgentPipelineOutputRepository(session)
        lesson_id_str = str(lesson_id)
        document_id_str = str(document_id)

        if await completion_repo.has_completed(agent_process_id, lesson_id_str, AGENT_TYPE):
            _LOG.info("SummariesAgent: already completed lesson %s, skipping", lesson_id)
            return []

        await output_repo.delete_summaries_for_lesson(document_id_str, lesson_id_str)

        user_prompt = USER_PROMPT_TEMPLATE.format(title=lesson_title, content=lesson_text)
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        chain = (
            RunnableLambda(lambda _: messages)
            | self.llm
            | StrOutputParser()
            | RunnableLambda(_extract_json)
        )
        result: dict[str, Any] = await chain.ainvoke({})

        summary_text = str(result.get("summary", "")).strip()
        items: list[SummaryItem] = []
        if summary_text:
            session.add(
                SummaryRow(
                    document_id=document_id_str,
                    lesson_id=lesson_id_str,
                    content=summary_text,
                )
            )
            await session.flush()
            items.append(SummaryItem(lesson_id=lesson_id, content=summary_text))

        await completion_repo.mark_done(
            agent_process_id, document_id_str, lesson_id_str, AGENT_TYPE
        )
        _LOG.info("SummariesAgent: generated summary for lesson %s", lesson_id)
        return items

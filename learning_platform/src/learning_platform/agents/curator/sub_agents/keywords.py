"""KeywordsAgent — extracts key terms and definitions from a lesson.

The orchestrator passes pre-extracted lesson text and lesson_id. This agent:
1. Checks lp_agent_lesson_completions — skips if already ran for this lesson/run
2. Deletes any partial output from lp_keywords for this lesson (cleanup before retry)
3. Calls the LLM with the lesson text
4. Persists output rows to lp_keywords
5. Writes a completion marker to lp_agent_lesson_completions
6. Raises on LLM failure so the orchestrator can mark the lesson as failed
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

from learning_platform.models.agent_pipeline import KeywordItem

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from sqlalchemy.ext.asyncio import AsyncSession

_LOG = logging.getLogger(__name__)

AGENT_TYPE: str = "keywords"

SYSTEM_PROMPT = """You are an educational content analysis assistant.

Extract key terms from the lesson content provided.

Rules:
- Identify terms that students should remember, that are introduced or defined,
  represent important vocabulary, or are likely to appear in exams.
- Do NOT include common words, names of examples, or incidental nouns.
- Do NOT invent facts not supported by the lesson.
- Return ONLY valid JSON matching this exact schema:
  {"key_terms": [{"term": "string", "definition": "string"}]}
- Each definition must be a clear, concise one-sentence explanation.
- Return between 3 and 15 key terms.
"""

USER_PROMPT_TEMPLATE = """Extract key terms from the following lesson.

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


class KeywordsAgent:
    """Extracts key terms and definitions per lesson using an LLM."""

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
    ) -> list[KeywordItem]:
        """Extract key terms for a lesson.

        Skips if already completed for this run. Raises on LLM failure.
        """
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.agent_pipeline_outputs import (
            AgentPipelineOutputRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_pipeline_outputs import (
            KeywordRow,
        )

        completion_repo = AgentLessonCompletionRepository(session)
        output_repo = AgentPipelineOutputRepository(session)

        lesson_id_str = str(lesson_id)
        document_id_str = str(document_id)

        # 1. Skip if already completed for this run
        if await completion_repo.has_completed(agent_process_id, lesson_id_str, AGENT_TYPE):
            _LOG.info("KeywordsAgent: already completed lesson %s, skipping", lesson_id)
            return []

        # 2. Clean up any partial output from a previous failed attempt
        await output_repo.delete_keywords_for_lesson(document_id_str, lesson_id_str)

        # 3. Call LLM — raise on failure so orchestrator marks lesson failed
        user_prompt = USER_PROMPT_TEMPLATE.format(title=lesson_title, content=lesson_text)
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        chain = (
            RunnableLambda(lambda _: messages)
            | self.llm
            | StrOutputParser()
            | RunnableLambda(_extract_json)
        )
        result: dict[str, Any] = await chain.ainvoke({})

        # 4. Parse and persist output rows
        raw_terms = result.get("key_terms", [])
        rows: list[KeywordRow] = []
        items: list[KeywordItem] = []
        for entry in raw_terms:
            term = str(entry.get("term", "")).strip()
            definition = str(entry.get("definition", "")).strip()
            if term and definition:
                rows.append(
                    KeywordRow(
                        document_id=document_id_str,
                        lesson_id=lesson_id_str,
                        term=term,
                        definition=definition,
                    )
                )
                items.append(KeywordItem(lesson_id=lesson_id, term=term, definition=definition))

        if rows:
            session.add_all(rows)
            await session.flush()

        # 5. Write completion marker
        await completion_repo.mark_done(
            agent_process_id, document_id_str, lesson_id_str, AGENT_TYPE
        )

        _LOG.info("KeywordsAgent: extracted %d term(s) for lesson %s", len(items), lesson_id)
        return items

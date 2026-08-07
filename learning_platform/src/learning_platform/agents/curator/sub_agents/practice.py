"""PracticeAgent — generates applied MCQ practice questions per lesson.

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

from learning_platform.models.agent_pipeline import PracticeQuestion

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from sqlalchemy.ext.asyncio import AsyncSession

_LOG = logging.getLogger(__name__)

AGENT_TYPE: str = "practice"

SYSTEM_PROMPT = """You are an educational practice exercise generation assistant.

Generate applied multiple-choice practice questions from the lesson content provided.

Rules:
- Generate between 3 and 5 questions.
- Questions must be application or problem-solving oriented — not pure recall.
  Ask students to apply, analyse, or reason using lesson concepts.
- Each question must have exactly 4 answer choices (strings).
- One choice must be clearly correct; the others plausible but wrong.
- ``correct_index`` is the 0-based index of the correct choice.
- ``explanation`` is a brief one-sentence justification of the correct answer.
- Do NOT invent facts not supported by the lesson.
- Return ONLY valid JSON matching this schema:
  {
    "questions": [
      {
        "question": "string",
        "choices": ["string", "string", "string", "string"],
        "correct_index": 0,
        "explanation": "string"
      }
    ]
  }
"""

USER_PROMPT_TEMPLATE = """Generate practice questions from the following lesson.

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


def _validate_question(entry: dict[str, Any], lesson_id: UUID) -> PracticeQuestion | None:
    question = str(entry.get("question", "")).strip()
    choices = entry.get("choices", [])
    correct_index = entry.get("correct_index", 0)
    explanation = entry.get("explanation", None)
    if not question:
        return None
    if not isinstance(choices, list) or len(choices) < 2:
        return None
    if not isinstance(correct_index, int) or not (0 <= correct_index < len(choices)):
        correct_index = 0
    return PracticeQuestion(
        lesson_id=lesson_id,
        question=question,
        choices=[str(c) for c in choices],
        correct_index=correct_index,
        explanation=str(explanation).strip() if explanation else None,
    )


class PracticeAgent:
    """Generates 3–5 applied MCQ practice questions per lesson using an LLM."""

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
    ) -> list[PracticeQuestion]:
        """Generate practice questions for a lesson. Raises on LLM failure."""
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.agent_pipeline_outputs import (
            AgentPipelineOutputRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_pipeline_outputs import (
            PracticeQuestionRow,
        )

        completion_repo = AgentLessonCompletionRepository(session)
        output_repo = AgentPipelineOutputRepository(session)
        lesson_id_str = str(lesson_id)
        document_id_str = str(document_id)

        if await completion_repo.has_completed(agent_process_id, lesson_id_str, AGENT_TYPE):
            _LOG.info("PracticeAgent: already completed lesson %s, skipping", lesson_id)
            return []

        await output_repo.delete_practice_questions_for_lesson(document_id_str, lesson_id_str)

        user_prompt = USER_PROMPT_TEMPLATE.format(title=lesson_title, content=lesson_text)
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        chain = (
            RunnableLambda(lambda _: messages)
            | self.llm
            | StrOutputParser()
            | RunnableLambda(_extract_json)
        )
        result: dict[str, Any] = await chain.ainvoke({})

        raw_questions = result.get("questions", [])
        rows: list[PracticeQuestionRow] = []
        items: list[PracticeQuestion] = []
        for entry in raw_questions:
            q = _validate_question(entry, lesson_id)
            if q is not None:
                rows.append(
                    PracticeQuestionRow(
                        document_id=document_id_str,
                        lesson_id=lesson_id_str,
                        question=q.question,
                        choices=json.dumps(q.choices),
                        correct_index=q.correct_index,
                        explanation=q.explanation,
                    )
                )
                items.append(q)

        if rows:
            session.add_all(rows)
            await session.flush()

        await completion_repo.mark_done(
            agent_process_id, document_id_str, lesson_id_str, AGENT_TYPE
        )
        _LOG.info("PracticeAgent: generated %d question(s) for lesson %s", len(items), lesson_id)
        return items

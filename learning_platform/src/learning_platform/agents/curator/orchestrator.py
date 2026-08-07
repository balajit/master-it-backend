"""Curator Agent — orchestrates the Agent Pipeline (Pipeline 3).

CuratorAgent is the entry point for all lesson-level AI content generation.
It coordinates five sub-agents (keywords, summaries, flashcards, quizzes,
practice) over every lesson in a CanonicalBook using a LangGraph StateGraph.

Parallelism is controlled by the ``AGENT_PIPELINE_PARALLEL`` env var:
  - ``false`` (default) — sub-agents run sequentially per lesson (safe for
    local LLMs such as Ollama where parallel requests cause contention).
  - ``true`` — sub-agents fan out concurrently with ``asyncio.gather``.

Backward compatibility:
  The legacy ``analyze(lesson_text)`` / ``aanalyze(lesson_text)`` methods are
  preserved.  They delegate only to KeywordsAgent and return the original
  ``{"key_terms": [...]}`` dict format used by FlashCardGenerator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any, TypedDict
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph

from learning_platform.agents.curator.sub_agents.flashcards import FlashcardsAgent
from learning_platform.agents.curator.sub_agents.keywords import KeywordsAgent
from learning_platform.agents.curator.sub_agents.practice import PracticeAgent
from learning_platform.agents.curator.sub_agents.quizzes import QuizzesAgent
from learning_platform.agents.curator.sub_agents.summaries import SummariesAgent
from learning_platform.models.agent_pipeline import (
    AgentFlashcard,
    AgentPipelineResult,
    KeywordItem,
    PracticeQuestion,
    QuizQuestion,
    SummaryItem,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from sqlalchemy.ext.asyncio import AsyncSession

    from learning_platform.models.book import BookLesson, CanonicalBook

_LOG = logging.getLogger(__name__)

# ── Legacy system prompt (kept for backward-compat analyze()) ─────────────────

SYSTEM_PROMPT = """You are an educational content analysis assistant.

Your task is to analyze a lesson and extract structured learning metadata.

Analyze the lesson from a student's learning perspective.

Goals:
1. Identify important vocabulary and terms.
Rules:
- Do not invent facts that are not supported by the lesson.
- Preserve technical accuracy.
- Distinguish between examples and core concepts.
- Prefer concepts that help a student understand the subject.
- Return only valid JSON matching the required schema as { "key_terms" :["Inert Gas", "Anion"] }

## Key Terms

Identify terms that:
- students should remember
- are introduced or defined
- represent important vocabulary
- are likely to appear in exams

Do not include:
- common words
- names of examples
- incidental nouns
"""

USER_PROMPT_TEMPLATE = """Analyze the following lesson.

LESSON:
---------------
{lesson_text}
---------------

Return JSON
"""


def _build_messages(inputs: dict[str, Any]) -> list[SystemMessage | HumanMessage]:
    user_prompt = USER_PROMPT_TEMPLATE.format(lesson_text=inputs["lesson_text"])
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]


def _parse_json(text: str) -> dict[str, Any]:
    return _extract_json(text)


def _extract_json(text: str) -> dict[str, Any]:
    """Extract and parse JSON from LLM output."""
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
        if isinstance(result, dict):
            return result
        return {"raw": result}
    except json.JSONDecodeError:
        return {"raw": text, "error": "Failed to parse JSON from LLM output"}


# ── LangGraph state ───────────────────────────────────────────────────────────


class _PipelineState(TypedDict):
    book: Any  # CanonicalBook — avoid circular import at module load
    document_id: UUID
    agent_process_id: int
    session: Any  # AsyncSession
    result: AgentPipelineResult
    failed_lessons: list[str]  # lesson_ids that had at least one sub-agent failure


# ── CuratorAgent ─────────────────────────────────────────────────────────────


class CuratorAgent:
    """Orchestrates the Agent Pipeline over a CanonicalBook.

    For each lesson the orchestrator calls five sub-agents.  Sequential vs
    parallel execution is determined by the ``AGENT_PIPELINE_PARALLEL`` env var.
    """

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        self._llm = llm
        self._chain: Any = None

        shared_llm = self._llm  # may be None; sub-agents lazy-load via LLMFactory
        self._keywords_agent = KeywordsAgent(llm=shared_llm)
        self._summaries_agent = SummariesAgent(llm=shared_llm)
        self._flashcards_agent = FlashcardsAgent(llm=shared_llm)
        self._quizzes_agent = QuizzesAgent(llm=shared_llm)
        self._practice_agent = PracticeAgent(llm=shared_llm)

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            from learning_platform.agents.llm import LLMFactory
            from learning_platform.config import get_settings

            self._llm = LLMFactory.create(get_settings())
        return self._llm

    # ── Legacy backward-compat interface ──────────────────────────────────────

    def _build_chain(self) -> Any:
        if self._chain is None:
            prompt = RunnableLambda(_build_messages)
            parser = RunnableLambda(_parse_json)
            self._chain = prompt | self.llm | StrOutputParser() | parser
        return self._chain

    def analyze(self, lesson_text: str) -> dict[str, Any]:
        """Legacy: extract key_terms from lesson text (sync)."""
        chain = self._build_chain()
        return chain.invoke({"lesson_text": lesson_text})

    async def aanalyze(self, lesson_text: str) -> dict[str, Any]:
        """Legacy: extract key_terms from lesson text (async)."""
        chain = self._build_chain()
        return await chain.ainvoke({"lesson_text": lesson_text})

    # ── Agent Pipeline orchestration ──────────────────────────────────────────

    @staticmethod
    def _parallel_enabled() -> bool:
        return os.getenv("AGENT_PIPELINE_PARALLEL", "false").lower() == "true"

    @staticmethod
    def _extract_lesson_text(lesson: BookLesson) -> str:
        """Extract and concatenate all readable text from a BookLesson.

        The orchestrator is solely responsible for this — sub-agents receive
        plain strings and have no knowledge of BookLesson internals.
        """
        parts: list[str] = []
        for page in lesson.pages:
            for item in page.items:
                text = getattr(item, "content", None) or getattr(item, "items", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
                elif isinstance(text, list):
                    parts.extend(str(t) for t in text if str(t).strip())
        return "\n".join(parts)

    async def _run_sub_agents(
        self,
        lesson_id: UUID,
        lesson_title: str,
        lesson_text: str,
        document_id: UUID,
        agent_process_id: int,
        session: AsyncSession,
        result: AgentPipelineResult,
    ) -> None:
        """Dispatch all 5 sub-agents for one lesson.

        Sub-agents own their own skip-check, cleanup, DB write, and completion
        marker. They raise on LLM failure so this method propagates the error
        to the caller (lesson progress tracking in _build_graph).
        """
        if self._parallel_enabled():
            kw, sm, fl, qz, pr = await asyncio.gather(
                self._keywords_agent.run(
                    lesson_id=lesson_id,
                    lesson_title=lesson_title,
                    lesson_text=lesson_text,
                    document_id=document_id,
                    agent_process_id=agent_process_id,
                    session=session,
                ),
                self._summaries_agent.run(
                    lesson_id=lesson_id,
                    lesson_title=lesson_title,
                    lesson_text=lesson_text,
                    document_id=document_id,
                    agent_process_id=agent_process_id,
                    session=session,
                ),
                self._flashcards_agent.run(
                    lesson_id=lesson_id,
                    lesson_title=lesson_title,
                    lesson_text=lesson_text,
                    document_id=document_id,
                    agent_process_id=agent_process_id,
                    session=session,
                ),
                self._quizzes_agent.run(
                    lesson_id=lesson_id,
                    lesson_title=lesson_title,
                    lesson_text=lesson_text,
                    document_id=document_id,
                    agent_process_id=agent_process_id,
                    session=session,
                ),
                self._practice_agent.run(
                    lesson_id=lesson_id,
                    lesson_title=lesson_title,
                    lesson_text=lesson_text,
                    document_id=document_id,
                    agent_process_id=agent_process_id,
                    session=session,
                ),
            )
        else:
            kw: list[KeywordItem] = await self._keywords_agent.run(
                lesson_id=lesson_id,
                lesson_title=lesson_title,
                lesson_text=lesson_text,
                document_id=document_id,
                agent_process_id=agent_process_id,
                session=session,
            )
            sm: list[SummaryItem] = await self._summaries_agent.run(
                lesson_id=lesson_id,
                lesson_title=lesson_title,
                lesson_text=lesson_text,
                document_id=document_id,
                agent_process_id=agent_process_id,
                session=session,
            )
            fl: list[AgentFlashcard] = await self._flashcards_agent.run(
                lesson_id=lesson_id,
                lesson_title=lesson_title,
                lesson_text=lesson_text,
                document_id=document_id,
                agent_process_id=agent_process_id,
                session=session,
            )
            qz: list[QuizQuestion] = await self._quizzes_agent.run(
                lesson_id=lesson_id,
                lesson_title=lesson_title,
                lesson_text=lesson_text,
                document_id=document_id,
                agent_process_id=agent_process_id,
                session=session,
            )
            pr: list[PracticeQuestion] = await self._practice_agent.run(
                lesson_id=lesson_id,
                lesson_title=lesson_title,
                lesson_text=lesson_text,
                document_id=document_id,
                agent_process_id=agent_process_id,
                session=session,
            )

        result.keywords.extend(kw)
        result.summaries.extend(sm)
        result.flashcards.extend(fl)
        result.quiz_questions.extend(qz)
        result.practice_questions.extend(pr)

    def _build_graph(self) -> Any:
        """Build the LangGraph StateGraph for the agent pipeline."""
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
            ALL_AGENT_TYPES,
        )

        async def prepare(state: _PipelineState) -> _PipelineState:
            state["result"] = AgentPipelineResult(document_id=state["document_id"])
            state["failed_lessons"] = []
            return state

        async def process_lessons(state: _PipelineState) -> _PipelineState:
            book = state["book"]
            document_id = state["document_id"]
            agent_process_id = state["agent_process_id"]
            session = state["session"]
            result = state["result"]

            progress_repo = AgentLessonProgressRepository(session)
            completion_repo = AgentLessonCompletionRepository(session)

            for chapter in book.chapters:
                for lesson in chapter.lessons:
                    lesson_id_str = str(lesson.id)

                    # Check lesson-level progress
                    progress = await progress_repo.find(agent_process_id, lesson_id_str)
                    if progress and progress.status == "completed":
                        _LOG.debug(
                            "CuratorAgent: lesson %s already completed, skipping",
                            lesson.id,
                        )
                        continue

                    # Create progress row if first time
                    if not progress:
                        progress = await progress_repo.create(
                            agent_process_id,
                            str(document_id),
                            lesson_id_str,
                        )
                        await session.flush()

                    # Extract lesson text once — orchestrator's responsibility
                    lesson_text = self._extract_lesson_text(lesson)
                    if not lesson_text.strip():
                        _LOG.info(
                            "CuratorAgent: lesson %s has no text, marking completed",
                            lesson.id,
                        )
                        await progress_repo.mark_completed(progress)
                        await session.flush()
                        continue

                    # Dispatch all sub-agents — they raise on failure
                    try:
                        await self._run_sub_agents(
                            lesson_id=lesson.id,
                            lesson_title=lesson.title,
                            lesson_text=lesson_text,
                            document_id=document_id,
                            agent_process_id=agent_process_id,
                            session=session,
                            result=result,
                        )
                    except Exception as exc:
                        _LOG.exception("CuratorAgent: sub-agent failure for lesson %s", lesson.id)
                        # Determine which agents are still missing
                        completed = await completion_repo.find_completed_agents(
                            agent_process_id, lesson_id_str
                        )
                        missing = sorted(ALL_AGENT_TYPES - completed)
                        await progress_repo.mark_failed(progress, missing, str(exc))
                        await session.flush()
                        state["failed_lessons"].append(lesson_id_str)
                        continue  # continue to next lesson

                    # Check completion via markers (authoritative source of truth)
                    completed = await completion_repo.find_completed_agents(
                        agent_process_id, lesson_id_str
                    )
                    missing = sorted(ALL_AGENT_TYPES - completed)
                    if missing:
                        await progress_repo.mark_failed(
                            progress,
                            missing,
                            f"Missing completion markers for: {', '.join(missing)}",
                        )
                        await session.flush()
                        state["failed_lessons"].append(lesson_id_str)
                    else:
                        await progress_repo.mark_completed(progress)
                        await session.flush()

            return state

        async def finalize(state: _PipelineState) -> _PipelineState:
            r = state["result"]
            failed = state["failed_lessons"]
            _LOG.info(
                "CuratorAgent: pipeline complete for document %s — "
                "%d keywords, %d summaries, %d flashcards, %d quizzes, %d practice"
                " | failed_lessons=%d",
                state["document_id"],
                len(r.keywords),
                len(r.summaries),
                len(r.flashcards),
                len(r.quiz_questions),
                len(r.practice_questions),
                len(failed),
            )
            return state

        graph: StateGraph = StateGraph(_PipelineState)
        graph.add_node("prepare", prepare)
        graph.add_node("process_lessons", process_lessons)
        graph.add_node("finalize", finalize)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "process_lessons")
        graph.add_edge("process_lessons", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def run_pipeline(
        self,
        book: CanonicalBook,
        document_id: UUID,
        agent_process_id: int,
        session: AsyncSession,
    ) -> AgentPipelineResult:
        """Run the full agent pipeline over all lessons in a CanonicalBook.

        Args:
            book: The assembled canonical book to process.
            document_id: The document UUID (used to scope all output rows).
            agent_process_id: The lp_agent_process row id for this run.
            session: AsyncSession shared across all sub-agents for this run.

        Returns:
            AgentPipelineResult containing all sub-agent outputs.

        Raises:
            AgentPipelinePartialFailureError: if one or more lessons failed.
        """
        from learning_platform.pipeline.agent_pipeline import AgentPipelinePartialFailureError

        compiled = self._build_graph()
        initial_state: _PipelineState = {
            "book": book,
            "document_id": document_id,
            "agent_process_id": agent_process_id,
            "session": session,
            "result": AgentPipelineResult(document_id=document_id),
            "failed_lessons": [],
        }
        final_state: _PipelineState = await compiled.ainvoke(initial_state)

        if final_state["failed_lessons"]:
            raise AgentPipelinePartialFailureError(
                f"{len(final_state['failed_lessons'])} lesson(s) failed: "
                + ", ".join(final_state["failed_lessons"])
            )

        return final_state["result"]


if __name__ == "__main__":
    agent = CuratorAgent()

    while True:
        lesson_text = input("prompt 'exit' > ")
        if lesson_text == "exit":
            break
        response: dict[str, Any] = agent.analyze(lesson_text)
        print(f"{lesson_text} \n")
        print(f" {response}")

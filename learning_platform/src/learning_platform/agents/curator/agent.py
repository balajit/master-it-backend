"""Curator agent — analyzes lessons and extracts structured learning metadata.

The Curator agent uses LangChain to orchestrate LLM calls for educational
content analysis.  It supports multiple LLM providers (Ollama, OpenAI,
Anthropic) through the LLMFactory adapter.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


# ── Synthesized System Prompt ────────────────────────────────────────────────
# Generated from the specialized sub-prompts in prompts.txt.
# This single system prompt replaces the need for prompt composition at runtime.
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
# SYSTEM_PROMPT = """You are an educational content analysis assistant.
#
# Your task is to analyze a lesson and extract structured learning metadata.
#
# Analyze the lesson from a student's learning perspective.
#
# Goals:
# 1. Identify important vocabulary and terms.
# 2. Extract the core concepts being taught.
# 3. Estimate learning difficulty.
# 4. Classify formulas and scientific expressions.
# 5. Generate explanations and learning questions.
#
# Rules:
# - Do not invent facts that are not supported by the lesson.
# - Preserve technical accuracy.
# - Distinguish between examples and core concepts.
# - Prefer concepts that help a student understand the subject.
# - Return only valid JSON matching the required schema.
#
# ---
#
# ## Key Terms
#
# Identify terms that:
# - students should remember
# - are introduced or defined
# - represent important vocabulary
# - are likely to appear in exams
#
# Do not include:
# - common words
# - names of examples
# - incidental nouns
#
# Each key term must include:
# - term: the vocabulary word or phrase
# - definition: a clear, concise explanation
# - importance: "high", "medium", or "low"
# - confidence: a float between 0.0 and 1.0 indicating extraction confidence
#
# ---
#
# ## Concepts
#
# Extract the main concepts.
#
# For each concept provide:
# - name: the concept name
# - description: a clear explanation of the concept
# - prerequisites: concepts a student must understand first
# - importance: "core", "supporting", or "supplementary"
#
# Prefer concepts that help a student understand the subject.
# Distinguish between examples and core concepts.
# Do not invent facts not supported by the lesson.
#
# ---
#
# ## Difficulty
#
# Estimate educational difficulty.
#
# Consider:
# - abstraction level
# - mathematical complexity
# - required prior knowledge
# - number of concepts introduced
# - conceptual density
#
# Difficulty levels:
# - beginner: introductory material, minimal prerequisites
# - intermediate: assumes foundational knowledge, moderate complexity
# - advanced: deep domain knowledge, abstract reasoning required
# - expert: cutting-edge or highly specialized content
#
# Provide:
# - level: one of beginner, intermediate, advanced, expert
# - score: integer from 1 (easiest) to 10 (hardest)
# - reasoning: list of factors that influenced the estimate
# - prerequisites: list of prerequisite knowledge areas
#
# ---
#
# ## Formulas
#
# For each formula or scientific expression:
#
# Identify:
# - expression: the mathematical expression as it appears
# - normalized_expression: normalized LaTeX representation
# - domain: list of scientific domains (e.g., thermodynamics, chemistry, physics)
# - primary_domain: the single most relevant domain
# - type: classification — mathematical, physical_quantity, chemical_equation,
#         engineering_formula, or statistical_expression
# - explanation: what the formula represents
#
# Do not assume chemistry just because chemical symbols appear.
# Use lesson context to determine the correct domain classification.
#
# ---
#
# ## Explanations
#
# Generate explanations at multiple levels for each key concept:
#
# simple:
# - beginner friendly
# - minimal jargon
# - uses everyday language and analogies
#
# intermediate:
# - appropriate for the lesson level
# - uses standard terminology
# - builds on prerequisite knowledge
#
# advanced:
# - technically precise
# - includes mathematical or formal definitions
# - suitable for expert review
#
# ---
#
# ## Questions
#
# Generate learning questions of varying types and difficulties:
#
# Types:
# - recall: memory-based questions about facts and definitions
# - conceptual: understanding-based questions about relationships
# - application: using knowledge to solve problems
# - reasoning: analytical questions requiring deeper thinking
#
# For each question provide:
# - type: one of recall, conceptual, application, reasoning
# - question: the question text
# - difficulty: easy, medium, or hard
# - answer: a clear, correct answer
# - related_concept: which concept this question assesses"""


USER_PROMPT_TEMPLATE = """Analyze the following lesson.

LESSON:
---------------
{lesson_text}
---------------

Return JSON
"""
# "concepts": [],
# "difficulty": {{}},
# "formulas": [],
# "explanations": [],
# "questions": []

def _build_messages(inputs: dict[str, Any]) -> list[SystemMessage | HumanMessage]:
    """Build message list from inputs for the LLM."""
    user_prompt = USER_PROMPT_TEMPLATE.format(lesson_text=inputs["lesson_text"])
    #print(f'number of tokens: {user_prompt.split(" ").count()}')
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]


def _parse_json(text: str) -> dict[str, Any]:
    """Parse the text output from the LLM into a dictionary."""
    return _extract_json(text)


class CuratorAgent:
    """Educational content analysis agent.

    Extracts structured learning metadata from lesson text using an LLM.

    Usage::

        from learning_platform.agents.llm import LLMFactory
        from learning_platform.agents.curator import CuratorAgent
        from learning_platform.config import get_settings

        settings = get_settings()
        llm = LLMFactory.create(settings)
        agent = CuratorAgent(llm=llm)

        result = agent.analyze(lesson_text)
        print(result["key_terms"])
    """

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        """Initialize the curator agent.

        Args:
            llm: A LangChain chat model instance.  If None, the agent
                 will use LLMFactory with default settings when analyze()
                 is called.
        """
        self._llm = llm
        self._chain = None

    @property
    def llm(self) -> BaseChatModel:
        """Lazy-load the LLM instance."""
        if self._llm is None:
            from learning_platform.agents.llm import LLMFactory
            from learning_platform.config import get_settings

            self._llm = LLMFactory.create(get_settings())
        return self._llm

    def _build_chain(self) -> Any:
        """Build the LangChain chain (cached)."""
        if self._chain is None:
            prompt = RunnableLambda(_build_messages)
            parser = RunnableLambda(_parse_json)
            self._chain = prompt | self.llm | StrOutputParser() | parser
        return self._chain

    def analyze(self, lesson_text: str) -> dict[str, Any]:
        """Analyze a lesson and extract structured learning metadata.

        Args:
            lesson_text: The full text content of the lesson to analyze.

        Returns:
            A dictionary with keys: key_terms, concepts, difficulty,
            formulas, explanations, questions.
        """
        chain = self._build_chain()
        return chain.invoke({"lesson_text": lesson_text})

    async def aanalyze(self, lesson_text: str) -> dict[str, Any]:
        """Async version of analyze().

        Args:
            lesson_text: The full text content of the lesson to analyze.

        Returns:
            A dictionary with keys: key_terms, concepts, difficulty,
            formulas, explanations, questions.
        """
        chain = self._build_chain()
        return await chain.ainvoke({"lesson_text": lesson_text})


def _extract_json(text: str) -> dict[str, Any]:
    """Extract and parse JSON from LLM output.

    Handles cases where the LLM wraps JSON in markdown code blocks
    or includes preamble text before the JSON.
    """
    cleaned = text.strip()

    # Try to extract from markdown code blocks
    if "```" in cleaned:
        start = cleaned.find("```")
        # Skip the opening ``` and optional language tag
        next_newline = cleaned.find("\n", start)
        if next_newline != -1:
            end = cleaned.rfind("```")
            if end > next_newline:
                cleaned = cleaned[next_newline + 1 : end].strip()

    # Find the first { and last }
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


if __name__ == "__main__":
    agent = CuratorAgent()

    while True:
        lesson_text = input("prompt 'exit' > ")
        if lesson_text == "exit":
            break
        response : dict[str, Any] = agent.analyze(lesson_text)
        print(f"{lesson_text} \n")
        print(f" {response}")



#!/usr/bin/env python3
"""Agent CLI driver — interactive tool for testing learning-platform agents.

Usage:
    uv run learning_platform/src/learning_platform/agents/driver.py
    uv run learning_platform/src/learning_platform/agents/driver.py \
        --file lesson.txt
    uv run learning_platform/src/learning_platform/agents/driver.py \
        --provider openai --model gpt-4o
    uv run learning_platform/src/learning_platform/agents/driver.py \
        --agent reviewer --file lesson.txt
    uv run learning_platform/src/learning_platform/agents/driver.py \
        --agent reviewer --document-id doc_123 --page-range 7-10
    uv run learning_platform/src/learning_platform/agents/driver.py \
        --agent reviewer --document-id 00000000-0000-0000-0000-000000000001 --page-range 1-2

Environment variables:
    LLM_PROVIDER: Provider name (ollama | openai | anthropic)
    LLM_MODEL: Model name for the chosen provider
    LLM_BASE_URL: Base URL for Ollama (default: http://localhost:11434)
    OPENAI_API_KEY: API key for OpenAI provider
    ANTHROPIC_API_KEY: API key for Anthropic provider
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from learning_platform.agents.curator.agent import CuratorAgent
from learning_platform.agents.llm.adapter import LLMFactory
from learning_platform.agents.reviewer import ReviewerAgent
from learning_platform.agents.reviewer_models import (
    ReviewerDocumentReviewRequest,
    ReviewPageRangeRequest,
)
from learning_platform.config import Settings


def build_settings(args: argparse.Namespace) -> Settings:
    """Build Settings from CLI arguments, overriding defaults."""
    overrides: dict[str, Any] = {}

    if args.provider:
        overrides["llm_provider"] = args.provider
    if args.model:
        overrides["llm_model"] = args.model
    if args.base_url:
        overrides["llm_base_url"] = args.base_url

    return Settings(**overrides)


def print_result(result: dict[str, Any]) -> None:
    """Pretty-print the analysis result."""
    if isinstance(result.get("page_reviews"), list):
        print(f"\n{'=' * 60}")
        print("  DOCUMENT REVIEW")
        print(f"{'=' * 60}")
        _print_dict(result, indent=2)
        return

    sections = [
        ("KEY TERMS", "key_terms"),
        ("CONCEPTS", "concepts"),
        ("DIFFICULTY", "difficulty"),
        ("FORMULAS", "formulas"),
        ("EXPLANATIONS", "explanations"),
        ("QUESTIONS", "questions"),
    ]

    for title, key in sections:
        value = result.get(key)
        if value is None:
            continue

        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

        if isinstance(value, list):
            for i, item in enumerate(value, 1):
                print(f"\n  [{i}]")
                _print_dict(item, indent=4)
        elif isinstance(value, dict):
            _print_dict(value, indent=4)
        else:
            print(f"  {value}")

    # Check for parse errors
    if "error" in result:
        print(f"\n  WARNING: {result['error']}")
        if "raw" in result:
            print(f"\n  Raw output:\n{result['raw']}")


def _print_dict(d: Any, indent: int = 0) -> None:
    """Recursively print a dictionary with indentation."""
    prefix = " " * indent
    if isinstance(d, dict):
        for key, val in d.items():
            if isinstance(val, (dict, list)):
                print(f"{prefix}{key}:")
                _print_dict(val, indent + 2)
            else:
                print(f"{prefix}{key}: {val}")
    elif isinstance(d, list):
        for i, item in enumerate(d):
            if isinstance(item, dict):
                print(f"{prefix}[{i + 1}]:")
                _print_dict(item, indent + 2)
            else:
                print(f"{prefix}- {item}")
    else:
        print(f"{prefix}{d}")


def create_agent(agent_name: str, llm: Any) -> Any:
    """Create an agent instance by name."""
    normalized_name = agent_name.strip().lower()
    if normalized_name == "curator":
        return CuratorAgent(llm=llm)
    if normalized_name == "reviewer":
        return ReviewerAgent(llm=llm)
    raise ValueError(f"Unsupported agent '{agent_name}'")


def run_agent(agent: Any, content: str) -> dict[str, Any]:
    """Run agent using supported sync method."""
    if hasattr(agent, "review"):
        return agent.review(content)
    if hasattr(agent, "analyze"):
        return agent.analyze(content)
    raise TypeError("Agent must define review() or analyze()")


def should_use_reviewer_document_mode(args: argparse.Namespace) -> bool:
    """Validate whether reviewer document mode should run."""
    has_document_id = bool(args.document_id)
    has_page_ranges = bool(args.page_range)
    has_any_doc_flags = has_document_id or has_page_ranges

    if args.agent != "reviewer" and has_any_doc_flags:
        raise ValueError("reviewer document flags require --agent reviewer")

    if not has_any_doc_flags:
        return False

    if not has_document_id:
        raise ValueError("--document-id is required for reviewer document mode")

    if not has_page_ranges:
        raise ValueError("At least one --page-range must be provided")

    if args.file:
        raise ValueError("--file cannot be combined with reviewer document mode flags")

    return True


def run_reviewer_document_review(
    agent: Any,
    *,
    lp_documents_id: str | None,
    page_ranges: list[str],
) -> dict[str, Any]:
    """Run reviewer document workflow via managed-doc MCP tools."""
    if not hasattr(agent, "areview_document"):
        raise TypeError("Reviewer document mode requires areview_document()")

    parsed_ranges: list[ReviewPageRangeRequest] = []
    for raw_range in page_ranges:
        start_text, sep, end_text = raw_range.partition("-")
        if sep != "-":
            raise ValueError(f"Invalid --page-range format: {raw_range}")
        parsed_ranges.append(
            ReviewPageRangeRequest(
                start_page=int(start_text),
                end_page=int(end_text),
            )
        )

    request = ReviewerDocumentReviewRequest(
        lp_documents_id=str(lp_documents_id),
        page_ranges=parsed_ranges,
    )

    return asyncio.run(agent.areview_document(request))


def interactive_mode(agent: Any, agent_name: str) -> None:
    """Run the agent in interactive mode — read content from stdin."""
    print(f"{agent_name.title()} Agent — Interactive Mode")
    print("=" * 40)
    print("Paste or type your content below.")
    print("When done, enter an empty line followed by 'END' on its own line.")
    print()

    lines: list[str] = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return

        if line.strip() == "END":
            break
        lines.append(line)

    content = "\n".join(lines).strip()
    if not content:
        print("No content provided.")
        return

    print(f"\nProcessing content ({len(content)} characters)...\n")

    try:
        result = run_agent(agent, content)
        print_result(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def file_mode(agent: Any, filepath: str) -> None:
    """Run the agent on a file."""
    try:
        with open(filepath) as f:
            lesson_text = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing file: {filepath} ({len(lesson_text)} characters)...\n")

    try:
        result = run_agent(agent, lesson_text)
        print_result(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Learning Platform Agent Driver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--file",
        "-f",
        help="Path to a file containing lesson text to analyze",
    )
    parser.add_argument(
        "--document-id",
        help="LP document id (lp_documents.id) for reviewer document mode",
    )
    parser.add_argument(
        "--page-range",
        action="append",
        help="Inclusive page range as START-END (repeatable)",
    )
    parser.add_argument(
        "--agent",
        choices=["curator", "reviewer"],
        default="curator",
        help="Agent to run (default: curator)",
    )
    parser.add_argument(
        "--provider",
        "-p",
        choices=["ollama", "openai", "anthropic"],
        help="LLM provider (default: from env LLM_PROVIDER or ollama)",
    )
    parser.add_argument(
        "--model",
        "-m",
        help="Model name for the chosen provider",
    )
    parser.add_argument(
        "--base-url",
        help="Base URL for Ollama (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text",
    )

    args = parser.parse_args()
    settings = build_settings(args)

    print(f"Provider: {settings.llm_provider}")
    print(f"Model:    {settings.llm_model}")
    print(f"Agent:    {args.agent}")
    print()

    try:
        llm = LLMFactory.create(settings)
        agent = create_agent(args.agent, llm)
    except Exception as exc:
        print(f"Failed to initialize LLM: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        use_doc_mode = should_use_reviewer_document_mode(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if use_doc_mode:
        try:
            result = run_reviewer_document_review(
                agent,
                lp_documents_id=args.document_id,
                page_ranges=[str(value) for value in (args.page_range or [])],
            )
            print_result(result)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if args.file:
        file_mode(agent, args.file)
    else:
        interactive_mode(agent, args.agent)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Curator agent CLI driver — interactive tool for testing the Curator agent.

Usage:
    uv run learning_platform/src/learning_platform/agents/driver.py
    uv run learning_platform/src/learning_platform/agents/driver.py \
        --file lesson.txt
    uv run learning_platform/src/learning_platform/agents/driver.py \
        --provider openai --model gpt-4o

Environment variables:
    LLM_PROVIDER: Provider name (ollama | openai | anthropic)
    LLM_MODEL: Model name for the chosen provider
    LLM_BASE_URL: Base URL for Ollama (default: http://localhost:11434)
    OPENAI_API_KEY: API key for OpenAI provider
    ANTHROPIC_API_KEY: API key for Anthropic provider
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from learning_platform.agents.curator.agent import CuratorAgent
from learning_platform.agents.llm.adapter import LLMFactory
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


def interactive_mode(agent: CuratorAgent) -> None:
    """Run the agent in interactive mode — read lesson text from stdin."""
    print("Curator Agent — Interactive Mode")
    print("=" * 40)
    print("Paste or type your lesson text below.")
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

    lesson_text = "\n".join(lines).strip()
    if not lesson_text:
        print("No lesson text provided.")
        return

    print(f"\nAnalyzing lesson ({len(lesson_text)} characters)...\n")

    try:
        result = agent.analyze(lesson_text)
        print_result(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def file_mode(agent: CuratorAgent, filepath: str) -> None:
    """Run the agent on a file."""
    try:
        with open(filepath) as f:
            lesson_text = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing file: {filepath} ({len(lesson_text)} characters)...\n")

    try:
        result = agent.analyze(lesson_text)
        print_result(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Curator Agent — Educational Content Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--file",
        "-f",
        help="Path to a file containing lesson text to analyze",
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
    print()

    try:
        llm = LLMFactory.create(settings)
        agent = CuratorAgent(llm=llm)
    except Exception as exc:
        print(f"Failed to initialize LLM: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.file:
        file_mode(agent, args.file)
    else:
        interactive_mode(agent)


if __name__ == "__main__":
    main()

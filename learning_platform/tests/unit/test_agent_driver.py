from __future__ import annotations

import argparse
from typing import Any

import pytest

from learning_platform.agents.driver import (
    build_settings,
    create_agent,
    run_agent,
    run_reviewer_document_review,
    should_use_reviewer_document_mode,
)


class _CuratorLikeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def analyze(self, content: str) -> dict[str, Any]:
        self.calls.append(content)
        return {"mode": "analyze", "content": content}


class _ReviewerLikeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def review(self, content: str) -> dict[str, Any]:
        self.calls.append(content)
        return {"mode": "review", "content": content}


class _InvalidAgent:
    pass


class _ReviewerDocumentAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def areview_document(
        self,
        request: Any,
    ) -> dict[str, Any]:
        payload = {
            "lp_documents_id": str(getattr(request, "lp_documents_id", "")),
            "page_ranges": [
                {
                    "start_page": item.start_page,
                    "end_page": item.end_page,
                }
                for item in getattr(request, "page_ranges", [])
            ],
        }
        self.calls.append(payload)
        return {
            "aggregate_verdict": "approved",
            "page_reviews": [],
            "slices": [],
            "resolved_lp_documents_id": "00000000-0000-0000-0000-000000000001",
            "resolved_document_name": "unit.pdf",
            "metadata": payload,
        }


def test_build_settings_applies_overrides() -> None:
    args = argparse.Namespace(provider="openai", model="gpt-4o-mini", base_url="http://x")
    settings = build_settings(args)
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.llm_base_url == "http://x"


def test_create_agent_curator(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent = _CuratorLikeAgent()
    monkeypatch.setattr(
        "learning_platform.agents.driver.CuratorAgent",
        lambda llm: fake_agent,
    )
    created = create_agent("curator", llm=object())
    assert created is fake_agent


def test_create_agent_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent = _ReviewerLikeAgent()
    monkeypatch.setattr(
        "learning_platform.agents.driver.ReviewerAgent",
        lambda llm: fake_agent,
    )
    created = create_agent("reviewer", llm=object())
    assert created is fake_agent


def test_create_agent_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported agent"):
        create_agent("unknown", llm=object())


def test_run_agent_prefers_review_when_available() -> None:
    agent = _ReviewerLikeAgent()
    result = run_agent(agent, "hello")
    assert result["mode"] == "review"
    assert agent.calls == ["hello"]


def test_run_agent_falls_back_to_analyze() -> None:
    agent = _CuratorLikeAgent()
    result = run_agent(agent, "hello")
    assert result["mode"] == "analyze"
    assert agent.calls == ["hello"]


def test_run_agent_rejects_agent_without_supported_methods() -> None:
    with pytest.raises(TypeError, match="review\(\) or analyze\(\)"):
        run_agent(_InvalidAgent(), "hello")


def test_should_use_reviewer_document_mode_false_without_flags() -> None:
    args = argparse.Namespace(
        agent="reviewer",
        document_id=None,
        page_range=None,
        file=None,
    )
    assert should_use_reviewer_document_mode(args) is False


def test_should_use_reviewer_document_mode_true_with_complete_flags() -> None:
    args = argparse.Namespace(
        agent="reviewer",
        document_id="00000000-0000-0000-0000-000000000001",
        page_range=["2-4"],
        file=None,
    )
    assert should_use_reviewer_document_mode(args) is True


def test_should_use_reviewer_document_mode_rejects_non_reviewer() -> None:
    args = argparse.Namespace(
        agent="curator",
        document_id="00000000-0000-0000-0000-000000000001",
        page_range=["2-4"],
        file=None,
    )
    with pytest.raises(ValueError, match="require --agent reviewer"):
        _ = should_use_reviewer_document_mode(args)


def test_should_use_reviewer_document_mode_requires_document_id() -> None:
    args = argparse.Namespace(
        agent="reviewer",
        document_id=None,
        page_range=["2-4"],
        file=None,
    )
    with pytest.raises(ValueError, match="--document-id is required"):
        _ = should_use_reviewer_document_mode(args)


def test_should_use_reviewer_document_mode_requires_page_ranges() -> None:
    args = argparse.Namespace(
        agent="reviewer",
        document_id="00000000-0000-0000-0000-000000000001",
        page_range=None,
        file=None,
    )
    with pytest.raises(ValueError, match="At least one --page-range"):
        _ = should_use_reviewer_document_mode(args)


def test_should_use_reviewer_document_mode_rejects_file_combo() -> None:
    args = argparse.Namespace(
        agent="reviewer",
        document_id="00000000-0000-0000-0000-000000000001",
        page_range=["2-4"],
        file="lesson.txt",
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        _ = should_use_reviewer_document_mode(args)


def test_run_reviewer_document_review_invokes_agent() -> None:
    agent = _ReviewerDocumentAgent()
    result = run_reviewer_document_review(
        agent,
        lp_documents_id="00000000-0000-0000-0000-000000000001",
        page_ranges=["7-10"],
    )
    assert result["aggregate_verdict"] == "approved"
    assert len(agent.calls) == 1
    assert agent.calls[0]["lp_documents_id"] == "00000000-0000-0000-0000-000000000001"
    assert agent.calls[0]["page_ranges"] == [{"start_page": 7, "end_page": 10}]


def test_run_reviewer_document_review_rejects_invalid_agent() -> None:
    with pytest.raises(TypeError, match="areview_document"):
        _ = run_reviewer_document_review(
            _ReviewerLikeAgent(),
            lp_documents_id="00000000-0000-0000-0000-000000000001",
            page_ranges=["1-1"],
        )


def test_run_reviewer_document_review_rejects_bad_range_format() -> None:
    agent = _ReviewerDocumentAgent()
    with pytest.raises(ValueError, match="Invalid --page-range format"):
        _ = run_reviewer_document_review(
            agent,
            lp_documents_id="00000000-0000-0000-0000-000000000001",
            page_ranges=["1:2"],
        )

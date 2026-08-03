"""Service wrapper for running triage via MCP reports."""

from __future__ import annotations

from learning_platform.agentic_ops.contracts.mcp import ReportScope
from learning_platform.agentic_ops.mcp.client import McpReportClient
from learning_platform.agentic_ops.rules.defaults import build_default_rule_set
from learning_platform.agentic_ops.settings import AgenticOpsSettings
from learning_platform.agentic_ops.triage.agent import TriageAgent
from learning_platform.agentic_ops.triage.models import TriageResult


class TriageService:
    """Construct and execute deterministic triage flows."""

    def __init__(self, settings: AgenticOpsSettings) -> None:
        self._settings = settings

    async def run(self, scope: ReportScope) -> TriageResult:
        provider = McpReportClient(
            endpoint=self._settings.report_mcp_endpoint,
            timeout_seconds=self._settings.mcp_timeout_seconds,
            api_key=self._settings.report_mcp_api_key,
        )
        agent = TriageAgent(
            provider=provider,
            rule_set=build_default_rule_set(),
            page_size=self._settings.max_rows_per_page,
            include_rows=self._settings.include_rows,
        )
        return await agent.run(scope)

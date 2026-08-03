"""Runtime settings for agentic operations."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class AgenticOpsSettings(BaseSettings):
    """Settings for deterministic triage workflows."""

    mcp_endpoint: str = Field(default="http://localhost:8765/mcp/lp/reporting")
    mcp_api_key: str | None = Field(default=None)
    action_mcp_endpoint: str = Field(default="http://localhost:8766/mcp/lp/actions")
    mcp_timeout_seconds: float = Field(default=30.0, gt=0.0)
    action_mcp_api_key: str | None = Field(default=None)
    max_rows_per_page: int = Field(default=500, ge=1, le=5000)
    include_rows: bool = Field(default=False)
    allow_corrective_actions: bool = Field(default=False)
    action_ttl_minutes: int = Field(default=30, ge=1, le=1440)
    mcp_managed_docs: str = Field(
        default="agentic_ops_managed_docs",
        validation_alias="MCP_MANAGED_DOCS",
    )
    mcp_max_input_size_bytes: int = Field(default=30 * 1024 * 1024, ge=1)
    mcp_max_pages_per_slice: int = Field(default=50, ge=1, le=1000)
    mcp_max_base64_return_bytes: int = Field(default=8 * 1024 * 1024, ge=1)

    @property
    def report_mcp_endpoint(self) -> str:
        """Alias for report MCP endpoint."""
        return self.mcp_endpoint

    @property
    def report_mcp_api_key(self) -> str | None:
        """Alias for report MCP API key."""
        return self.mcp_api_key

    model_config = {
        "env_prefix": "AGENTIC_OPS_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

# Design: Diagnosis API + Controlled Destructive Actions

## Context

The system has two data planes (`src` master models and `learning_platform` LP models) and now needs both:

- Deterministic read-only triage across both planes.
- Controlled destructive operations with explicit safety gates and rollback data.

## Scope

This design defines:

1. Diagnosis-first backend API surface for deterministic triage and findings.
2. Dual MCP server topology (report vs action).
3. Typed prepare/execute/cancel/rollback contracts for destructive operations.
4. Rollback persistence model and action lifecycle state machine.
5. Current implementation for deleting `lp_document_process` + related `lp_pipeline_logs` rows.
6. Core managed-document capability for ingesting PDFs, slicing page ranges, and exposing inventory for agents.
7. Reviewer document-page workflow orchestration and persistence for run/page review traces.

## Goals / Non-Goals

**Goals**

- Keep reporting tools strictly read-only.
- Separate destructive tools onto a dedicated MCP surface.
- Require two-step destructive flow (`prepare` before `execute`) through one endpoint with `confirm`.
- Support explicit cancel operation for prepared actions.
- Persist undo payload before destructive write.
- Support explicit rollback operation.
- Keep triage workflows unchanged and deterministic.
- Provide a single mode-driven page slicing tool for any agent (`path` or `base64`).
- Persist all tool-ingested originals and generated slices under MCP-managed storage.
- Expose managed-document inventory so agents can decide whether upload/ingest is needed.

**Non-goals**

- Automatic destructive remediation by triage itself.
- Multi-action orchestration from the backend API in this phase.
- Cross-repo split of agentic subsystem.
- Introducing managed-doc capability into public `src/` API schemas.

## Decisions

### D1. Two MCP server boundaries

- **Report server** (`reporting_server.py`) exposes only `db.report_*` tools.
- **Action server** (`action_server.py`) exposes only `ops.*` destructive tools.

Rationale: hard boundary between diagnostics and writes.

### D2. Mandatory prepare/execute/rollback lifecycle

Destructive action calls must follow:

- `ops.prepare_delete_document_process_runs`
- `ops.execute_delete_document_process_runs`
- optional `ops.cancel_agent_action`
- optional `ops.rollback_agent_action`

Execute never accepts raw row IDs; it accepts an `action_id` returned from prepare.

At the backend API layer, delete operations use a single endpoint:

- `POST /api/v1/triage/diagnoses/{diagnosis_id}/actions/delete-document-process-runs`
  - `confirm=false` and `process_ids` -> prepare
  - `confirm=true` and `action_id` -> execute

### D3. Rollback-first persistence

Before execute is allowed, prepare stores undo payload in `lp_roll_back_agent_action`:

- full target row snapshots,
- deterministic target key,
- requester,
- integrity hash,
- precheck result,
- expiry.

### D4. Idempotency and ownership checks

- A deterministic `target_key` is derived from normalized actioned `process_ids`.
- only one `prepared` action may exist for a given `target_key`.
- repeated prepare for the same item set returns existing `prepared` action (`already_prepared`).
- cancel is allowed for any authorized caller.
- `requested_by` is retained for audit/security logging, not action identity.

### D5. Diagnosis-first public API naming

- `POST /api/v1/triage/diagnoses`
- `GET /api/v1/triage/diagnoses/{diagnosis_id}`
- `GET /api/v1/triage/diagnoses/{diagnosis_id}/findings`

Backward-compatible aliases remain in service/repository/router internals while callers migrate.

### D6. Managed-doc capability is an independent LP capability, exposed via MCP action tools

- Core implementation lives in:
  - `learning_platform/src/learning_platform/capabilities/managed_docs/service.py`
- MCP action tool layer exposes:
  - `ops.slice_document_pages`
  - `ops.list_managed_documents`

Design choices:

- one field `mode` controls both request source and response shape:
  - `mode=path`: request must provide absolute `source_path`; response returns `sliced_path` and no base64 payload
  - `mode=base64`: request must provide `source_pdf_base64`; response returns `sliced_pdf_base64` and no sliced path
- originals are always persisted first in MCP-managed storage (`orig/`) for both modes.
- slices are always persisted in MCP-managed storage (`sliced/`) before response.

Rationale: keeps capability transport-agnostic and reusable for all agents while preserving deterministic storage and auditability.

### D7. Reviewer workflow uses LangGraph with deterministic precheck and persistent run/page traces

- Reviewer execution is orchestrated by a LangGraph state machine in `ReviewerAgent`.
- The graph performs:
  - request context preparation (LP doc resolution + canonical page loading),
  - explicit run creation (`lp_reviewer_run`),
  - per-page review loop with deterministic verifier gate,
  - run completion/failure persistence.
- Per-page results are persisted for every requested page (including non-reviewed statuses like `canonical_missing` and `deterministic_mismatch`) to preserve full traceability.

Rationale: deterministic state transitions and durable run/page records make reviewer behavior auditable and reproducible.

## Data Model

### Table: `lp_roll_back_agent_action`

Key fields:

- `id` (UUID string PK)
- `action_type`
- `tool_name`
- `status` (`prepared`, `applied`, `rolled_back`, `execute_failed`, `rollback_failed`)
- `reason`
- `requested_by`
- `target_key`
- `precheck_passed`
- `target_summary` (JSON)
- `undo_steps` (JSON)
- `integrity_hash` (sha256)
- `affected_row_count`
- `affected_file_count`
- `error_message`
- `prepared_at`, `applied_at`, `canceled_at`, `rolled_back_at`, `expires_at`
- `created_at`, `updated_at`

Indexes:

- `idx_lp_roll_back_agent_action_status`
- `idx_lp_roll_back_agent_action_created_at`
- `idx_lp_roll_back_agent_action_action_type`
- `uq_lp_roll_back_agent_action_prepared_target_key` (partial unique index where `status='prepared'`)

Migration:

- `alembic/versions/f9c1a2b3d4e5_add_lp_roll_back_agent_action_table.py`

### Table: `lp_reviewer_run`

Key fields:

- `id` (UUID PK)
- `requested_lp_documents_id` (UUID)
- `resolved_lp_documents_id` (UUID FK -> `lp_documents.id`)
- `resolved_document_name`
- `status` (`processing`, `completed`, `failed`)
- `aggregate_verdict` (nullable)
- `aggregate_summary`
- `metadata` (JSON)
- `error_message` (nullable)
- `created_at`, `updated_at`

Indexes:

- `ix_lp_reviewer_run_requested_lp_documents_id`
- `ix_lp_reviewer_run_resolved_lp_documents_id`
- `ix_lp_reviewer_run_status`

### Table: `lp_reviewer_page_result`

Key fields:

- `id` (int PK)
- `reviewer_run_id` (UUID FK -> `lp_reviewer_run.id`)
- `lp_documents_id` (UUID FK -> `lp_documents.id`)
- `page_number`
- `review_status`
- `review_error` (nullable)
- `extracted_text_char_count`
- `summary`
- `strengths` (JSON)
- `issues` (JSON)
- `recommendations` (JSON)
- `verdict` (nullable)
- `confidence` (nullable)
- `metadata` (JSON)
- `created_at`

Indexes:

- `ix_lp_reviewer_page_result_reviewer_run_id`
- `ix_lp_reviewer_page_result_lp_documents_id`
- `ix_lp_reviewer_page_result_review_status`

Migration:

- `alembic/versions/a8d9e7c6b5a4_add_lp_reviewer_run_tables.py`

## Contracts

Implemented in `learning_platform/src/learning_platform/agentic_ops/contracts/mcp.py`.

### Request models

- `PrepareDeleteDocumentProcessRunsRequest`
  - `process_ids: list[int]`
  - `reason: str`
  - `requested_by: str`
- `ExecuteDeleteDocumentProcessRunsRequest`
  - `action_id: str`
  - `requested_by: str`
- `CancelAgentActionRequest`
  - `action_id: str`
  - `requested_by: str`
  - `reason: str`
- `RollBackAgentActionRequest`
  - `action_id: str`
  - `requested_by: str`
  - `reason: str`
- `SliceDocumentPagesRequest`
  - `mode: path | base64`
  - `start_page: int`
  - `end_page: int`
  - `source_path: str | None`
  - `source_pdf_base64: str | None`
  - `filename: str | None`

### Result models

- `PreparedAgentActionResult`
  - `status: prepared | already_prepared`
  - includes requested/target/missing IDs and integrity hash
- `ExecutedAgentActionResult`
  - `status: applied | already_applied`
  - includes deleted IDs and deleted pipeline-log count
- `CanceledAgentActionResult`
  - `status: canceled | already_canceled`
  - includes `canceled_at`
- `RolledBackAgentActionResult`
  - `status: rolled_back | already_rolled_back`
  - includes restored row count
- `SliceDocumentPagesResult`
  - `doc_id: str`
  - `mode: path | base64`
  - `orig_filename`, `orig_path`
  - `sliced_filename`
  - `sliced_path: str | None`
  - `sliced_pdf_base64: str | None`
  - page range and hash metadata
- `ManagedDocumentEntry`
  - managed inventory entry returned by `ops.list_managed_documents`
  - includes filename/path/size/hash/page count/source metadata

## Runtime Components

### `AgenticActionService`

Path: `learning_platform/src/learning_platform/agentic_ops/actions/service.py`

Responsibilities:

- validate action lifecycle state transitions,
- gather target rows and related pipeline logs during prepare,
- derive deterministic target key from normalized process IDs,
- create undo steps and integrity hash,
- perform destructive delete during execute,
- support explicit cancel of prepared actions,
- restore rows from undo steps during rollback,
- mark failure statuses on execute/rollback errors.

### `ReviewerAgent` (LangGraph orchestration)

Path: `learning_platform/src/learning_platform/agents/reviewer.py`

Responsibilities:

- maintain LP-ID strict request/response semantics (`lp_documents_id` only),
- orchestrate reviewer workflow through LangGraph nodes,
- enforce `max_pages_per_request` before review loop,
- run deterministic verifier before LLM review,
- persist `lp_reviewer_run` and `lp_reviewer_page_result` lifecycle/output rows,
- preserve non-fail-fast per-page behavior while still marking run-level failures on orchestration/persistence errors.

### Report server

Path: `learning_platform/src/learning_platform/agentic_ops/mcp_server/reporting_server.py`

- exposes only read-only tools:
  - `db.report_all_entries`
  - `db.report_missing_entries`
  - `db.report_table_page`

### Action server

Path: `learning_platform/src/learning_platform/agentic_ops/mcp_server/action_server.py`

- exposes destructive tools:
  - `ops.prepare_delete_document_process_runs`
  - `ops.execute_delete_document_process_runs`
  - `ops.cancel_agent_action`
  - `ops.rollback_agent_action`
  - `ops.slice_document_pages`
  - `ops.list_managed_documents`

### MCP clients

Path: `learning_platform/src/learning_platform/agentic_ops/mcp/client.py`

- `McpReportClient` for `db.report_*` tools.
- `McpActionClient` for `ops.*` tools.
- `McpActionClient.slice_document_pages(...)` for mode-driven managed slicing.
- `McpActionClient.list_managed_documents()` for managed inventory discovery.
- shared parser/unwrap behavior for MCP `tools/call` responses.

## Settings

Path: `learning_platform/src/learning_platform/agentic_ops/settings.py`

- `mcp_endpoint` (report endpoint)
- `mcp_api_key` (report API key)
- `action_mcp_endpoint`
- `action_mcp_api_key`
- `mcp_timeout_seconds`
- `max_rows_per_page`
- `include_rows`
- `allow_corrective_actions`
- `action_ttl_minutes`
- `mcp_managed_docs`
  - env: `MCP_MANAGED_DOCS`
- `mcp_max_input_size_bytes`
- `mcp_max_pages_per_slice`
- `mcp_max_base64_return_bytes`

Aliases:

- `report_mcp_endpoint` -> `mcp_endpoint`
- `report_mcp_api_key` -> `mcp_api_key`

## CLI Entrypoint

Path: `learning_platform/src/learning_platform/agentic_ops/mcp_server/__main__.py`

Parameters:

- `--mode report|action`
- `--transport streamable-http|stdio`
- `--host`
- `--port` (defaults by mode: report=8765, action=8766)
- `--path` (defaults by mode: report `/mcp/lp/reporting`, action `/mcp/lp/actions`)

## State Machine

`lp_roll_back_agent_action.status` transitions:

1. prepare success -> `prepared`
2. cancel success -> `canceled`
3. execute success -> `applied`
4. rollback success -> `rolled_back`
5. execute failure -> `execute_failed`
6. rollback failure -> `rollback_failed`

Valid operation gates:

- execute allowed only from `prepared` with precheck pass, integrity valid, and TTL valid.
- cancel allowed only from `prepared`.
- rollback allowed only from `applied` with integrity valid.

### Reviewer state machine

Reviewer graph transitions:

1. `prepare_context`
2. `create_run`
3. `review_page` (loop until all expanded pages processed)
4. `finalize_run` -> `completed`
5. Any graph-level failure -> `fail_run` -> `failed`

Per-page review outcomes include:

- `reviewed`
- `canonical_missing`
- `canonical_render_error`
- `source_page_error`
- `deterministic_mismatch`
- `deterministic_verifier_error`
- `llm_review_error`

## Testing

Added/updated unit coverage:

- `learning_platform/tests/unit/test_action_service.py`
  - prepare/execute/cancel/rollback happy paths,
  - deterministic target-key dedupe on repeated prepare,
  - repeated execute returns `already_applied`,
  - cancel lifecycle guards and re-prepare behavior after cancel.
- `learning_platform/tests/unit/test_mcp_server.py`
  - report server tool exposure,
  - action server tool exposure including cancel and managed-doc tools.
- `learning_platform/tests/unit/test_mcp_client.py`
  - action client tool mapping and payload shape checks,
  - cancel tool call mapping,
  - managed-doc slice/list call mappings,
  - MCP parse/unwrap behavior retained.
- `learning_platform/tests/unit/test_managed_docs_service.py`
  - path mode ingest/slice persistence
  - base64 mode ingest/slice response semantics
  - managed inventory listing and metadata
  - invalid range validation
- `learning_platform/tests/unit/test_repositories.py`
  - coverage for listing process rows/log rows by IDs and rollback repository prepared-target lookup.
  - reviewer run/page repository lifecycle coverage.
- `learning_platform/tests/unit/test_reviewer_agent.py`
  - reviewer graph persistence on completion and failure paths.
  - max-page guard behavior with no persisted run.
  - deterministic mismatch/canonical-missing persistence assertions.
- `learning_platform/tests/unit/test_orm_models.py`
  - reviewer run/page table registration and row construction coverage.
- `src/tests/test_v1.py`
  - diagnosis endpoints and corrective action endpoint coverage.
- `src/tests/test_src_coverage.py`
  - unauthorized path coverage updated for diagnosis route.

## Verification Commands

- `uv run pytest learning_platform/tests/unit/test_action_service.py learning_platform/tests/unit/test_mcp_client.py learning_platform/tests/unit/test_mcp_server.py learning_platform/tests/unit/test_repositories.py -q`
- `uv run pytest learning_platform/tests/unit/test_reviewer_agent.py learning_platform/tests/unit/test_repositories.py learning_platform/tests/unit/test_orm_models.py -q`
- `uv run pytest learning_platform/tests/unit/test_managed_docs_service.py learning_platform/tests/unit/test_mcp_client.py learning_platform/tests/unit/test_mcp_server.py -q`
- `uv run pytest src/tests/test_v1.py src/tests/test_src_coverage.py -q`
- `uv run ruff check learning_platform/src/learning_platform/agentic_ops learning_platform/src/learning_platform/infrastructure/persistence/repositories learning_platform/src/learning_platform/infrastructure/persistence/models learning_platform/tests/unit/test_action_service.py learning_platform/tests/unit/test_mcp_client.py learning_platform/tests/unit/test_mcp_server.py learning_platform/tests/unit/test_repositories.py src/routers/triage.py src/services/triage.py src/services/triage_actions.py src/database/repositories/triage.py src/schemas.py alembic/versions/f9c1a2b3d4e5_add_lp_roll_back_agent_action_table.py`

## Risks and Follow-ups

- Rollback row restoration currently targets LP process/log tables only; extending to broader destructive actions requires per-action undo schema discipline.
- Rollback integrity hash covers undo payload content; future hardening can include additional scope metadata in hash input.
- Migration `f9c1a2b3d4e5` was edited in place to switch `idempotency_key` to `target_key`; if already applied in any environment, a follow-up migration is required instead of replay.

# Architecture: Master-It + Agentic Operations

## System Context

The repository has two production planes that must stay consistent:

- `src/` (master API plane): FastAPI endpoints and core relational data (`documents`, `courses`, `units`, `sections`, `lessons`, enrollments, progress).
- `learning_platform/` (LP processing plane): parser/pipeline/runtime and LP persistence (`lp_*` tables).

Agentic operations now include two MCP server boundaries:

- **Read-only reporting boundary** for deterministic diagnostics.
- **Destructive action boundary** for controlled write operations with prepare/execute/cancel/rollback safety gates.

## High-Level Components

### Existing Components

- **Master API (`src/main.py`)**
  - Hosts user/course/document/learning APIs.
  - Uses SQLAlchemy async engine configured in `src/database/base.py`.

- **Learning Platform API + Pipeline (`learning_platform/src/learning_platform`)**
  - Pollers and orchestration (`poller.py`, `pipeline/orchestrator.py`).
  - Parser stack and LP persistence models/repositories.

### Agentic Ops Components

- **MCP Report Service (read-only)**
  - `learning_platform/src/learning_platform/agentic_ops/reporting/service.py`
  - Tools exposed by report server:
    - `db.report_all_entries`
    - `db.report_missing_entries`
    - `db.report_table_page`
  - Performs read-only aggregation and integrity reporting.

- **MCP Report Server Runtime**
  - `learning_platform/src/learning_platform/agentic_ops/mcp_server/reporting_server.py`
  - Server name: `master-it-triage-report-service`
  - Default transport path: `/mcp/lp/reporting`

- **Action Service (destructive workflow engine)**
  - `learning_platform/src/learning_platform/agentic_ops/actions/service.py`
  - Implements strict `prepare -> execute/cancel -> rollback` lifecycle.
  - Current destructive action type:
    - `delete_document_process_runs`

- **MCP Action Server Runtime**
  - `learning_platform/src/learning_platform/agentic_ops/mcp_server/action_server.py`
  - Server name: `master-it-triage-action-service`
  - Default transport path: `/mcp/lp/actions`
  - Tools exposed:
    - `ops.prepare_delete_document_process_runs`
    - `ops.execute_delete_document_process_runs`
    - `ops.cancel_agent_action`
    - `ops.rollback_agent_action`
    - `ops.slice_document_pages`
    - `ops.list_managed_documents`

- **Managed Docs Capability Service**
  - `learning_platform/src/learning_platform/capabilities/managed_docs/service.py`
  - Independent capability used by MCP action tools.
  - Manages MCP-owned storage root with subfolders:
    - `orig/` for ingested originals
    - `sliced/` for generated slices
  - Supports mode-driven request/response behavior:
    - `mode=path` reads absolute source path, persists original, returns sliced path
    - `mode=base64` ingests base64 source, persists original, returns sliced base64

- **ReviewerAgent Document Review Workflow**
  - `learning_platform/src/learning_platform/agents/reviewer.py`
  - Uses a LangGraph state machine for document-page review orchestration.
  - Graph stages:
    - `prepare_context` (resolve LP document, load canonical pages, expand ranges)
    - `create_run` (persist `lp_reviewer_run` row in `processing` state)
    - `review_page` loop (per-page deterministic precheck + optional LLM review)
    - `finalize_run` (aggregate verdict + persist completion)
    - `fail_run` (persist failure state and error details)
  - Preserves non-fail-fast page semantics for canonical/source/page-level issues.

- **Reviewer Run Persistence**
  - Tables:
    - `lp_reviewer_run`
    - `lp_reviewer_page_result`
  - ORM models:
    - `learning_platform/src/learning_platform/infrastructure/persistence/models/reviewer_run.py`
  - Repositories:
    - `learning_platform/src/learning_platform/infrastructure/persistence/repositories/reviewer_run.py`
  - Stores per-run lifecycle (`processing`, `completed`, `failed`) and per-page review outcomes for traceability.

- **Rollback/Audit Store**
  - Table: `lp_roll_back_agent_action`
  - ORM model:
    - `learning_platform/src/learning_platform/infrastructure/persistence/models/roll_back_agent_action.py`
  - Repository:
    - `learning_platform/src/learning_platform/infrastructure/persistence/repositories/roll_back_agent_action.py`
  - Stores deterministic `target_key`, requester identity, precheck result, undo data, integrity hash, and lifecycle status timestamps (including `canceled_at`).

- **Backend Triage API Surface**
  - `src/routers/triage.py`
  - Diagnosis endpoints:
    - `POST /api/v1/triage/diagnoses`
    - `GET /api/v1/triage/diagnoses/{diagnosis_id}`
    - `GET /api/v1/triage/diagnoses/{diagnosis_id}/findings`
  - Corrective action endpoints:
    - `POST /api/v1/triage/diagnoses/{diagnosis_id}/actions/delete-document-process-runs`
      - `confirm=false`: prepare and return confirmation payload
      - `confirm=true`: execute using `action_id`
    - `POST /api/v1/triage/diagnoses/{diagnosis_id}/actions/{action_id}/cancel`
    - `POST /api/v1/triage/diagnoses/{diagnosis_id}/actions/{action_id}/rollback`

- **TriageAgent + Rule Engine**
  - Triage agent consumes read-only report pages and evaluates deterministic rules.
  - No direct SQL in triage evaluator.

## Deployment Topology

Phase-1 runtime remains in one repository/workspace, with two MCP endpoints:

- Report MCP endpoint (default): `http://127.0.0.1:8765/mcp/lp/reporting`
- Action MCP endpoint (default): `http://127.0.0.1:8766/mcp/lp/actions`

Entrypoint supports both modes:

- `uv run python -m learning_platform.agentic_ops.mcp_server --mode report --transport streamable-http`
- `uv run python -m learning_platform.agentic_ops.mcp_server --mode action --transport streamable-http`

## Operational Runbook

### Environment variables

- `AGENTIC_OPS_MCP_ENDPOINT`
  - Report MCP endpoint used by triage report client.
  - Default: `http://localhost:8765/mcp/lp/reporting`
- `AGENTIC_OPS_MCP_API_KEY`
  - Optional report MCP bearer token.
- `AGENTIC_OPS_ACTION_MCP_ENDPOINT`
  - Action MCP endpoint used by destructive-action client.
  - Default: `http://localhost:8766/mcp/lp/actions`
- `AGENTIC_OPS_ACTION_MCP_API_KEY`
  - Optional action MCP bearer token.
- `AGENTIC_OPS_MCP_TIMEOUT_SECONDS`
  - Shared MCP request timeout.
  - Default: `30.0`
- `AGENTIC_OPS_MAX_ROWS_PER_PAGE`
  - Report pagination cap used by triage agent.
  - Default: `500`
- `AGENTIC_OPS_INCLUDE_ROWS`
  - Include sampled rows in table reports.
  - Default: `false`
- `AGENTIC_OPS_ALLOW_CORRECTIVE_ACTIONS`
  - Feature flag gate for future backend-triggered remediation flows.
  - Default: `false`
- `AGENTIC_OPS_ACTION_TTL_MINUTES`
  - TTL for prepared destructive actions.
  - Default: `30`
- `MCP_MANAGED_DOCS`
  - MCP-managed document root path for capability tools.
  - Default: `agentic_ops_managed_docs`
- `AGENTIC_OPS_MCP_MAX_INPUT_SIZE_BYTES`
  - Max input PDF size accepted by managed-doc tooling.
  - Default: `31457280` (30 MiB)
- `AGENTIC_OPS_MCP_MAX_PAGES_PER_SLICE`
  - Max pages allowed per slicing request.
  - Default: `50`
- `AGENTIC_OPS_MCP_MAX_BASE64_RETURN_BYTES`
  - Max sliced PDF byte size allowed when returning base64.
  - Default: `8388608` (8 MiB)

### Launch commands

- Start report MCP server:
  - `uv run python -m learning_platform.agentic_ops.mcp_server --mode report --transport streamable-http --host 127.0.0.1 --port 8765 --path /mcp/lp/reporting`
- Start action MCP server:
  - `uv run python -m learning_platform.agentic_ops.mcp_server --mode action --transport streamable-http --host 127.0.0.1 --port 8766 --path /mcp/lp/actions`
- Start backend API:
  - `uv run fastapi dev src/main.py --port 5000`

### Health checks

- Backend liveness:
  - `curl -sS http://127.0.0.1:5000/health`
- Report MCP tools should include:
  - `db.report_all_entries`
  - `db.report_missing_entries`
  - `db.report_table_page`
- Action MCP tools should include:
  - `ops.prepare_delete_document_process_runs`
  - `ops.execute_delete_document_process_runs`
  - `ops.cancel_agent_action`
  - `ops.rollback_agent_action`
  - `ops.slice_document_pages`
  - `ops.list_managed_documents`

## Data Flow

### Read-only triage flow

```text
PostgreSQL (master + LP tables)
    -> MCP Report Server (db.report_* tools)
    -> MCP Report Client
    -> TriageAgent (deterministic rule evaluation)
    -> Findings persistence (diagnosis runs + diagnosis findings)
    -> API/CLI consumers
```

### Destructive action flow

```text
Operator/automation request
    -> MCP Action Server (ops.prepare_*)
    -> Action Service
    -> snapshot target rows + undo payload
    -> lp_roll_back_agent_action(status=prepared)
    -> optional MCP Action Server (ops.cancel_*)
    -> lp_roll_back_agent_action(status=canceled)
    -> MCP Action Server (ops.execute_*)
    -> integrity + status + TTL checks
    -> destructive write (delete)
    -> lp_roll_back_agent_action(status=applied)
    -> optional MCP Action Server (ops.rollback_*)
    -> restore from undo payload
    -> lp_roll_back_agent_action(status=rolled_back)
```

### Managed document slicing flow

```text
Agent request
    -> MCP Action Server (ops.slice_document_pages)
    -> ManagedDocsService
    -> persist original into MCP_MANAGED_DOCS/orig
    -> slice requested page range
    -> persist slice into MCP_MANAGED_DOCS/sliced
    -> mode=path returns sliced_path
    -> mode=base64 returns sliced_pdf_base64
```

### Reviewer document-page review flow

```text
Reviewer request(lp_documents_id + page ranges)
    -> ReviewerAgent LangGraph
    -> prepare_context (lookup + canonical pages + range expansion)
    -> create_run (lp_reviewer_run status=processing)
    -> review_page loop
       -> slice actual page via MCP action tool
       -> render canonical page from LP BookPage
       -> deterministic verifier (PyMuPDF)
       -> optional LLM review on deterministic pass
       -> persist lp_reviewer_page_result row
    -> finalize_run
       -> aggregate verdict/summary
       -> lp_reviewer_run status=completed
    -> on workflow failure: fail_run -> lp_reviewer_run status=failed
```

## Trust and Security Boundaries

### Read-only boundary

- Reporting server exposes only read-only tools.
- Triage verdicting is deterministic and contract-validated.

### Destructive boundary

- Destructive tools are isolated on a separate MCP server and endpoint.
- Execution is blocked unless:
  - action exists,
  - action type matches,
  - action is in `prepared` status,
  - precheck passed,
  - integrity hash validates,
  - action is not expired.
- Cancel is blocked unless action status is `prepared`.
- Rollback is blocked unless action status is `applied` and integrity validates.

### Managed docs boundary

- Managed-doc tools write only under `MCP_MANAGED_DOCS`.
- Path-mode source requires absolute path.
- Slices are always persisted to MCP-managed storage before response.
- Base64-mode response is size-capped by configuration.

### Auditability

- `lp_roll_back_agent_action` captures:
  - reason, requester, deterministic target key,
  - target summary,
  - undo steps,
  - integrity hash,
  - lifecycle timestamps and failure status.
- `lp_reviewer_run` captures:
  - requested vs resolved LP document IDs,
  - aggregate verdict/summary,
  - workflow status and error state,
  - run-level metadata and timestamps.
- `lp_reviewer_page_result` captures:
  - per-page review status and errors,
  - extracted text length,
  - issues/recommendations/verdict/confidence,
  - deterministic verifier metadata for each reviewed page.

## Failure Semantics

- Report MCP contract mismatch or tool error -> diagnosis execution fails.
- Action precheck failure -> prepare succeeds with `precheck_passed=false`, execute blocked.
- Execute failure -> action status `execute_failed` with error message.
- Cancel on non-prepared action -> rejected by lifecycle guard.
- Rollback failure -> action status `rollback_failed` with error message.
- Repeated prepare for the same target item set returns existing prepared action state.
- Slicing request with out-of-range pages fails with validation error.
- Base64 mode fails when sliced output exceeds configured max response size.
- Reviewer workflow graph-level failure marks run `failed` and surfaces error to caller.
- Deterministic mismatches persist as page results (`review_status=deterministic_mismatch`) without aborting the run.

## Extensibility

- New destructive action types can reuse shared rollback table and lifecycle model.
- Additional action servers can be split later by domain while preserving the same prepare/execute/cancel/rollback contract style.

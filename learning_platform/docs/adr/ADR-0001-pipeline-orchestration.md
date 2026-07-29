# ADR-0001: Pipeline Orchestration Through Service Facade

- Status: Accepted
- Date: 2026-07-28

## Context

The LP module had orchestration logic split across route handlers and service
paths. This increased drift risk and made API and background poller behavior
harder to keep consistent.

## Decision

Use `LearningPlatformService.process(...)` as the single orchestration path for
document processing.

- API document endpoints call the service.
- `FilePoller` calls the same service path.
- Service delegates pipeline execution to `PipelineOrchestrator`.

## Consequences

### Positive

- One execution path for API and poller.
- Reduced duplication and behavior drift.
- Easier testing and event/log persistence consistency.

### Trade-offs

- Service becomes a critical integration point and must remain stable.
- Requires clear boundaries to avoid route-specific logic bleeding into service.

## Implementation References

- `learning_platform/src/learning_platform/service.py`
- `learning_platform/src/learning_platform/api/routes/documents.py`
- `learning_platform/src/learning_platform/poller.py`
- `learning_platform/src/learning_platform/pipeline/orchestrator.py`

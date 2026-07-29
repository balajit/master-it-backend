# learning_platform Architecture Notes

## 1. Module Topology

The `learning_platform` module is a bounded subsystem mounted into the host
API under `/lp`.

- Host app mounts LP singleton app: `src/main.py`.
- LP app is built in `learning_platform/src/learning_platform/api/app.py`.
- LP routes delegate to `LearningPlatformService` for processing orchestration.

## 2. Processing Flow

Canonical flow:

1. Upload document (`/api/documents/upload`)
2. Resolve source + authorize ownership
3. `LearningPlatformService.process(...)`
4. `PipelineOrchestrator` executes stages in order
5. Persist artifacts + cache `PipelineResult`
6. Query endpoints read cached/persisted outputs

Stage sequence in orchestrator:

- parser
- normalizer
- page grouping
- enricher
- unit builder
- concept extractor
- graph builder
- sequence builder

## 3. Runtime Components

### API Layer

- `routes/documents.py`: upload, process, enrich, tree, units, concepts,
  study-plan, JSON export.
- `routes/courses.py`: courses list endpoint.
- `routes/health.py`: liveness endpoint.

### Service Layer

- `LearningPlatformService` is the single orchestration path used by both
  API handlers and poller.
- Service captures pipeline events and persists stage/pipeline logs.

### Poller

- `FilePoller` reads `registry.txt`, creates pending process rows, then
  processes pending entries via `LearningPlatformService`.

## 4. Persistence Model

Primary LP tables include:

- `lp_documents`
- `lp_learning_units`
- `lp_annotations`
- `lp_concepts`, `lp_concept_relationships`
- `lp_knowledge_graphs`, `lp_graph_nodes`, `lp_graph_edges`
- `lp_study_plans`, `lp_lessons`, `lp_milestones`, `lp_checkpoints`
- `lp_pipeline_logs`, `lp_document_process`
- book tables: `lp_book_chapter`, `lp_book_lesson`, `lp_book_page`, `lp_book_item`

Schema governance is Alembic-driven from repo root `alembic/`.

## 5. Configuration & Security

- Configuration uses Pydantic settings with fail-fast validation in
  non-test environments.
- JWT validation in LP uses shared secret and algorithm compatibility with
  host app auth.
- Upload ownership enforcement uses persisted owner subject checks.

## 6. Operational Notes

- LP app is singleton-based to avoid cache divergence across app instances.
- Blocking file operations in hot async paths are offloaded to threadpool.
- Migrations include smoke-test and head/current validation scripts under
  `scripts/`.

## 7. Open Gaps

- Oversized module split remains pending for:
  - `api/routes/documents.py`
  - `presentation/mappers/learning_experience.py`
- Dependency hygiene and empty placeholder model cleanup remain pending.

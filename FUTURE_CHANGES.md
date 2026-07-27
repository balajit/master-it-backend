# Future Changes

## Pipeline / Poller

### Re-process from persisted data instead of re-running pipeline
Currently when a file has a `lp_pipeline_logs` success entry but the in-memory
cache misses (e.g. after server restart), the full pipeline re-runs from
scratch (`service.py` duplicate check path).  A future improvement would
reconstruct the `PipelineResult` from persisted tables (`lp_documents`,
`lp_learning_units`, `lp_concepts`, `lp_knowledge_graphs`, `lp_study_plans`)
instead of re-parsing the source file.

### Backoff strategy for WIP retries
Currently WIP retries happen every poll cycle (10s).  A future improvement
would add exponential backoff (e.g. 30s, 2min, 10min) before the 3-retry
limit.

### Replace registry files with DB-backed queue
The file-based registry (`registry.txt`, `registry_wip.txt`) could be
replaced by a database table with states (pending, wip, done, error).  This
would eliminate file-locking complexity and make the queue observable via
SQL.

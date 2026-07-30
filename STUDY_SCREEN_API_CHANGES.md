# Study Screen API Changes — Implementation Prompt

## Context

The frontend study screen (`StudyPage.tsx`) needs to drive the following UI components from live API
data. All components are currently powered by hardcoded placeholders. This prompt describes the
exact backend changes required to support them.

The primary study page endpoint is `GET /api/v1/units/{unit_id}` → `UnitResponse` (defined in
`src/schemas.py`). Secondary data comes from `GET /courses/{course_id}/units` (learning router).
All changes are confined to `src/schemas.py`, `src/routers/v1.py`, `src/routers/learning.py`, and
`src/services/learning.py`.

---

## Stack Rules (from AGENTS.md)

- Framework: FastAPI + Python 3.10+
- Always use full type hints on all variables, parameters, and return types.
- Always create Pydantic models for request/response shapes.
- Use `typing` collections (`List`, `Optional`, `Dict`) where needed.
- Package manager: `uv`. Do not use pip.
- Lint after every change: `uv run ruff check .`
- Format after every change: `uv run ruff format .`
- Do not use `sudo`. Do not run interactive commands.

---

## Change 1 — Normalize `ProgressStatus` to lowercase

**File:** `src/schemas.py`

`ProgressStatus` currently uses `SCREAMING_SNAKE_CASE` values. The frontend `statusConfig.ts` maps
against lowercase strings. Change all enum values to lowercase.

```python
# BEFORE
class ProgressStatus(str, enum.Enum):
    MASTERED = "MASTERED"
    PRACTICED = "PRACTICED"
    FAMILIAR = "FAMILIAR"
    ATTEMPTED = "ATTEMPTED"
    NOT_STARTED = "NOT_STARTED"
    LOCKED = "LOCKED"

# AFTER
class ProgressStatus(str, enum.Enum):
    MASTERED = "mastered"
    PRACTICED = "practiced"
    FAMILIAR = "familiar"
    ATTEMPTED = "attempted"
    NOT_STARTED = "not_started"
    LOCKED = "locked"
```

**Impact:** `ProgressStatus` is used in `LessonResponse.status`, `PracticeResponse.status`, and
`ProgressSquareResponse.status`. Anywhere a raw string like `"MASTERED"` or `"NOT_STARTED"` is
assigned in `src/routers/v1.py` or `src/services/` must be updated to use the enum member instead
(e.g. `ProgressStatus.MASTERED`) so the serialized value is lowercase.

Search for all raw uppercase string assignments in the codebase and replace them with enum members:
- In `v1.py` line ~180: `status: str = "MASTERED" if passed else "ATTEMPTED"` → use enum members
- In `v1.py` line ~326: `status: str = "NOT_STARTED"` in `UserPracticeProgressUpdate` default →
  this is a request body, leave as a raw string but document the expected values
- In `services/progress.py`: verify all `ProgressStatus` comparisons and returns use the enum

---

## Change 2 — Add `activity_type`, `description`, `locked`, `progress_label`, and `action_label` to `PracticeResponse`

**File:** `src/schemas.py`

The `PracticeCard` UI component requires these additional fields.

```python
# AFTER
class PracticeResponse(BaseModel):
    """A practice activity within a section — clean response serializer."""

    id: int
    title: str
    description: str = ""
    required_correct: int
    total_questions: int
    order: int
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    attempts: int = 0
    best_score: float = 0.0
    activity_type: str = "practice"   # "practice" | "project" | "self_test"
    locked: bool = False
    progress_label: str = ""          # e.g. "Score 12/15 to pass"
    action_label: str = "Start"       # e.g. "Start", "Continue", "Review"
```

**Computation rules** for the new fields — implement these in `src/services/learning.py` where
`PracticeResponse` instances are constructed:

- `progress_label`: `f"Score {required_correct}/{total_questions} to pass"` when
  `total_questions > 0`, otherwise `""`.
- `action_label`: derive from `status`:
  - `NOT_STARTED` or `LOCKED` → `"Start"`
  - `ATTEMPTED` or `PRACTICED` or `FAMILIAR` → `"Continue"`
  - `MASTERED` → `"Review"`
- `locked`: `True` when `status == ProgressStatus.LOCKED`, else `False`.
- `activity_type`: default `"practice"`. No database column exists for this yet; use the default
  for now and leave a `# TODO: derive from db column once added` comment.
- `description`: default `""`. No database column exists yet; leave a `# TODO` comment.

Update the `PracticeResponse(...)` construction site in `src/services/learning.py` to populate
all new fields using the rules above.

Also update `src/routers/v1.py` `get_practice_v1` to populate the new fields consistently.

---

## Change 3 — Add `status`, `description`, `activity_type`, `locked`, and `action_label` to `GoalResponse`

**File:** `src/schemas.py`

The `PracticeCard` is also used to render quiz/goal items in the sidebar and content area.

```python
# AFTER
class GoalResponse(BaseModel):
    """A quiz/goal within a section — renamed from QuizWithProgress."""

    id: int
    title: str
    description: str = ""
    score: Optional[float] = None
    completed_at: Optional[str] = None
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    activity_type: str = "quiz"   # "quiz" | "project"
    locked: bool = False
    action_label: str = "Start"   # "Start" | "Continue" | "Review"
```

**Computation rules** — implement in `src/services/learning.py` and `src/routers/v1.py`:

- `status`: call the existing `determine_goal_status(progress)` from `src/services/progress.py`.
  This function already exists — just assign its return value to `status`.
- `action_label`: same logic as `PracticeResponse` — derive from `status`.
- `locked`: `True` when `status == ProgressStatus.LOCKED`.
- `description`: default `""`. Leave a `# TODO` comment.
- `activity_type`: default `"quiz"`. Leave a `# TODO` comment.

Update the `GoalResponse(...)` construction sites:
1. In `src/services/learning.py` where goals are assembled per section.
2. In `src/routers/v1.py` `get_quiz_v1` endpoint.

---

## Change 4 — Add a study-page units listing endpoint to the v1 router

**File:** `src/routers/v1.py`

The study page receives `course_id` from the URL and needs to resolve it to `unit_id` values to
call `GET /api/v1/units/{unit_id}`. The existing `GET /courses/{course_id}/units` in the learning
router returns `UnitCrudResponse` (admin shape with `created_at`, `updated_at`, etc.) — that is
not appropriate for frontend consumption.

Add a lean, frontend-facing endpoint to the v1 router:

```python
class UnitSummary(BaseModel):
    """Lightweight unit listing item for the study page navigation."""

    id: int
    title: str
    description: str
    display_order: int
    total_sections: int = 0
    estimated_minutes: int = 0
```

Add this new schema to `src/schemas.py`.

Add this endpoint to `src/routers/v1.py`:

```python
@router.get("/courses/{course_id}/units", response_model=List[UnitSummary])
async def list_units_v1(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[UnitSummary]:
    ...
```

Implementation notes:
- Import `list_units` from `database` (it already exists — used in the learning router).
- For `total_sections` and `estimated_minutes`, query the sections for each unit and aggregate.
  If that is too expensive, default both to `0` with a `# TODO` comment for now.
- Return units ordered by `display_order`.

---

## Change 5 — Differentiate `about` from `description` in `UnitResponse`

**File:** `src/schemas.py` and `src/services/learning.py`

Currently `UnitResponse.about` is set equal to `description` in `services/learning.py`. The
`InfoCard` component needs a distinct, richer body copy field. Separate the two fields so they
can diverge once the database has dedicated content.

In `src/services/learning.py`, where `UnitResponse` is constructed:

```python
# BEFORE (approximate)
about=unit["description"],

# AFTER
# Use the db `about` column when it exists; fall back to description for now.
about=unit.get("about") or unit.get("description", ""),
```

Add a database column `about TEXT DEFAULT ''` to the `units` table so the field can be populated
independently. Create an Alembic migration for this column addition.

**Migration steps:**
1. Check whether Alembic is configured (`alembic.ini` exists — it does).
2. Run: `uv run alembic revision --autogenerate -m "add_unit_about_column"`
3. Review the generated migration file to confirm it adds `about TEXT DEFAULT ''` to `units`.
4. Apply: `./scripts/migrate.sh testing`

If autogenerate does not detect the change (SQLite quirks), write the migration manually using
`op.add_column('units', sa.Column('about', sa.Text(), nullable=True, server_default=''))`.

---

## Change 6 — Add `duration_label` to `LessonResponse`

**File:** `src/schemas.py`

The `LessonItem` UI component expects a pre-formatted duration string like `"5 min"`, not a raw
integer. Add a computed field to `LessonResponse`:

```python
class LessonResponse(BaseModel):
    """A lesson within a section — clean response serializer."""

    id: int
    title: str
    description: str
    duration_minutes: int
    duration_label: str = ""   # e.g. "5 min", "1 hr 10 min" — computed, not stored
    order: int
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    completed_at: Optional[str] = None
```

Add a helper function in `src/services/learning.py`:

```python
def format_duration(minutes: int) -> str:
    """Format an integer minute count into a human-readable label."""
    if minutes <= 0:
        return ""
    if minutes < 60:
        return f"{minutes} min"
    hours: int = minutes // 60
    remaining: int = minutes % 60
    if remaining == 0:
        return f"{hours} hr"
    return f"{hours} hr {remaining} min"
```

Populate `duration_label` from `format_duration(lesson["duration_minutes"])` wherever
`LessonResponse` is constructed (in `services/learning.py` and `routers/v1.py`).

---

## Change 7 — Add `total_lessons` and `total_minutes` to `UnitResponse`

**File:** `src/schemas.py` and `src/services/learning.py`

The sidebar header displays the total lesson count and total estimated time for the unit. Neither
field is currently on `UnitResponse`. Add both as computed aggregates.

```python
class UnitResponse(BaseModel):
    """Top-level unit study page response — clean serializer for frontend."""

    id: int
    title: str
    description: str
    course_id: int
    progress: ProgressResponse
    about: str
    total_lessons: int = 0    # ADD — count of all lessons across all sections
    total_minutes: int = 0    # ADD — sum of all lesson duration_minutes
    sections: List[SectionResponse] = []
```

**In `src/services/learning.py`**, compute these after assembling sections in `get_unit_details()`:

```python
total_lessons: int = sum(len(s.lessons) for s in sections)
total_minutes: int = sum(
    lesson.duration_minutes
    for s in sections
    for lesson in s.lessons
)
```

Pass `total_lessons` and `total_minutes` into the `UnitResponse(...)` constructor.

---

## Change 8 — Add `sidebar_status` (3-state) to `LessonResponse` and `PracticeResponse`

**File:** `src/schemas.py` and `src/services/progress.py`

The sidebar `SidebarItemData.status` field uses a 3-state vocabulary:
`"completed" | "in_progress" | "not_started"`. The existing `ProgressStatus` is 6-state.
Rather than forcing the frontend to map between them, expose a pre-collapsed `sidebar_status`
field on both lesson and practice responses.

```python
class LessonResponse(BaseModel):
    ...
    sidebar_status: str = "not_started"   # ADD — "completed" | "in_progress" | "not_started"

class PracticeResponse(BaseModel):
    ...
    sidebar_status: str = "not_started"   # ADD
```

Add this helper to `src/services/progress.py`:

```python
def to_sidebar_status(status: ProgressStatus) -> str:
    """Collapse 6-state ProgressStatus into the 3-state sidebar ItemStatus."""
    if status == ProgressStatus.MASTERED:
        return "completed"
    if status in (
        ProgressStatus.PRACTICED,
        ProgressStatus.FAMILIAR,
        ProgressStatus.ATTEMPTED,
    ):
        return "in_progress"
    return "not_started"  # covers NOT_STARTED and LOCKED
```

Populate `sidebar_status` using `to_sidebar_status(status)` wherever `LessonResponse` and
`PracticeResponse` are constructed — in both `src/services/learning.py` and `src/routers/v1.py`.

---

## Change 9 — Add `practice_type` DB column → `activity_type` in `PracticeResponse`

**Files:** Alembic migration, `src/schemas.py`, `src/services/learning.py`

The sidebar renders a badge (`meta` prop) showing the activity type: `"Quiz"`, `"Project"`,
`"Practice"`. This requires a `practice_type` column in the database surfaced as `activity_type`
in `PracticeResponse` (already added in Change 2 — this change provides the database backing).

**Migration steps:**

1. Create migration: `uv run alembic revision --autogenerate -m "add_practice_type_column"`
2. If autogenerate does not detect the column (SQLite quirks), write it manually:
   ```python
   op.add_column(
       'practices',
       sa.Column('practice_type', sa.String(), nullable=True, server_default='practice')
   )
   ```
3. Apply: `./scripts/migrate.sh testing`

**In `src/services/learning.py`**, read the column when constructing `PracticeResponse`:

```python
activity_type=practice.get("practice_type") or "practice",
```

Remove the `# TODO` placeholder comment added in Change 2 once this migration is applied.

**Frontend badge mapping** (for reference — frontend implements this, not backend):

| `activity_type` value | Sidebar `meta` badge |
|---|---|
| `"quiz"` | `"Quiz"` |
| `"practice"` | `"Practice"` |
| `"project"` | `"Project"` |
| `"self_test"` | `"Self Test"` |

---

## Change 10 — Add `last_accessed_at` to `user_lesson_progress`

**Files:** Alembic migration, `src/database/models.py`, `src/routers/v1.py`

The resume feature requires knowing which lesson the user most recently interacted with. Add a
timestamp column to the `user_lesson_progress` table.

**Migration steps:**

1. Create migration: `uv run alembic revision --autogenerate -m "add_last_accessed_at_to_lesson_progress"`
2. If autogenerate does not detect the column (SQLite quirks), write it manually:
   ```python
   op.add_column(
       'user_lesson_progress',
       sa.Column('last_accessed_at', sa.String(), nullable=True)
   )
   ```
3. Apply: `./scripts/migrate.sh testing`

**Update `src/routers/v1.py` — `update_lesson_progress_v1` (`PATCH /api/v1/users/me/lessons/{lesson_id}`):**

Always write `last_accessed_at = datetime.now(timezone.utc).isoformat()` when upserting lesson
progress, regardless of status. `datetime` and `timezone` imports are already present.

**Update wherever `upsert_user_lesson_progress` is defined** (database layer): add
`last_accessed_at: str | None = None` parameter and persist it to the table.

---

## Change 11 — Add `GET /api/v1/users/me/courses/{course_id}/resume`

**Files:** `src/schemas.py`, `src/routers/v1.py`, `src/database/`

The frontend study page calls this endpoint on load to determine which lesson to open first (the
"resume" feature — pick up where you left off).

Add a new response schema to `src/schemas.py`:

```python
class ResumeResponse(BaseModel):
    """The lesson to resume for a given course — most recently accessed."""

    lesson_id: int | None = None   # None if the user has no progress in this course
    unit_id: int | None = None     # The unit that contains the lesson
```

Add this endpoint to `src/routers/v1.py`:

```python
@router.get("/users/me/courses/{course_id}/resume", response_model=ResumeResponse)
async def get_resume_v1(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> ResumeResponse:
    ...
```

**Implementation logic:**

1. Fetch all lessons for the course by joining:
   `lessons → sections → units` where `units.course_id = course_id`
2. Join with `user_lesson_progress` for the current user
3. Filter to rows where `last_accessed_at IS NOT NULL`
4. Order by `last_accessed_at DESC`
5. Take the first row — return its `lesson_id` and resolved `unit_id`
6. If no rows found (no progress yet), return `{ lesson_id: null, unit_id: null }`

Implement as a new database query function in `src/database/repositories/learning.py`:
`get_resume_lesson(user_id: int, course_id: int) -> dict | None`

---

## Note — Sidebar `children` (nested lessons)

The hardcoded `PLACEHOLDER_GROUPS` in `StudyPage.tsx` uses `SidebarItemData.children` to show
sub-lessons nested under a parent. **Do not implement a nested lesson hierarchy in the backend.**
The backend has no such structure and adding one is out of scope. The frontend should flatten
`SectionResponse.lessons` into top-level sidebar items per section. This is a frontend-only
refactor.

---

## Verification

After all changes:

1. Lint: `uv run ruff check .` — must pass with zero errors.
2. Format: `uv run ruff format .` — apply and commit formatting.
3. Run the server: `uv run fastapi dev src/main.py --port 5000`
4. Verify the OpenAPI spec at `GET /api/spec` includes:
   - `GET /api/v1/courses/{course_id}/units` → `List[UnitSummary]`
   - `GET /api/v1/units/{unit_id}` → `UnitResponse` with updated nested schemas
   - `GET /api/v1/users/me/courses/{course_id}/resume` → `ResumeResponse`
   - `ProgressStatus` values are lowercase in the schema
5. Run existing tests: `uv run pytest` — must pass.
6. Manually test one unit: `curl -H "Authorization: Bearer <token>" http://localhost:5000/api/v1/units/1`
   and confirm:
   - `lessons[].status` values are lowercase
   - `lessons[].sidebar_status` is one of `"completed"`, `"in_progress"`, `"not_started"`
   - `lessons[].duration_label` is a formatted string (e.g. `"10 min"`)
   - `practices[]` include `progress_label`, `action_label`, `locked`, `sidebar_status`, `activity_type`
   - `goals[]` include `status`, `action_label`, `locked`
   - `total_lessons` and `total_minutes` are present at the unit level
7. Test resume: `curl -H "Authorization: Bearer <token>" http://localhost:5000/api/v1/users/me/courses/1/resume`
   and confirm `{ lesson_id: <int|null>, unit_id: <int|null> }` is returned.

---

## Summary of Files to Change

| File | Changes |
|---|---|
| `src/schemas.py` | Update `ProgressStatus` to lowercase; add fields to `PracticeResponse`, `GoalResponse`, `LessonResponse`; add `total_lessons`/`total_minutes` to `UnitResponse`; add `sidebar_status` to `LessonResponse` + `PracticeResponse`; add `UnitSummary` and `ResumeResponse` schemas |
| `src/services/learning.py` | Add `format_duration()`; compute `total_lessons`/`total_minutes`; populate all new fields in `PracticeResponse`, `GoalResponse`, `LessonResponse` construction; update `about` field resolution |
| `src/services/progress.py` | Add `to_sidebar_status()`; verify all `ProgressStatus` comparisons use enum members after casing change |
| `src/routers/v1.py` | Add `GET /api/v1/courses/{course_id}/units`; add `GET /api/v1/users/me/courses/{course_id}/resume`; update `get_practice_v1` and `get_quiz_v1` to populate new fields; write `last_accessed_at` in `update_lesson_progress_v1` |
| `src/database/repositories/learning.py` | Add `get_resume_lesson(user_id, course_id)` query |
| Alembic migrations | (1) `about` column on `units`; (2) `practice_type` column on `practices`; (3) `last_accessed_at` column on `user_lesson_progress` |

"""Comprehensive integration tests for all published API endpoints.

Runs against the real test PostgreSQL DB (learning_platform_testing on port 5433).
Uses the ``client``, ``db_session``, and ``mock_user`` fixtures from conftest.py.

Skipped automatically when the DB is unreachable.

Run:
    uv run pytest src/tests/integration/test_api_endpoints.py -v
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _uid() -> str:
    """Return a short unique hex string for use in titles."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Helper — build a reusable course via the API and return its id
# ---------------------------------------------------------------------------


async def _create_course(client: AsyncClient, *, suffix: str = "") -> int:
    resp = await client.post(
        "/api/courses",
        json={
            "title": f"Course-{_uid()}{suffix}",
            "description": "Auto-created by integration tests",
            "number_of_credits": 3,
            "difficulty": "beginner",
            "status": "OPEN",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_unit(client: AsyncClient, course_id: int, *, suffix: str = "") -> int:
    resp = await client.post(
        f"/api/courses/{course_id}/units",
        json={
            "title": f"Unit{suffix}",
            "description": "test unit",
            "display_order": 1,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_section(
    client: AsyncClient, unit_id: int, *, suffix: str = ""
) -> int:
    resp = await client.post(
        f"/api/units/{unit_id}/sections",
        json={
            "title": f"Section{suffix}",
            "estimated_minutes": 30,
            "display_order": 1,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_lesson(
    client: AsyncClient, section_id: int, *, suffix: str = ""
) -> int:
    resp = await client.post(
        f"/api/sections/{section_id}/lessons",
        json={
            "title": f"Lesson{suffix}",
            "description": "test lesson",
            "duration_minutes": 10,
            "display_order": 1,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_practice(
    client: AsyncClient, section_id: int, *, suffix: str = ""
) -> int:
    resp = await client.post(
        f"/api/sections/{section_id}/practices",
        json={
            "title": f"Practice{suffix}",
            "required_correct": 3,
            "total_questions": 5,
            "display_order": 2,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_quiz(
    client: AsyncClient, section_id: int, *, suffix: str = ""
) -> int:
    resp = await client.post(
        f"/api/sections/{section_id}/quizzes",
        json={"title": f"Quiz{suffix}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ===========================================================================
# Courses router  —  /api/courses
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestCoursesRouter:
    async def test_list_courses_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/courses")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_course(self, client: AsyncClient) -> None:
        title = f"New Course {_uid()}"
        resp = await client.post(
            "/api/courses",
            json={
                "title": title,
                "description": "desc",
                "number_of_credits": 3,
                "difficulty": "beginner",
                "status": "OPEN",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == title
        assert "id" in data

    async def test_create_course_returns_owner_id(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        resp = await client.post(
            "/api/courses",
            json={
                "title": f"Owner Course {_uid()}",
                "description": "",
                "number_of_credits": 1,
                "difficulty": "beginner",
                "status": "OPEN",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["owner_id"] == mock_user["id"]

    async def test_delete_course(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (delete me)")
        resp = await client.delete(f"/api/courses/{course_id}")
        assert resp.status_code == 204

    async def test_delete_nonexistent_course_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/courses/999999")
        assert resp.status_code == 404

    async def test_study_plan_404_for_missing_course(self, client: AsyncClient) -> None:
        resp = await client.get("/api/courses/999999/study-plan")
        assert resp.status_code == 404

    async def test_study_plan_returns_empty_chapters_for_course_with_no_docs(
        self, client: AsyncClient
    ) -> None:
        course_id = await _create_course(client, suffix=" (study plan)")
        resp = await client.get(f"/api/courses/{course_id}/study-plan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == course_id
        assert data["chapters"] == []


# ===========================================================================
# Learning router — Units
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestUnitsRouter:
    async def test_create_unit(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (units)")
        resp = await client.post(
            f"/api/courses/{course_id}/units",
            json={"title": "Intro Unit", "description": "desc", "display_order": 1},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Intro Unit"
        assert data["course_id"] == course_id

    async def test_list_units(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (list units)")
        await _create_unit(client, course_id, suffix=" A")
        await _create_unit(client, course_id, suffix=" B")
        resp = await client.get(f"/api/courses/{course_id}/units")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_unit(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (get unit)")
        unit_id = await _create_unit(client, course_id)
        resp = await client.get(f"/api/units/{unit_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == unit_id

    async def test_get_unit_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/units/999999")
        assert resp.status_code == 404

    async def test_update_unit(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (upd unit)")
        unit_id = await _create_unit(client, course_id)
        resp = await client.put(
            f"/api/units/{unit_id}",
            json={
                "title": "Updated Unit",
                "description": "new desc",
                "display_order": 2,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Unit"

    async def test_update_unit_404(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/units/999999",
            json={"title": "X", "description": "", "display_order": 1},
        )
        assert resp.status_code == 404

    async def test_delete_unit(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (del unit)")
        unit_id = await _create_unit(client, course_id)
        resp = await client.delete(f"/api/units/{unit_id}")
        assert resp.status_code == 204

    async def test_delete_unit_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/units/999999")
        assert resp.status_code == 404

    async def test_create_unit_for_missing_course_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/courses/999999/units",
            json={"title": "X", "description": "", "display_order": 1},
        )
        assert resp.status_code == 404


# ===========================================================================
# Learning router — Sections
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestSectionsRouter:
    async def test_create_section(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (sec)")
        unit_id = await _create_unit(client, course_id)
        resp = await client.post(
            f"/api/units/{unit_id}/sections",
            json={
                "title": "Intro Section",
                "estimated_minutes": 20,
                "display_order": 1,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Intro Section"
        assert data["unit_id"] == unit_id

    async def test_list_sections(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (list sec)")
        unit_id = await _create_unit(client, course_id)
        await _create_section(client, unit_id, suffix=" A")
        await _create_section(client, unit_id, suffix=" B")
        resp = await client.get(f"/api/units/{unit_id}/sections")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_section(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (get sec)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        resp = await client.get(f"/api/sections/{section_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == section_id

    async def test_get_section_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/sections/999999")
        assert resp.status_code == 404

    async def test_update_section(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (upd sec)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        resp = await client.put(
            f"/api/sections/{section_id}",
            json={
                "title": "Updated Section",
                "estimated_minutes": 45,
                "display_order": 2,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Section"

    async def test_delete_section(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (del sec)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        resp = await client.delete(f"/api/sections/{section_id}")
        assert resp.status_code == 204

    async def test_delete_section_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/sections/999999")
        assert resp.status_code == 404


# ===========================================================================
# Learning router — Lessons
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestLessonsRouter:
    async def _scaffold(self, client: AsyncClient, tag: str = "") -> tuple[int, int]:
        """Returns (section_id, lesson_id)."""
        course_id = await _create_course(client, suffix=f" (lesson{tag})")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        lesson_id = await _create_lesson(client, section_id)
        return section_id, lesson_id

    async def test_create_lesson(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (cr lesson)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        resp = await client.post(
            f"/api/sections/{section_id}/lessons",
            json={
                "title": "Intro Lesson",
                "description": "desc",
                "duration_minutes": 15,
                "display_order": 1,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Intro Lesson"

    async def test_list_lessons(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (list lesson)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        await _create_lesson(client, section_id, suffix=" A")
        await _create_lesson(client, section_id, suffix=" B")
        resp = await client.get(f"/api/sections/{section_id}/lessons")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_lesson(self, client: AsyncClient) -> None:
        _, lesson_id = await self._scaffold(client, " get")
        resp = await client.get(f"/api/lessons/{lesson_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == lesson_id

    async def test_get_lesson_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/lessons/999999")
        assert resp.status_code == 404

    async def test_update_lesson(self, client: AsyncClient) -> None:
        _, lesson_id = await self._scaffold(client, " upd")
        resp = await client.put(
            f"/api/lessons/{lesson_id}",
            json={
                "title": "Updated Lesson",
                "description": "new",
                "duration_minutes": 20,
                "display_order": 2,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Lesson"

    async def test_update_lesson_404(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/lessons/999999",
            json={
                "title": "X",
                "description": "",
                "duration_minutes": 5,
                "display_order": 1,
            },
        )
        assert resp.status_code == 404

    async def test_delete_lesson(self, client: AsyncClient) -> None:
        _, lesson_id = await self._scaffold(client, " del")
        resp = await client.delete(f"/api/lessons/{lesson_id}")
        assert resp.status_code == 204

    async def test_delete_lesson_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/lessons/999999")
        assert resp.status_code == 404


# ===========================================================================
# Learning router — Practices
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestPracticesRouter:
    async def _scaffold(self, client: AsyncClient, tag: str = "") -> tuple[int, int]:
        course_id = await _create_course(client, suffix=f" (prac{tag})")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        practice_id = await _create_practice(client, section_id)
        return section_id, practice_id

    async def test_create_practice(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (cr prac)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        resp = await client.post(
            f"/api/sections/{section_id}/practices",
            json={
                "title": "Intro Practice",
                "required_correct": 2,
                "total_questions": 4,
                "display_order": 1,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Intro Practice"

    async def test_list_practices(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (list prac)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        await _create_practice(client, section_id, suffix=" A")
        await _create_practice(client, section_id, suffix=" B")
        resp = await client.get(f"/api/sections/{section_id}/practices")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_practice(self, client: AsyncClient) -> None:
        _, practice_id = await self._scaffold(client, " get")
        resp = await client.get(f"/api/practices/{practice_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == practice_id

    async def test_get_practice_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/practices/999999")
        assert resp.status_code == 404

    async def test_update_practice(self, client: AsyncClient) -> None:
        _, practice_id = await self._scaffold(client, " upd")
        resp = await client.put(
            f"/api/practices/{practice_id}",
            json={
                "title": "Updated Practice",
                "required_correct": 4,
                "total_questions": 6,
                "display_order": 3,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Practice"

    async def test_delete_practice(self, client: AsyncClient) -> None:
        _, practice_id = await self._scaffold(client, " del")
        resp = await client.delete(f"/api/practices/{practice_id}")
        assert resp.status_code == 204

    async def test_delete_practice_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/practices/999999")
        assert resp.status_code == 404


# ===========================================================================
# Learning router — Quizzes
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestQuizzesRouter:
    async def _scaffold(self, client: AsyncClient, tag: str = "") -> tuple[int, int]:
        course_id = await _create_course(client, suffix=f" (quiz{tag})")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        quiz_id = await _create_quiz(client, section_id)
        return section_id, quiz_id

    async def test_create_quiz(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (cr quiz)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        resp = await client.post(
            f"/api/sections/{section_id}/quizzes",
            json={"title": "Final Quiz"},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Final Quiz"

    async def test_list_quizzes(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (list quiz)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        await _create_quiz(client, section_id, suffix=" A")
        await _create_quiz(client, section_id, suffix=" B")
        resp = await client.get(f"/api/sections/{section_id}/quizzes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_quiz(self, client: AsyncClient) -> None:
        _, quiz_id = await self._scaffold(client, " get")
        resp = await client.get(f"/api/quizzes/{quiz_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == quiz_id

    async def test_get_quiz_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/quizzes/999999")
        assert resp.status_code == 404

    async def test_update_quiz(self, client: AsyncClient) -> None:
        _, quiz_id = await self._scaffold(client, " upd")
        resp = await client.put(
            f"/api/quizzes/{quiz_id}",
            json={"title": "Updated Quiz"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Quiz"

    async def test_delete_quiz(self, client: AsyncClient) -> None:
        _, quiz_id = await self._scaffold(client, " del")
        resp = await client.delete(f"/api/quizzes/{quiz_id}")
        assert resp.status_code == 204

    async def test_delete_quiz_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/quizzes/999999")
        assert resp.status_code == 404


# ===========================================================================
# Learning router — Progress (lesson / practice / quiz)
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestProgressRouter:
    async def _full_scaffold(self, client: AsyncClient, tag: str = "") -> dict:
        """Return ids dict with course/unit/section/lesson/practice/quiz."""
        course_id = await _create_course(client, suffix=f" (prog{tag})")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        lesson_id = await _create_lesson(client, section_id)
        practice_id = await _create_practice(client, section_id)
        quiz_id = await _create_quiz(client, section_id)
        return {
            "course_id": course_id,
            "unit_id": unit_id,
            "section_id": section_id,
            "lesson_id": lesson_id,
            "practice_id": practice_id,
            "quiz_id": quiz_id,
        }

    # -- lesson progress --

    async def test_upsert_lesson_progress(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        ids = await self._full_scaffold(client, " l-upsert")
        user_id = mock_user["id"]
        lesson_id = ids["lesson_id"]
        resp = await client.put(
            f"/api/users/{user_id}/lessons/{lesson_id}/progress",
            json={"status": "completed", "completed_at": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["lesson_id"] == lesson_id

    async def test_get_lesson_progress(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        ids = await self._full_scaffold(client, " l-get")
        user_id = mock_user["id"]
        lesson_id = ids["lesson_id"]
        # Upsert first
        await client.put(
            f"/api/users/{user_id}/lessons/{lesson_id}/progress",
            json={"status": "in_progress", "completed_at": None},
        )
        resp = await client.get(f"/api/users/{user_id}/lessons/{lesson_id}/progress")
        assert resp.status_code == 200
        assert resp.json()["lesson_id"] == lesson_id

    async def test_get_lesson_progress_404(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        resp = await client.get(f"/api/users/{mock_user['id']}/lessons/999999/progress")
        assert resp.status_code == 404

    # -- practice progress --

    async def test_upsert_practice_progress(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        ids = await self._full_scaffold(client, " p-upsert")
        user_id = mock_user["id"]
        practice_id = ids["practice_id"]
        resp = await client.put(
            f"/api/users/{user_id}/practices/{practice_id}/progress",
            json={"attempts": 2, "best_score": 4.0, "status": "mastered"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["practice_id"] == practice_id
        assert data["attempts"] == 2

    async def test_get_practice_progress_404(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        resp = await client.get(
            f"/api/users/{mock_user['id']}/practices/999999/progress"
        )
        assert resp.status_code == 404

    # -- quiz progress --

    async def test_upsert_quiz_progress(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        ids = await self._full_scaffold(client, " q-upsert")
        user_id = mock_user["id"]
        quiz_id = ids["quiz_id"]
        resp = await client.put(
            f"/api/users/{user_id}/quizzes/{quiz_id}/progress",
            json={"score": 88.0, "completed_at": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["quiz_id"] == quiz_id
        assert data["score"] == 88.0

    async def test_get_quiz_progress_404(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        resp = await client.get(f"/api/users/{mock_user['id']}/quizzes/999999/progress")
        assert resp.status_code == 404


# ===========================================================================
# V1 router — courses, units, lessons, practices, quizzes
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestV1CoursesRouter:
    async def test_list_courses_v1(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/courses")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_course_v1(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (v1 get)")
        resp = await client.get(f"/api/v1/courses/{course_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == course_id

    async def test_get_course_v1_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/courses/999999")
        assert resp.status_code == 404

    async def test_list_units_v1(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (v1 units)")
        await _create_unit(client, course_id)
        resp = await client.get(f"/api/v1/courses/{course_id}/units")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_get_unit_v1(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (v1 unit)")
        unit_id = await _create_unit(client, course_id)
        resp = await client.get(f"/api/v1/units/{unit_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == unit_id

    async def test_get_unit_v1_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/units/999999")
        assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
class TestV1LessonsRouter:
    async def _scaffold(self, client: AsyncClient) -> int:
        course_id = await _create_course(client, suffix=" (v1 lesson)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        return await _create_lesson(client, section_id)

    async def test_get_lesson_v1(self, client: AsyncClient) -> None:
        lesson_id = await self._scaffold(client)
        resp = await client.get(f"/api/v1/lessons/{lesson_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == lesson_id
        assert "status" in data

    async def test_get_lesson_v1_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/lessons/999999")
        assert resp.status_code == 404

    async def test_get_lesson_notes_empty(self, client: AsyncClient) -> None:
        lesson_id = await self._scaffold(client)
        resp = await client.get(f"/api/v1/lessons/{lesson_id}/notes")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_lesson_flashcards_empty(self, client: AsyncClient) -> None:
        lesson_id = await self._scaffold(client)
        resp = await client.get(f"/api/v1/lessons/{lesson_id}/flashcards")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio(loop_scope="session")
class TestV1PracticesRouter:
    async def _scaffold(self, client: AsyncClient) -> int:
        course_id = await _create_course(client, suffix=" (v1 prac)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        return await _create_practice(client, section_id)

    async def test_get_practice_v1(self, client: AsyncClient) -> None:
        practice_id = await self._scaffold(client)
        resp = await client.get(f"/api/v1/practices/{practice_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == practice_id

    async def test_get_practice_v1_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/practices/999999")
        assert resp.status_code == 404

    async def test_submit_practice_v1(self, client: AsyncClient) -> None:
        practice_id = await self._scaffold(client)
        resp = await client.post(
            f"/api/v1/practices/{practice_id}/submit",
            json={"score": 4.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["practice_id"] == practice_id
        assert data["score"] == 4.0
        assert "passed" in data

    async def test_submit_practice_v1_404(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/practices/999999/submit", json={"score": 1.0})
        assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
class TestV1QuizzesRouter:
    async def _scaffold(self, client: AsyncClient) -> int:
        course_id = await _create_course(client, suffix=" (v1 quiz)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        return await _create_quiz(client, section_id)

    async def test_get_quiz_v1(self, client: AsyncClient) -> None:
        quiz_id = await self._scaffold(client)
        resp = await client.get(f"/api/v1/quizzes/{quiz_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == quiz_id

    async def test_get_quiz_v1_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/quizzes/999999")
        assert resp.status_code == 404

    async def test_submit_quiz_v1(self, client: AsyncClient) -> None:
        quiz_id = await self._scaffold(client)
        resp = await client.post(
            f"/api/v1/quizzes/{quiz_id}/submit",
            json={"score": 85.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["quiz_id"] == quiz_id
        assert data["passed"] is True

    async def test_submit_quiz_v1_404(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/quizzes/999999/submit", json={"score": 50.0})
        assert resp.status_code == 404


# ===========================================================================
# V1 router — User progress (me)
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestV1UserProgressRouter:
    async def test_get_user_progress(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        resp = await client.get("/api/v1/users/me/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == mock_user["id"]
        assert "lessons" in data
        assert "practices" in data
        assert "quizzes" in data

    async def test_patch_lesson_progress_v1(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (v1 patch l)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        lesson_id = await _create_lesson(client, section_id)
        resp = await client.patch(
            f"/api/v1/users/me/lessons/{lesson_id}",
            json={"status": "completed", "completed_at": None},
        )
        assert resp.status_code == 200
        assert resp.json()["lesson_id"] == lesson_id

    async def test_patch_lesson_progress_v1_404(self, client: AsyncClient) -> None:
        resp = await client.patch(
            "/api/v1/users/me/lessons/999999",
            json={"status": "completed", "completed_at": None},
        )
        assert resp.status_code == 404

    async def test_patch_practice_progress_v1(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (v1 patch p)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        practice_id = await _create_practice(client, section_id)
        resp = await client.patch(
            f"/api/v1/users/me/practices/{practice_id}",
            json={"attempts": 1, "best_score": 3.0, "status": "attempted"},
        )
        assert resp.status_code == 200
        assert resp.json()["practice_id"] == practice_id

    async def test_patch_quiz_progress_v1(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (v1 patch q)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        quiz_id = await _create_quiz(client, section_id)
        resp = await client.patch(
            f"/api/v1/users/me/quizzes/{quiz_id}",
            json={"score": 75.0, "completed_at": None},
        )
        assert resp.status_code == 200
        assert resp.json()["quiz_id"] == quiz_id

    async def test_get_resume_returns_none_for_new_course(
        self, client: AsyncClient
    ) -> None:
        course_id = await _create_course(client, suffix=" (v1 resume)")
        resp = await client.get(f"/api/v1/users/me/courses/{course_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["lesson_id"] is None


# ===========================================================================
# V1 router — Enrollment
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestV1EnrollmentRouter:
    async def test_enroll_in_course(self, client: AsyncClient, mock_user: dict) -> None:
        course_id = await _create_course(client, suffix=" (enroll)")
        resp = await client.post(
            f"/api/v1/courses/{course_id}/enroll",
            json={"source_document_id": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == course_id
        assert data["user_id"] == mock_user["id"]

    async def test_enroll_idempotent(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (enroll2)")
        await client.post(
            f"/api/v1/courses/{course_id}/enroll", json={"source_document_id": None}
        )
        resp = await client.post(
            f"/api/v1/courses/{course_id}/enroll", json={"source_document_id": None}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_enrolled"

    async def test_enroll_404_for_missing_course(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/courses/999999/enroll", json={"source_document_id": None}
        )
        assert resp.status_code == 404


# ===========================================================================
# V1 router — Section unlock
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestV1SectionUnlockRouter:
    async def test_unlock_section(self, client: AsyncClient, mock_user: dict) -> None:
        course_id = await _create_course(client, suffix=" (unlock)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        resp = await client.post(
            f"/api/v1/sections/{section_id}/unlock",
            json={"user_id": mock_user["id"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["section_id"] == section_id

    async def test_unlock_section_404(
        self, client: AsyncClient, mock_user: dict
    ) -> None:
        resp = await client.post(
            "/api/v1/sections/999999/unlock",
            json={"user_id": mock_user["id"]},
        )
        assert resp.status_code == 404


# ===========================================================================
# V1 router — Notes CRUD
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestV1NotesRouter:
    async def _scaffold_lesson(self, client: AsyncClient) -> int:
        course_id = await _create_course(client, suffix=" (notes)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        return await _create_lesson(client, section_id)

    async def test_create_note_for_lesson(self, client: AsyncClient) -> None:
        lesson_id = await self._scaffold_lesson(client)
        resp = await client.post(
            "/api/v1/notes",
            json={"content": "Test note", "lesson_id": lesson_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Test note"
        assert data["lesson_id"] == lesson_id

    async def test_get_lesson_notes(self, client: AsyncClient) -> None:
        lesson_id = await self._scaffold_lesson(client)
        await client.post(
            "/api/v1/notes", json={"content": "note 1", "lesson_id": lesson_id}
        )
        resp = await client.get(f"/api/v1/lessons/{lesson_id}/notes")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_update_note(self, client: AsyncClient) -> None:
        lesson_id = await self._scaffold_lesson(client)
        create_resp = await client.post(
            "/api/v1/notes",
            json={"content": "original", "lesson_id": lesson_id},
        )
        note_id = create_resp.json()["id"]
        resp = await client.put(f"/api/v1/notes/{note_id}", json={"content": "updated"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "updated"

    async def test_update_note_404(self, client: AsyncClient) -> None:
        resp = await client.put("/api/v1/notes/999999", json={"content": "x"})
        assert resp.status_code == 404

    async def test_delete_note(self, client: AsyncClient) -> None:
        lesson_id = await self._scaffold_lesson(client)
        create_resp = await client.post(
            "/api/v1/notes",
            json={"content": "delete me", "lesson_id": lesson_id},
        )
        note_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/v1/notes/{note_id}")
        assert resp.status_code == 204

    async def test_delete_note_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/v1/notes/999999")
        assert resp.status_code == 404

    async def test_get_unit_notes_empty(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (unit notes)")
        unit_id = await _create_unit(client, course_id)
        resp = await client.get(f"/api/v1/units/{unit_id}/notes")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_course_notes_empty(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (course notes)")
        resp = await client.get(f"/api/v1/courses/{course_id}/notes")
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# V1 router — Flashcards CRUD
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestV1FlashcardsRouter:
    async def _scaffold(self, client: AsyncClient) -> dict:
        course_id = await _create_course(client, suffix=" (flashcard)")
        unit_id = await _create_unit(client, course_id)
        section_id = await _create_section(client, unit_id)
        lesson_id = await _create_lesson(client, section_id)
        return {"course_id": course_id, "unit_id": unit_id, "lesson_id": lesson_id}

    async def test_create_flashcard_user_scope(self, client: AsyncClient) -> None:
        ids = await self._scaffold(client)
        resp = await client.post(
            "/api/v1/flashcards",
            json={
                "front": "What is X?",
                "back": "X is Y",
                "scope": "user",
                "lesson_id": ids["lesson_id"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["front"] == "What is X?"
        assert data["is_generated"] is False

    async def test_create_flashcard_course_scope(self, client: AsyncClient) -> None:
        ids = await self._scaffold(client)
        resp = await client.post(
            "/api/v1/flashcards",
            json={
                "front": "Course Q?",
                "back": "Course A",
                "scope": "course",
                "course_id": ids["course_id"],
            },
        )
        assert resp.status_code == 201

    async def test_get_lesson_flashcards(self, client: AsyncClient) -> None:
        ids = await self._scaffold(client)
        await client.post(
            "/api/v1/flashcards",
            json={
                "front": "Q",
                "back": "A",
                "scope": "user",
                "lesson_id": ids["lesson_id"],
            },
        )
        resp = await client.get(f"/api/v1/lessons/{ids['lesson_id']}/flashcards")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_unit_flashcards_empty(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (fc unit)")
        unit_id = await _create_unit(client, course_id)
        resp = await client.get(f"/api/v1/units/{unit_id}/flashcards")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_course_flashcards_empty(self, client: AsyncClient) -> None:
        course_id = await _create_course(client, suffix=" (fc course)")
        resp = await client.get(f"/api/v1/courses/{course_id}/flashcards")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_update_flashcard(self, client: AsyncClient) -> None:
        ids = await self._scaffold(client)
        create_resp = await client.post(
            "/api/v1/flashcards",
            json={
                "front": "Old Q",
                "back": "Old A",
                "scope": "user",
                "lesson_id": ids["lesson_id"],
            },
        )
        card_id = create_resp.json()["id"]
        resp = await client.put(
            f"/api/v1/flashcards/{card_id}", json={"front": "New Q", "back": "New A"}
        )
        assert resp.status_code == 200
        assert resp.json()["front"] == "New Q"

    async def test_update_flashcard_404(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/v1/flashcards/999999", json={"front": "X", "back": "Y"}
        )
        assert resp.status_code == 404

    async def test_delete_flashcard(self, client: AsyncClient) -> None:
        ids = await self._scaffold(client)
        create_resp = await client.post(
            "/api/v1/flashcards",
            json={
                "front": "Del Q",
                "back": "Del A",
                "scope": "user",
                "lesson_id": ids["lesson_id"],
            },
        )
        card_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/v1/flashcards/{card_id}")
        assert resp.status_code == 204

    async def test_delete_flashcard_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/v1/flashcards/999999")
        assert resp.status_code == 404


# ===========================================================================
# Users router — /me and permission-gated endpoints
# ===========================================================================


@pytest.mark.asyncio(loop_scope="session")
class TestUsersRouter:
    async def test_get_me(self, client: AsyncClient, mock_user: dict) -> None:
        resp = await client.get("/api/me")
        assert resp.status_code == 200
        data = resp.json()
        # mock_user.id == 1 but since the DB may not have that row, the endpoint
        # calls get_user_roles_with_permissions which returns [] for unknown id.
        # The key assertion: it returns 200 and the user shape.
        assert "email" in data
        assert "roles" in data

    async def test_auth_register_new_user(self, client: AsyncClient) -> None:
        import uuid

        email = f"newuser_{uuid.uuid4().hex[:8]}@example.com"
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "secret123", "name": "New User"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_auth_register_duplicate_returns_409(
        self, client: AsyncClient
    ) -> None:
        import uuid

        email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "secret123", "name": "Dup User"},
        )
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "secret123", "name": "Dup User"},
        )
        assert resp.status_code == 409

    async def test_auth_login(self, client: AsyncClient) -> None:
        import uuid

        email = f"login_{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "mypassword", "name": "Login User"},
        )
        resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "mypassword"},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_auth_login_wrong_password_401(self, client: AsyncClient) -> None:
        import uuid

        email = f"wrongpw_{uuid.uuid4().hex[:8]}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "correct", "name": "User"},
        )
        resp = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong"},
        )
        assert resp.status_code == 401

    async def test_auth_login_unknown_email_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/auth/login",
            json={"email": "nobody@nowhere.com", "password": "x"},
        )
        assert resp.status_code == 401

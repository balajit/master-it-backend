"""Repository for study plans, lessons, milestones, and checkpoints."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.sequence import (
    CheckpointRow,
    LessonRow,
    MilestoneRow,
    StudyPlanRow,
)
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository
from learning_platform.models.sequence import (
    Checkpoint,
    CheckpointType,
    Lesson,
    LessonType,
    Milestone,
    StudyPlan,
)


class StudyPlanRepository(BaseRepository[StudyPlanRow]):
    """Persists and retrieves ``StudyPlan`` instances."""

    model_class = StudyPlanRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._lesson_repo = LessonRepository(session)
        self._milestone_repo = MilestoneRepository(session)
        self._checkpoint_repo = CheckpointRepository(session)

    async def save_plan(self, plan: StudyPlan, document_id: UUID) -> None:
        """Persist a full study plan with all child entities."""
        plan_id = plan.id

        plan_row = StudyPlanRow(
            id=plan_id,
            document_id=document_id,
            title=plan.title,
            description=plan.description,
            total_estimated_minutes=plan.total_estimated_minutes,
            total_lessons=plan.total_lessons,
            metadata_json=plan.metadata,
        )
        await self.save(plan_row)

        milestone_rows = [
            self._milestone_repo._milestone_to_row(milestone, plan_id)
            for milestone in plan.milestones
        ]
        lesson_rows = [
            self._lesson_repo._lesson_to_row(lesson, plan_id) for lesson in plan.lessons
        ]
        checkpoint_rows = [
            self._checkpoint_repo._checkpoint_to_row(checkpoint, plan_id)
            for checkpoint in plan.checkpoints
        ]

        if milestone_rows:
            await self._milestone_repo.save_all(milestone_rows)
        if lesson_rows:
            await self._lesson_repo.save_all(lesson_rows)
        if checkpoint_rows:
            await self._checkpoint_repo.save_all(checkpoint_rows)

    async def find_by_document(self, document_id: UUID) -> StudyPlan | None:
        """Load the study plan for a document."""
        stmt = select(StudyPlanRow).where(StudyPlanRow.document_id == document_id)
        result = await self._session.execute(stmt)
        plan_row = result.scalars().first()
        if plan_row is None:
            return None

        milestones = await self._milestone_repo.find_by_plan(plan_row.id)
        lessons = await self._lesson_repo.find_by_plan(plan_row.id)
        checkpoints = await self._checkpoint_repo.find_by_plan(plan_row.id)

        return StudyPlan(
            id=plan_row.id,
            title=plan_row.title,
            description=plan_row.description,
            lessons=lessons,
            milestones=milestones,
            checkpoints=checkpoints,
            total_estimated_minutes=plan_row.total_estimated_minutes,
            total_lessons=plan_row.total_lessons,
            metadata=plan_row.metadata_json or {},
        )

    async def delete_by_document(self, document_id: UUID) -> int:
        """Delete plan and all child entities for a document."""
        stmt = select(StudyPlanRow).where(StudyPlanRow.document_id == document_id)
        result = await self._session.execute(stmt)
        plans = result.scalars().all()
        count = 0
        for p in plans:
            await self._checkpoint_repo.delete_by_plan(p.id)
            await self._lesson_repo.delete_by_plan(p.id)
            await self._milestone_repo.delete_by_plan(p.id)
            await self._session.delete(p)
            count += 1
        await self._session.flush()
        return count


class LessonRepository(BaseRepository[LessonRow]):
    """Persists and retrieves ``Lesson`` instances."""

    model_class = LessonRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _save_lesson(self, lesson: Lesson, plan_id: UUID) -> UUID:
        row = self._lesson_to_row(lesson, plan_id)
        await self.save(row)
        return row.id

    @staticmethod
    def _lesson_to_row(lesson: Lesson, plan_id: UUID) -> LessonRow:
        return LessonRow(
            id=lesson.id,
            study_plan_id=plan_id,
            milestone_id=lesson.milestone_id,
            unit_id=lesson.unit_id,
            order=lesson.order,
            title=lesson.title,
            description=lesson.description,
            lesson_type=lesson.lesson_type.value,
            difficulty=lesson.difficulty,
            estimated_minutes=lesson.estimated_minutes,
            learning_objectives_json=lesson.learning_objectives,
            prerequisites_json=[str(uid) for uid in lesson.prerequisites],
            metadata_json=lesson.metadata,
        )

    async def find_by_plan(self, plan_id: UUID) -> list[Lesson]:
        stmt = select(LessonRow).where(LessonRow.study_plan_id == plan_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_plan(self, plan_id: UUID) -> None:
        from sqlalchemy import delete

        stmt = delete(LessonRow).where(LessonRow.study_plan_id == plan_id)
        await self._session.execute(stmt)

    @staticmethod
    def _to_domain(row: LessonRow) -> Lesson:
        return Lesson(
            id=row.id,
            unit_id=row.unit_id,
            order=row.order,
            title=row.title,
            description=row.description,
            learning_objectives=row.learning_objectives_json or [],
            lesson_type=LessonType(row.lesson_type),
            difficulty=row.difficulty,
            estimated_minutes=row.estimated_minutes,
            milestone_id=row.milestone_id,
            prerequisites=[UUID(u) for u in (row.prerequisites_json or [])],
            metadata=row.metadata_json or {},
        )


class MilestoneRepository(BaseRepository[MilestoneRow]):
    """Persists and retrieves ``Milestone`` instances."""

    model_class = MilestoneRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _save_milestone(self, milestone: Milestone, plan_id: UUID) -> UUID:
        row = self._milestone_to_row(milestone, plan_id)
        await self.save(row)
        return row.id

    @staticmethod
    def _milestone_to_row(milestone: Milestone, plan_id: UUID) -> MilestoneRow:
        return MilestoneRow(
            id=milestone.id,
            study_plan_id=plan_id,
            order=milestone.order,
            title=milestone.title,
            description=milestone.description,
            estimated_minutes=milestone.estimated_minutes,
            lesson_ids_json=[str(uid) for uid in milestone.lesson_ids],
            metadata_json=milestone.metadata,
        )

    async def find_by_plan(self, plan_id: UUID) -> list[Milestone]:
        stmt = select(MilestoneRow).where(MilestoneRow.study_plan_id == plan_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_plan(self, plan_id: UUID) -> None:
        from sqlalchemy import delete

        stmt = delete(MilestoneRow).where(MilestoneRow.study_plan_id == plan_id)
        await self._session.execute(stmt)

    @staticmethod
    def _to_domain(row: MilestoneRow) -> Milestone:
        return Milestone(
            id=row.id,
            order=row.order,
            title=row.title,
            description=row.description,
            estimated_minutes=row.estimated_minutes,
            lesson_ids=[UUID(u) for u in (row.lesson_ids_json or [])],
            metadata=row.metadata_json or {},
        )


class CheckpointRepository(BaseRepository[CheckpointRow]):
    """Persists and retrieves ``Checkpoint`` instances."""

    model_class = CheckpointRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _save_checkpoint(self, cp: Checkpoint, plan_id: UUID) -> UUID:
        row = self._checkpoint_to_row(cp, plan_id)
        await self.save(row)
        return row.id

    @staticmethod
    def _checkpoint_to_row(cp: Checkpoint, plan_id: UUID) -> CheckpointRow:
        return CheckpointRow(
            id=cp.id,
            study_plan_id=plan_id,
            milestone_id=cp.milestone_id,
            order=cp.order,
            title=cp.title,
            checkpoint_type=cp.checkpoint_type.value,
            estimated_minutes=cp.estimated_minutes,
            lesson_ids_json=[str(uid) for uid in cp.lesson_ids],
            metadata_json=cp.metadata,
        )

    async def find_by_plan(self, plan_id: UUID) -> list[Checkpoint]:
        stmt = select(CheckpointRow).where(CheckpointRow.study_plan_id == plan_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_plan(self, plan_id: UUID) -> None:
        from sqlalchemy import delete

        stmt = delete(CheckpointRow).where(CheckpointRow.study_plan_id == plan_id)
        await self._session.execute(stmt)

    @staticmethod
    def _to_domain(row: CheckpointRow) -> Checkpoint:
        return Checkpoint(
            id=row.id,
            milestone_id=row.milestone_id,
            order=row.order,
            title=row.title,
            checkpoint_type=CheckpointType(row.checkpoint_type),
            estimated_minutes=row.estimated_minutes,
            lesson_ids=[UUID(u) for u in (row.lesson_ids_json or [])],
            metadata=row.metadata_json or {},
        )

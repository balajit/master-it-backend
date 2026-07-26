"""Mapping API routes — endpoints for document mapping management.

These routes expose presentation models instead of canonical pipeline models.
Updating mappings does NOT rerun the document pipeline — only regenerates
presentation objects.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from learning_platform.presentation.mappers.configuration import (
    MappingConfiguration,
)
from learning_platform.presentation.mappers.context import ProgressContext
from schemas_mapping import (
    ExerciseOptionSchema,
    LessonCardSchema,
    MappingConfigurationSchema,
    MappingResponse,
    MappingUpdateRequest,
    MappingUpdateResponse,
    NavigationNodeSchema,
    NodeRefSchema,
    PageViewSchema,
    PracticeCardSchema,
    ProgressSummarySchema,
    QuizCardSchema,
    RegenerateResponse,
    ResetResponse,
    SectionSchema,
    StatusLegendSchema,
    UnitCardSchema,
)
from services.mapping import (
    generate_preview,
    generate_study_experience,
    get_mapping_configuration,
    reset_mapping_configuration,
    save_mapping_configuration,
)

router: APIRouter = APIRouter(
    prefix="/api/documents",
    tags=["mapping"],
)
logger: logging.Logger = logging.getLogger(__name__)


def _progress_context_from_user(
    user: Dict[str, Any],
    doc_id: str,
) -> ProgressContext:
    """Create a ProgressContext from the authenticated user.

    In production, this would load actual progress data from the database.
    For now, it creates a minimal context.
    """
    return ProgressContext(
        user_id=user["id"],
        course_id=0,  # Would be resolved from document
    )


def _node_refs_to_schema(refs: list[Any]) -> list[NodeRefSchema]:
    """Convert a list of NodeRef objects to NodeRefSchema objects."""
    return [NodeRefSchema(node_id=str(r.node_id), summary=r.summary) for r in refs]


def _study_experience_to_response(
    doc_id: str,
    experience: Any,
    config: MappingConfiguration,
) -> MappingResponse:
    """Convert a StudyExperience to a MappingResponse."""
    config_schema = MappingConfigurationSchema(
        section={
            "grouping": config.section.grouping,
            "title_template": config.section.title_template,
            "show_empty_sections": config.section.show_empty_sections,
            "min_lessons_per_section": config.section.min_lessons_per_section,
        },
        lesson={
            "grouping": config.lesson.grouping,
            "ordering": config.lesson.ordering,
            "show_learning_objectives": config.lesson.show_learning_objectives,
            "show_difficulty": config.lesson.show_difficulty,
            "show_estimated_time": config.lesson.show_estimated_time,
        },
        practice={
            "grouping": config.practice.grouping,
            "ordering": config.practice.ordering,
            "default_required_correct": config.practice.default_required_correct,
            "default_total_questions": config.practice.default_total_questions,
        },
        quiz={
            "placement": config.quiz.placement,
            "ordering": config.quiz.ordering,
            "show_time_limit": config.quiz.show_time_limit,
            "show_passing_score": config.quiz.show_passing_score,
        },
        goal={
            "placement": config.goal.placement,
            "show_completed_count": config.goal.show_completed_count,
            "show_estimated_time": config.goal.show_estimated_time,
        },
        study_time={
            "strategy": config.study_time.strategy,
            "fixed_minutes_per_lesson": config.study_time.fixed_minutes_per_lesson,
            "words_per_minute": config.study_time.words_per_minute,
            "exercise_minutes_each": config.study_time.exercise_minutes_each,
        },
        navigation={
            "include_root": config.navigation.include_root,
            "highlight_current": config.navigation.highlight_current,
            "show_status": config.navigation.show_status,
            "max_depth": config.navigation.max_depth,
        },
        status_legend={
            "show_legend": config.status_legend.show_legend,
        },
        ordering=config.ordering,
    )

    return MappingResponse(
        doc_id=doc_id,
        configuration=config_schema,
        unit=UnitCardSchema(
            unit_id=str(experience.unit.unit_id),
            title=experience.unit.title,
            description=experience.unit.description,
            difficulty=experience.unit.difficulty,
            estimated_minutes=experience.unit.estimated_minutes,
            total_sections=experience.unit.total_sections,
            total_lessons=experience.unit.total_lessons,
            course_id=experience.unit.course_id,
            progress_pct=experience.unit.progress_pct,
        ),
        sections=[
            SectionSchema(
                section_id=str(s.section_id),
                unit_id=str(s.unit_id),
                title=s.title,
                order=s.order,
                estimated_minutes=s.estimated_minutes,
                lesson_count=s.lesson_count,
                practice_count=s.practice_count,
                quiz_count=s.quiz_count,
                completed_count=s.completed_count,
                start_page=s.start_page,
                end_page=s.end_page,
            )
            for s in experience.sections
        ],
        lessons=[
            LessonCardSchema(
                lesson_id=str(lesson.lesson_id),
                unit_id=str(lesson.unit_id),
                section_id=str(lesson.section_id),
                title=lesson.title,
                description=lesson.description,
                order=lesson.order,
                duration_minutes=lesson.duration_minutes,
                difficulty=lesson.difficulty,
                status=lesson.status,
                learning_objectives=[
                    {
                        "text": o.text,
                        "annotation_id": str(o.annotation_id)
                        if o.annotation_id
                        else None,
                        "order": o.order,
                    }
                    for o in lesson.learning_objectives
                ],
                start_page=lesson.start_page,
                end_page=lesson.end_page,
                completed_at=lesson.completed_at,
                content_references=_node_refs_to_schema(lesson.content_references),
                definitions=_node_refs_to_schema(lesson.definitions),
                examples=_node_refs_to_schema(lesson.examples),
                figures=_node_refs_to_schema(lesson.figures),
                tables=_node_refs_to_schema(lesson.tables),
                equations=_node_refs_to_schema(lesson.equations),
            )
            for lesson in experience.lessons
        ],
        practices=[
            PracticeCardSchema(
                practice_id=str(p.practice_id),
                unit_id=str(p.unit_id),
                section_id=str(p.section_id),
                title=p.title,
                order=p.order,
                required_correct=p.required_correct,
                total_questions=p.total_questions,
                status=p.status,
                attempts=p.attempts,
                best_score=p.best_score,
                question_text=p.question_text,
                exercise_type=p.exercise_type,
                options=[
                    ExerciseOptionSchema(
                        label=o.label,
                        text=o.text,
                        is_correct=o.is_correct,
                        explanation=o.explanation,
                    )
                    for o in p.options
                ],
                solution=p.solution,
                explanation=p.explanation,
            )
            for p in experience.practices
        ],
        quizzes=[
            QuizCardSchema(
                quiz_id=str(q.quiz_id),
                unit_id=str(q.unit_id),
                section_id=str(q.section_id),
                title=q.title,
                order=q.order,
                total_points=q.total_points,
                passing_points=q.passing_points,
                time_limit_minutes=q.time_limit_minutes,
                status=q.status,
                score=q.score,
                completed_at=q.completed_at,
            )
            for q in experience.quizzes
        ],
        milestones=[
            {
                "milestone_id": str(m.milestone_id),
                "unit_id": str(m.unit_id),
                "title": m.title,
                "description": m.description,
                "order": m.order,
                "estimated_minutes": m.estimated_minutes,
                "lesson_count": m.lesson_count,
                "completed_lesson_count": m.completed_lesson_count,
                "status": m.status,
            }
            for m in experience.milestones
        ],
        pages=[
            PageViewSchema(
                page_number=p.page_number,
                title=p.title,
                text_preview=p.text_preview,
                full_text=p.full_text,
                unit_ids=[str(uid) for uid in p.unit_ids],
                annotation_ids=[str(aid) for aid in p.annotation_ids],
                concept_ids=[str(cid) for cid in p.concept_ids],
            )
            for p in experience.pages
        ],
        progress=ProgressSummarySchema(
            total_items=experience.progress.total_items,
            completed_items=experience.progress.completed_items,
            mastery_pct=experience.progress.mastery_pct,
            total_minutes_studied=experience.progress.total_minutes_studied,
            estimated_remaining_minutes=experience.progress.estimated_remaining_minutes,
        ),
        navigation=[
            NavigationNodeSchema(
                node_id=str(n.node_id),
                node_type=n.node_type.value,
                title=n.title,
                parent_id=str(n.parent_id) if n.parent_id else None,
                children_ids=[str(c) for c in n.children_ids],
                unit_id=str(n.unit_id) if n.unit_id else None,
                order=n.order,
                is_current=n.is_current,
                is_accessible=n.is_accessible,
                status=n.status,
            )
            for n in experience.navigation
        ],
        status_legend=[
            StatusLegendSchema(
                status=sl.status,
                label=sl.label,
                description=sl.description,
                icon_name=sl.icon_name,
                color_hex=sl.color_hex,
            )
            for sl in experience.status_legend
        ],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/{doc_id}/mapping", response_model=MappingResponse)
async def get_mapping(
    doc_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> MappingResponse:
    """Get the current mapping for a document.

    Returns the presentation model with the current configuration.
    """
    try:
        config = get_mapping_configuration(doc_id)
        progress = _progress_context_from_user(user, doc_id)
        experience = generate_study_experience(doc_id, progress, config)
        return _study_experience_to_response(doc_id, experience, config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{doc_id}/mapping", response_model=MappingUpdateResponse)
async def update_mapping(
    doc_id: str,
    payload: MappingUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> MappingUpdateResponse:
    """Update the mapping configuration for a document.

    This does NOT rerun the document pipeline. It only updates
    the configuration and regenerates presentation objects.
    """
    config = payload.configuration.to_mapping_config()
    save_mapping_configuration(doc_id, config)

    logger.info(
        "Mapping configuration updated for document %s by user %s",
        doc_id,
        user["id"],
    )

    return MappingUpdateResponse(
        doc_id=doc_id,
        configuration=payload.configuration,
        message="Mapping updated successfully",
    )


@router.post("/{doc_id}/mapping/regenerate", response_model=RegenerateResponse)
async def regenerate_mapping(
    doc_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> RegenerateResponse:
    """Regenerate the presentation for a document.

    This does NOT rerun the document pipeline. It only regenerates
    presentation objects using the current configuration.
    """
    config = get_mapping_configuration(doc_id)

    logger.info(
        "Presentation regenerated for document %s by user %s",
        doc_id,
        user["id"],
    )

    return RegenerateResponse(
        doc_id=doc_id,
        configuration=MappingConfigurationSchema(
            section={"grouping": config.section.grouping},
            lesson={"ordering": config.lesson.ordering},
            practice={"grouping": config.practice.grouping},
            quiz={"placement": config.quiz.placement},
            goal={"placement": config.goal.placement},
            ordering=config.ordering,
        ),
        message="Presentation regenerated successfully",
    )


@router.post("/{doc_id}/mapping/reset", response_model=ResetResponse)
async def reset_mapping(
    doc_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> ResetResponse:
    """Reset the mapping configuration to defaults.

    This does NOT rerun the document pipeline. It only resets
    the configuration and regenerates presentation objects.
    """
    config = reset_mapping_configuration(doc_id)

    logger.info(
        "Mapping configuration reset to defaults for document %s by user %s",
        doc_id,
        user["id"],
    )

    return ResetResponse(
        doc_id=doc_id,
        configuration=MappingConfigurationSchema(
            section={"grouping": config.section.grouping},
            lesson={"ordering": config.lesson.ordering},
            practice={"grouping": config.practice.grouping},
            quiz={"placement": config.quiz.placement},
            goal={"placement": config.goal.placement},
            ordering=config.ordering,
        ),
        message="Mapping reset to defaults",
    )


@router.get("/{doc_id}/mapping/preview", response_model=MappingResponse)
async def preview_mapping(
    doc_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> MappingResponse:
    """Preview the mapping for a document.

    Returns a preview of the presentation model without modifying
    any stored state.
    """
    try:
        config = get_mapping_configuration(doc_id)
        experience = generate_preview(doc_id, config)
        return _study_experience_to_response(doc_id, experience, config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

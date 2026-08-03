"""Default deterministic rule set for triage."""

from __future__ import annotations

from learning_platform.agentic_ops.rules.models import (
    CrossTableMinimumRule,
    ForeignKeyIntegrityRule,
    RequiredColumnsRule,
    RuleSet,
    TableNonEmptyRule,
)


def build_default_rule_set() -> RuleSet:
    """Return phase-1 default rules for core master/LP consistency."""
    return RuleSet(
        name="default-db-triage",
        version="1.0.0",
        rules=[
            TableNonEmptyRule(
                id="table.documents.non_empty",
                description="documents table must contain at least one row",
                severity="error",
                table_name="documents",
            ),
            TableNonEmptyRule(
                id="table.course_documents.non_empty",
                description="course_documents table must contain at least one row",
                severity="error",
                table_name="course_documents",
            ),
            TableNonEmptyRule(
                id="table.lp_documents.non_empty",
                description="lp_documents table must contain at least one row",
                severity="warning",
                table_name="lp_documents",
            ),
            RequiredColumnsRule(
                id="columns.documents.storage_path.required",
                description="documents.storage_path must be populated",
                severity="error",
                table_name="documents",
                columns=["storage_path"],
            ),
            RequiredColumnsRule(
                id="columns.lessons.plan_lesson_id.required",
                description="lessons.plan_lesson_id should be present for LP-linked courses",
                severity="warning",
                table_name="lessons",
                columns=["plan_lesson_id"],
            ),
            ForeignKeyIntegrityRule(
                id="fk.course_documents.document_id.documents.id",
                description="course_documents.document_id must reference documents.id",
                severity="error",
                child_table="course_documents",
                parent_table="documents",
                relation_name="course_documents_document_id_fkey",
            ),
            ForeignKeyIntegrityRule(
                id="fk.units.course_id.courses.id",
                description="units.course_id must reference courses.id",
                severity="error",
                child_table="units",
                parent_table="courses",
                relation_name="units_course_id_fkey",
            ),
            CrossTableMinimumRule(
                id="ratio.lessons.to.sections",
                description="lessons should be at least one per section",
                severity="warning",
                driving_table="sections",
                dependent_table="lessons",
                minimum_ratio=1.0,
            ),
            CrossTableMinimumRule(
                id="ratio.lp_book_page.to.lp_book_lesson",
                description="book pages should exist for each book lesson",
                severity="warning",
                driving_table="lp_book_lesson",
                dependent_table="lp_book_page",
                minimum_ratio=1.0,
            ),
        ],
    )

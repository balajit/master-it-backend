"""Mapping Service — handles mapping operations for documents.

This service manages the mapping configuration and presentation
generation for documents. It does NOT rerun the document pipeline
— only regenerates presentation objects from cached pipeline output.

Pipeline results are stored in the shared ``PipelineCache`` singleton
(``learning_platform.cache.pipeline_cache``), which is populated by the
learning-platform document processing route and consumed here.
"""

from __future__ import annotations

import logging

from learning_platform.cache import pipeline_cache
from learning_platform.pipeline.orchestrator import PipelineResult
from learning_platform.presentation.mappers.configuration import (
    MappingConfiguration,
    create_default_config,
)
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.mappers.learning_experience import (
    PipelineOutput,
    create_learning_experience,
)
from learning_platform.presentation.models import StudyExperience
from services.lp_results import lp_doc_uuid_from_external_id

logger: logging.Logger = logging.getLogger(__name__)

# ── In-memory cache for mapping configurations ──
# In production, this would be stored in the database
_mapping_configs: dict[str, MappingConfiguration] = {}


def get_mapping_configuration(doc_id: str) -> MappingConfiguration:
    """Get the mapping configuration for a document.

    Parameters
    ----------
    doc_id : str
        The document ID.

    Returns
    -------
    MappingConfiguration
        The current mapping configuration.
    """
    return _mapping_configs.get(doc_id, create_default_config())


def save_mapping_configuration(doc_id: str, config: MappingConfiguration) -> None:
    """Save a mapping configuration for a document.

    Parameters
    ----------
    doc_id : str
        The document ID.
    config : MappingConfiguration
        The configuration to save.
    """
    _mapping_configs[doc_id] = config
    logger.info("Mapping configuration saved for document %s", doc_id)


def reset_mapping_configuration(doc_id: str) -> MappingConfiguration:
    """Reset the mapping configuration to defaults.

    Parameters
    ----------
    doc_id : str
        The document ID.

    Returns
    -------
    MappingConfiguration
        The default configuration.
    """
    default_config = create_default_config()
    _mapping_configs[doc_id] = default_config
    logger.info("Mapping configuration reset to defaults for document %s", doc_id)
    return default_config


# ── Pipeline result → output conversion ──────────────────────────────────────


def pipeline_result_to_output(result: PipelineResult) -> PipelineOutput:
    """Convert a ``PipelineResult`` into a ``PipelineOutput`` for the mapper.

    The two models carry the same domain objects under slightly different
    field names.  ``PipelineResult`` is the orchestrator's raw output;
    ``PipelineOutput`` is the mapper's expected input.
    """
    return PipelineOutput(
        document=result.document,
        learning_units=result.units,
        annotations=result.annotations,
        concept_map=result.concepts,
        knowledge_graph=result.graph,
        study_plan=result.study_plan,
        quizzes=[],
        pages=result.pages,
    )


# ── Study experience generation ──────────────────────────────────────────────


def generate_study_experience(
    doc_id: str,
    progress: ProgressContext,
    config: MappingConfiguration | None = None,
) -> StudyExperience:
    """Generate a StudyExperience from the cached pipeline result.

    This function does NOT rerun the document pipeline. It reads the
    ``PipelineResult`` from the shared ``PipelineCache``, converts it
    to a ``PipelineOutput``, and regenerates presentation objects.

    Parameters
    ----------
    doc_id : str
        The document ID.
    progress : ProgressContext
        User progress data.
    config : MappingConfiguration | None
        Optional configuration override. If None, uses saved configuration.

    Returns
    -------
    StudyExperience
        The generated presentation model.

    Raises
    ------
    ValueError
        If no pipeline result is cached for this document.
    """
    cached_result: PipelineResult | None = pipeline_cache.get(doc_id)
    if cached_result is None:
        doc_uuid = lp_doc_uuid_from_external_id(doc_id)
        if doc_uuid is not None:
            cached_result = pipeline_cache.get(str(doc_uuid))
            if cached_result is not None:
                pipeline_cache.set(doc_id, cached_result)
    if cached_result is None:
        raise ValueError(f"No pipeline result cached for document {doc_id}")

    pipeline_output = pipeline_result_to_output(cached_result)

    if config is None:
        config = get_mapping_configuration(doc_id)

    return create_learning_experience(pipeline_output, progress, config)


def generate_preview(
    doc_id: str,
    config: MappingConfiguration | None = None,
) -> StudyExperience:
    """Generate a preview of the StudyExperience.

    This is similar to generate_study_experience but uses a default
    progress context for preview purposes.

    Parameters
    ----------
    doc_id : str
        The document ID.
    config : MappingConfiguration | None
        Optional configuration override.

    Returns
    -------
    StudyExperience
        The preview presentation model.

    Raises
    ------
    ValueError
        If no pipeline result is cached for this document.
    """
    progress = ProgressContext(
        user_id=0,  # Preview user
        course_id=0,
    )

    return generate_study_experience(doc_id, progress, config)


def list_cached_documents() -> list[str]:
    """List all document IDs with cached pipeline results.

    Returns
    -------
    list[str]
        List of document IDs.
    """
    return pipeline_cache.keys()

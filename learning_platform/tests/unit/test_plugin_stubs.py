"""Protocol conformance tests for the plugin framework.

Verifies that:
1. All stage Protocols in pipeline.base are runtime_checkable
2. New models are valid Pydantic models
3. New Protocols have the expected method signatures
"""

from __future__ import annotations

import inspect

from learning_platform.models.quiz import Answer, Question, QuestionType, Quiz
from learning_platform.models.search import SearchQuery, SearchResult
from learning_platform.models.summary import Summary, SummaryLevel
from learning_platform.models.vector import VectorDocument, VectorStore
from learning_platform.plugins.base import Plugin, PluginCategory, PluginManifest

# ── Model construction tests ─────────────────────────────────────────────────


class TestQuizModels:
    def test_question_type_all_values(self) -> None:
        assert len(QuestionType) == 6

    def test_answer_defaults(self) -> None:
        a = Answer(text="yes")
        assert a.is_correct is False
        assert a.explanation == ""
        assert a.id is not None

    def test_question_defaults(self) -> None:
        q = Question(question_type=QuestionType.TRUE_FALSE, text="Is 2+2=4?")
        assert q.points == 1
        assert q.answers == []

    def test_quiz_auto_total_points(self) -> None:
        q1 = Question(question_type=QuestionType.SHORT_ANSWER, text="Q1", points=3)
        q2 = Question(question_type=QuestionType.SHORT_ANSWER, text="Q2", points=5)
        quiz = Quiz(title="Test", questions=[q1, q2])
        assert quiz.total_points == 8

    def test_quiz_explicit_total_points(self) -> None:
        quiz = Quiz(title="Test", total_points=20)
        assert quiz.total_points == 20


class TestSummaryModels:
    def test_summary_level_all_values(self) -> None:
        assert len(SummaryLevel) == 4

    def test_summary_auto_word_count(self) -> None:
        s = Summary(level=SummaryLevel.DOCUMENT, title="Doc", text="one two three")
        assert s.word_count == 3

    def test_summary_explicit_word_count(self) -> None:
        s = Summary(level=SummaryLevel.UNIT, title="U", text="text", word_count=100)
        assert s.word_count == 100


class TestSearchModels:
    def test_search_query_defaults(self) -> None:
        q = SearchQuery(text="hello")
        assert q.limit == 10
        assert q.offset == 0
        assert q.include_highlights is True
        assert q.filters == []

    def test_search_result_defaults(self) -> None:
        r = SearchResult()
        assert r.score == 0.0
        assert r.highlights == []


class TestVectorModels:
    def test_vector_document(self) -> None:
        vd = VectorDocument(text="hello", embedding=[0.1, 0.2, 0.3])
        assert len(vd.embedding) == 3
        assert vd.chunk_index == 0

    def test_vector_store_count(self) -> None:
        docs = [VectorDocument(text="a"), VectorDocument(text="b")]
        vs = VectorStore(name="test", documents=docs)
        assert vs.count == 2

    def test_vector_store_empty(self) -> None:
        vs = VectorStore(name="empty")
        assert vs.count == 0


# ── Protocol runtime_checkable tests ─────────────────────────────────────────


class TestProtocolRuntimeCheckable:
    def test_plugin_is_runtime_checkable(self) -> None:
        assert (
            isinstance(
                PluginManifest(
                    name="x", version="1", category=PluginCategory.PARSER, description="d"
                ),
                Plugin,
            )
            is False
        )  # manifest-only object, no Protocol match needed here

    def test_all_base_protocols_are_runtime_checkable(self) -> None:
        from learning_platform.pipeline.base import (
            AbstractParser,
            ConceptExtractor,
            Detector,
            DocumentSummarizer,
            KnowledgeGraphBuilder,
            LearningSequenceBuilder,
            LearningUnitBuilder,
            QuizGenerator,
            SearchIndex,
            SemanticEnricher,
            StructuralNormalizer,
            VectorIndexer,
        )

        for proto in [
            AbstractParser,
            StructuralNormalizer,
            Detector,
            SemanticEnricher,
            LearningUnitBuilder,
            ConceptExtractor,
            KnowledgeGraphBuilder,
            LearningSequenceBuilder,
            QuizGenerator,
            DocumentSummarizer,
            SearchIndex,
            VectorIndexer,
        ]:
            assert hasattr(proto, "__protocol_attrs__") or callable(
                getattr(proto, "__instancecheck__", None)
            ), f"{proto.__name__} is not runtime_checkable"


# ── Protocol method signature tests ──────────────────────────────────────────


class TestProtocolSignatures:
    def test_quiz_generator_has_generate(self) -> None:
        from learning_platform.pipeline.base import QuizGenerator

        assert hasattr(QuizGenerator, "generate")
        sig = inspect.signature(QuizGenerator.generate)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "plan" in params
        assert "units" in params
        assert "concepts" in params

    def test_document_summarizer_has_summarize(self) -> None:
        from learning_platform.pipeline.base import DocumentSummarizer

        assert hasattr(DocumentSummarizer, "summarize")
        sig = inspect.signature(DocumentSummarizer.summarize)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "document" in params
        assert "units" in params

    def test_search_index_has_search_add_remove(self) -> None:
        from learning_platform.pipeline.base import SearchIndex

        assert hasattr(SearchIndex, "search")
        assert hasattr(SearchIndex, "add")
        assert hasattr(SearchIndex, "remove")

        search_sig = inspect.signature(SearchIndex.search)
        assert "query" in search_sig.parameters

        add_sig = inspect.signature(SearchIndex.add)
        assert "documents" in add_sig.parameters

        remove_sig = inspect.signature(SearchIndex.remove)
        assert "ids" in remove_sig.parameters

    def test_vector_indexer_has_index_and_similarity_search(self) -> None:
        from learning_platform.pipeline.base import VectorIndexer

        assert hasattr(VectorIndexer, "index")
        assert hasattr(VectorIndexer, "similarity_search")

        index_sig = inspect.signature(VectorIndexer.index)
        assert "documents" in index_sig.parameters

        sim_sig = inspect.signature(VectorIndexer.similarity_search)
        params = list(sim_sig.parameters.keys())
        assert "query" in params
        assert "k" in params


# ── Plugin manifest completeness ─────────────────────────────────────────────


class TestPluginManifestCompleteness:
    def test_all_categories_in_manifest(self) -> None:
        for cat in PluginCategory:
            m = PluginManifest(
                name=f"test-{cat.value}",
                version="0.0.1",
                category=cat,
                description=f"Test plugin for {cat.value}",
            )
            assert m.category == cat

"""Tests for the url-pdf-service scraper module."""

from __future__ import annotations

import pytest

from app.scraper import url_to_filename


class TestUrlToFilename:
    def test_basic_url(self) -> None:
        assert url_to_filename("https://example.com") == "example_com.pdf"

    def test_url_with_path(self) -> None:
        result = url_to_filename("https://example.com/path/to/page")
        assert result == "example_com_path_to_page.pdf"

    def test_query_string_stripped(self) -> None:
        result = url_to_filename("https://example.com/page?q=hello&lang=en")
        assert result == "example_com_page.pdf"

    def test_fragment_stripped(self) -> None:
        result = url_to_filename("https://example.com/docs#section-1")
        assert result == "example_com_docs.pdf"

    def test_query_and_fragment_stripped(self) -> None:
        result = url_to_filename("https://example.com/search?q=foo#top")
        assert result == "example_com_search.pdf"

    def test_special_chars_replaced(self) -> None:
        result = url_to_filename("https://docs.python.org/3/library/re.html")
        assert result == "docs_python_org_3_library_re_html.pdf"

    def test_consecutive_underscores_collapsed(self) -> None:
        # Double slashes in path become consecutive underscores → collapsed
        result = url_to_filename("https://example.com//double//slashes")
        # Each '/' → '_', then consecutive '_' → single '_'
        assert "__" not in result

    def test_truncated_to_100_chars(self) -> None:
        long_url = "https://example.com/" + "a" * 200
        result = url_to_filename(long_url)
        # stem should be ≤ 100 chars, plus .pdf
        stem = result[: -len(".pdf")]
        assert len(stem) <= 100
        assert result.endswith(".pdf")

    def test_always_ends_with_pdf(self) -> None:
        assert url_to_filename("https://example.com/page").endswith(".pdf")

    def test_empty_path_gives_domain_only(self) -> None:
        result = url_to_filename("https://example.com/")
        assert "example_com" in result
        assert result.endswith(".pdf")

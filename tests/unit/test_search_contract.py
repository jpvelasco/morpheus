"""Unit tests: documented Open WebUI search query URL contract (SRCH-002)."""

from __future__ import annotations

import pytest

from morpheus.core.search_contract import (
    SearchContractError,
    SearchQueryContract,
    SearchResult,
    documented_query_url,
    verify_search_payload,
)

DEFAULT = SearchQueryContract(base_url="http://searxng.test:8080")


def test_documented_query_url_matches_open_webui_shape() -> None:
    url = documented_query_url(DEFAULT, "local AI")
    assert url == "http://searxng.test:8080/search?q=local+AI&format=json"


def test_documented_query_url_encodes_reserved_characters() -> None:
    url = documented_query_url(DEFAULT, "rust & c++ 2026")
    assert "q=rust+%26+c%2B%2B+2026" in url
    assert "&" not in url.split("?")[1].split("&")[0].split("=")[1].replace("%26", "")


def test_documented_query_url_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="between 1 and 512"):
        documented_query_url(DEFAULT, "   ")


def test_documented_query_url_rejects_oversized_query() -> None:
    with pytest.raises(ValueError, match="between 1 and 512"):
        documented_query_url(DEFAULT, "x" * 513)


def test_documented_query_url_rejects_control_characters() -> None:
    with pytest.raises(ValueError, match="control character"):
        documented_query_url(DEFAULT, "line\nbreak")


def test_documented_query_url_rejects_unsafe_base_url() -> None:
    with pytest.raises(ValueError, match="http or https"):
        SearchQueryContract(base_url="file:///etc/passwd")
    with pytest.raises(ValueError, match="embedded credentials"):
        SearchQueryContract(base_url="https://user:pass@host.test:8080")
    with pytest.raises(ValueError, match="path, query, or fragment"):
        SearchQueryContract(base_url="http://host.test:8080/search?x=1")


def test_verify_search_payload_accepts_valid_results() -> None:
    results = verify_search_payload(
        {"results": [{"title": "T", "url": "https://example.test/a", "content": "C"}]}
    )
    assert results == (SearchResult(title="T", url="https://example.test/a", content="C"),)


def test_verify_search_payload_requires_results_list() -> None:
    for payload in ({}, {"results": {}}, {"results": "nope"}):
        with pytest.raises(SearchContractError, match="results list"):
            verify_search_payload(payload)


def test_verify_search_payload_rejects_unsafe_result_urls() -> None:
    with pytest.raises(SearchContractError, match="unsafe"):
        verify_search_payload({"results": [{"title": "T", "url": "file:///etc/passwd"}]})
    with pytest.raises(SearchContractError, match="unsafe"):
        verify_search_payload({"results": [{"title": "T", "url": "javascript:alert(1)"}]})


def test_verify_search_payload_rejects_incompatible_fields() -> None:
    with pytest.raises(SearchContractError, match="incompatible"):
        verify_search_payload({"results": [{"title": 1, "url": "https://x.test", "content": ""}]})
    with pytest.raises(SearchContractError, match="object"):
        verify_search_payload({"results": ["not-an-object"]})


def test_documented_query_url_is_idempotent_for_operator_docs() -> None:
    url = documented_query_url(DEFAULT, "what is a control plane")
    assert url.startswith("http://searxng.test:8080/search?q=")
    assert url.endswith("&format=json")
    assert "format=json" in url
    assert url.count("?") == 1

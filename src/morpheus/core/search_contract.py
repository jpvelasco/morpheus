"""Documented Open WebUI search query URL contract (SRCH-002).

The existing Open WebUI integrates with Morpheus-owned search through one
documented query URL. This module is the canonical source of that contract:
it derives the exact URL an operator can configure, and it verifies that a
live response honors the documented JSON shape. Configuration through the
Open WebUI admin interface remains operator-controlled.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_QUERY_MIN = 1
_QUERY_MAX = 512


class SearchContractError(ValueError):
    """A search response violates the documented JSON contract."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    content: str


@dataclass(frozen=True, slots=True)
class SearchQueryContract:
    base_url: str
    path: str = "/search"
    format_param: str = "format"
    format_value: str = "json"
    query_min: int = _QUERY_MIN
    query_max: int = _QUERY_MAX

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("search base_url must use http or https and have a host")
        if parsed.username or parsed.password:
            raise ValueError("search base_url must not contain embedded credentials")
        if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("search base_url must not contain a path, query, or fragment")


def documented_query_url(contract: SearchQueryContract, query: str) -> str:
    """Return the exact query URL the existing Open WebUI can use."""
    normalized = normalize_query(contract, query)
    from urllib.parse import quote

    encoded = quote(normalized, safe=" ")
    encoded = encoded.replace(" ", "+")
    return urlunsplit(
        (
            urlsplit(contract.base_url).scheme,
            urlsplit(contract.base_url).netloc,
            contract.path,
            f"q={encoded}&{contract.format_param}={contract.format_value}",
            "",
        )
    )


def verify_search_payload(payload: object) -> tuple[SearchResult, ...]:
    """Verify a live search response against the documented JSON contract."""
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SearchContractError("search response must contain a results list")
    results: list[SearchResult] = []
    for item in payload["results"]:
        if not isinstance(item, dict):
            raise SearchContractError("search result must be an object")
        title = item.get("title")
        url = item.get("url")
        content = item.get("content", "")
        if not isinstance(title, str) or not isinstance(url, str) or not isinstance(content, str):
            raise SearchContractError("search result fields are incompatible")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SearchContractError("search result URL is unsafe")
        results.append(SearchResult(title=title, url=url, content=content))
    return tuple(results)


def normalize_query(contract: SearchQueryContract, query: str) -> str:
    """Validate and normalize an operator query for the documented contract."""
    normalized = query.strip()
    if not contract.query_min <= len(normalized) <= contract.query_max:
        raise ValueError(
            f"search query length must be between {contract.query_min} and {contract.query_max}"
        )
    if any(ord(character) < 0x20 or character == "\x7f" for character in normalized):
        raise ValueError("search query must not contain control characters")
    return normalized

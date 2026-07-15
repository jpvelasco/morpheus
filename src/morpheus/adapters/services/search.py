from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class SearchContractError(ValueError):
    """SearXNG returned an incompatible or unsafe result contract."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    content: str


class SearchClient:
    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds

    async def search(self, query: str) -> tuple[SearchResult, ...]:
        normalized_query = query.strip()
        if not 1 <= len(normalized_query) <= 512:
            raise ValueError("search query length must be between 1 and 512 characters")
        response = await self._client.get(
            f"{self._base_url}/search",
            params={"q": normalized_query, "format": "json"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise SearchContractError("search response is not JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise SearchContractError("search response must contain a results list")
        results: list[SearchResult] = []
        for item in payload["results"]:
            if not isinstance(item, dict):
                raise SearchContractError("search result must be an object")
            title = item.get("title")
            url = item.get("url")
            content = item.get("content", "")
            if (
                not isinstance(title, str)
                or not isinstance(url, str)
                or not isinstance(content, str)
            ):
                raise SearchContractError("search result fields are incompatible")
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise SearchContractError("search result URL is unsafe")
            results.append(SearchResult(title=title, url=url, content=content))
        return tuple(results)

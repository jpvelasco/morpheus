from __future__ import annotations

import json

import httpx

from morpheus.core.search_contract import (
    SearchContractError,
    SearchQueryContract,
    SearchResult,
    normalize_query,
    verify_search_payload,
)

__all__ = ["SearchClient", "SearchContractError", "SearchResult"]


class SearchClient:
    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 10,
    ) -> None:
        self._contract = SearchQueryContract(base_url=base_url)
        self._client = client
        self._timeout = timeout_seconds

    async def search(self, query: str) -> tuple[SearchResult, ...]:
        normalized_query = normalize_query(self._contract, query)
        response = await self._client.get(
            f"{self._contract.base_url}/search",
            params={"q": normalized_query, "format": "json"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise SearchContractError("search response is not JSON") from error
        return verify_search_payload(payload)

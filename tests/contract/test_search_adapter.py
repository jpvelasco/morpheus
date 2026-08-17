from __future__ import annotations

import httpx
import pytest

from morpheus.adapters.services.search import SearchClient, SearchContractError
from morpheus.core.search_contract import SearchQueryContract, documented_query_url

pytestmark = pytest.mark.contract


@pytest.mark.asyncio
async def test_SRCH_001_validates_searxng_json_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        assert request.url.params["q"] == "local AI"
        return httpx.Response(
            200,
            json={
                "query": "local AI",
                "results": [
                    {"title": "Result", "url": "https://example.test/result", "content": "Summary"}
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        results = await SearchClient(base_url="http://search.test", client=http).search("local AI")
    assert results[0].title == "Result"
    assert results[0].url == "https://example.test/result"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": {}},
        {"results": [{}]},
        {"results": [{"title": "x", "url": "file:///etc/passwd"}]},
    ],
)
async def test_SRCH_001_rejects_incompatible_or_unsafe_results(payload: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(SearchContractError):
            await SearchClient(base_url="http://search.test", client=http).search("query")


@pytest.mark.asyncio
async def test_SRCH_001_bounds_query_size() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as http:
        with pytest.raises(ValueError, match="between 1 and 512"):
            await SearchClient(base_url="http://search.test", client=http).search("x" * 513)


@pytest.mark.asyncio
async def test_SRCH_002_client_requests_the_documented_query_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://example.test/r", "content": "C"}]},
        )

    contract = SearchQueryContract(base_url="http://search.test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await SearchClient(base_url="http://search.test", client=http).search("local AI")
    assert seen[0] == documented_query_url(contract, "local AI")

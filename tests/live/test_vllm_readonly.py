from __future__ import annotations

import os

import pytest

from morpheus.ops.live_readonly import (
    LiveReadOnlyConfig,
    run_live_readonly_probe,
    safe_live_failure_code,
)

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_LIVE_003_LIVE_004_current_vllm_read_only_contract() -> None:
    if os.environ.get("MORPHEUS_LIVE_TESTS") != "1":
        pytest.skip("live tests require MORPHEUS_LIVE_TESTS=1")

    try:
        config = LiveReadOnlyConfig.from_environment(os.environ)
        report = await run_live_readonly_probe(config)
    except Exception as error:
        pytest.fail(
            f"live read-only probe failed: {safe_live_failure_code(error)}",
            pytrace=False,
        )

    print(report.to_json())  # noqa: T201 - sanitized report is the evidence payload

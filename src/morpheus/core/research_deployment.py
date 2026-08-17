"""Pinned Perplexica research deployment wiring (RSCH-001).

Morpheus deploys a pinned Perplexica service wired to SearXNG and the
configured OpenAI-compatible model. This module is the canonical wiring
contract: every deployment value is validated (pinned image digest,
http(s) endpoints without credentials, bounded model id) and the
Perplexica configuration is rendered deterministically from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from morpheus.core.benchmark import bounded_identifier

_DIGEST_HEX = 64


@dataclass(frozen=True, slots=True)
class ResearchDeployment:
    image_ref: str
    searxng_base_url: str
    llm_base_url: str
    model_id: str
    host_port: int = 7412
    service_port: int = 3000

    def render_config(self) -> str:
        return render_perplexica_config(self)


def _validated_endpoint(value: str, *, what: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{what} must use http or https and have a host")
    if parsed.username or parsed.password:
        raise ValueError(f"{what} must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{what} must not contain a query or fragment")
    return value.rstrip("/")


def _validated_image_ref(value: str) -> str:
    if "@sha256:" not in value:
        raise ValueError("research image must be pinned with a sha256 digest")
    digest = value.rsplit("@sha256:", 1)[1]
    if len(digest) != _DIGEST_HEX or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("research image digest must be a 64-hex-char sha256")
    return value


def validated_research_deployment(
    *,
    image_ref: str,
    searxng_base_url: str,
    llm_base_url: str,
    model_id: str,
    host_port: int = 7412,
    service_port: int = 3000,
) -> ResearchDeployment:
    """Build a research deployment with every wiring value validated."""
    bounded_identifier(model_id, "model id")
    if not 1 <= host_port <= 65_535:
        raise ValueError("research host port must be between 1 and 65535")
    if not 1 <= service_port <= 65_535:
        raise ValueError("research service port must be between 1 and 65535")
    return ResearchDeployment(
        image_ref=_validated_image_ref(image_ref),
        searxng_base_url=_validated_endpoint(searxng_base_url, what="searxng_base_url"),
        llm_base_url=_validated_endpoint(llm_base_url, what="llm_base_url"),
        model_id=model_id,
        host_port=host_port,
        service_port=service_port,
    )


def render_perplexica_config(deployment: ResearchDeployment) -> str:
    """Render the deterministic Perplexica configuration for a deployment."""
    return "\n".join(
        (
            "[GENERAL]",
            f"PORT = {deployment.service_port}",
            'SIMILARITY_MEASURE = "cosine"',
            "",
            "[API_ENDPOINTS]",
            f'SEARXNG = "{deployment.searxng_base_url}"',
            f'OPENAI = "{deployment.llm_base_url}"',
            "",
            "[MODEL]",
            f'NAME = "{deployment.model_id}"',
            "",
        )
    )

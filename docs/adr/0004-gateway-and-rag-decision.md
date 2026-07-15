# ADR-0004: Defer LiteLLM and Independent RAG

Status: Accepted

The current deployment has one external model endpoint. Morpheus's telemetry
proxy already supplies the demonstrated authentication and observability need,
so LiteLLM would add an unnecessary routing dependency. The direct vLLM path is
preserved.

Open WebUI already owns a local vector store, and no independent corpus or
retrieval use case has been supplied. Qdrant and a separate embedding service
remain disabled. This decision must be revisited with a measured unmet retrieval
case, relevance judgments, privacy constraints, and a reindex plan.

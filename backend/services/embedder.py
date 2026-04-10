"""
Embedder backed by Ollama's nomic-embed-text model.
Uses the /api/embed endpoint (batch-capable, added in Ollama 0.1.31+).
Falls back to sequential /api/embeddings calls for older Ollama versions.
"""
from __future__ import annotations

import httpx

from config import EMBEDDING_MODEL, OLLAMA_BASE_URL

_EMBED_URL = f"{OLLAMA_BASE_URL}/api/embed"
_EMBED_LEGACY_URL = f"{OLLAMA_BASE_URL}/api/embeddings"


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per input text."""
    if not texts:
        return []

    # Try batch endpoint first (Ollama ≥ 0.1.31)
    try:
        resp = httpx.post(
            _EMBED_URL,
            json={"model": EMBEDDING_MODEL, "input": texts},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["embeddings"]
    except httpx.HTTPError:
        pass

    # Legacy endpoint: one request per text
    vectors = []
    for text in texts:
        resp = httpx.post(
            _EMBED_LEGACY_URL,
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        vectors.append(resp.json()["embedding"])
    return vectors

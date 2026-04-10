"""
Qdrant client wrapper.
Collections are created lazily — one per context ("global" or "session:<id>").
"""
from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
)

from config import QDRANT_HOST, QDRANT_PORT, EMBEDDING_DIM


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def _ensure_collection(collection: str):
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )


def upsert_chunks(
    collection: str,
    file_id: str,
    filename: str,
    chunks: list[str],
    vectors: list[list[float]],
):
    _ensure_collection(collection)
    client = get_client()

    points = [
        PointStruct(
            id=f"{file_id}_{i}",
            vector=vectors[i],
            payload={
                "file_id": file_id,
                "filename": filename,
                "text": chunks[i],
                "chunk_index": i,
            },
        )
        for i in range(len(chunks))
    ]
    client.upsert(collection_name=collection, points=points)


def search(
    collection: str,
    query_vector: list[float],
    limit: int = 5,
    file_id: str | None = None,
) -> list[dict]:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        return []

    query_filter = None
    if file_id:
        query_filter = Filter(
            must=[FieldCondition(key="file_id", match=MatchValue(value=file_id))]
        )

    hits = client.search(
        collection_name=collection,
        query_vector=query_vector,
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
    )
    return [
        {
            "score": h.score,
            "text": h.payload["text"],
            "filename": h.payload["filename"],
            "file_id": h.payload["file_id"],
            "chunk_index": h.payload["chunk_index"],
        }
        for h in hits
    ]


def delete_file_vectors(collection: str, file_id: str):
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        return
    client.delete(
        collection_name=collection,
        points_selector=Filter(
            must=[FieldCondition(key="file_id", match=MatchValue(value=file_id))]
        ),
    )

"""
POST /query       — RAG retrieval (context snippets + sources)
POST /query/chat  — RAG-augmented Ollama streaming chat
"""
import json
from typing import AsyncGenerator

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import OLLAMA_URL, OLLAMA_DEFAULT_MODEL, GLOBAL_COLLECTION
from services.embedder import embed_texts
from services import vector_store

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None   # if set, also searches session collection
    top_k: int = 5


class ChatRequest(BaseModel):
    messages: list[dict]            # [{role, content}, ...]
    session_id: str | None = None
    model: str = OLLAMA_DEFAULT_MODEL
    top_k: int = 5


def _retrieve(question: str, session_id: str | None, top_k: int) -> list[dict]:
    """Embed question, search global + optional session collection, merge by score."""
    vector = embed_texts([question])[0]
    per_collection = max(top_k, 3)

    hits = vector_store.search(GLOBAL_COLLECTION, vector, limit=per_collection)

    if session_id:
        session_hits = vector_store.search(
            f"session:{session_id}", vector, limit=per_collection
        )
        hits = sorted(hits + session_hits, key=lambda h: h["score"], reverse=True)

    return hits[:top_k]


@router.post("")
async def retrieve(req: QueryRequest):
    """Pure retrieval — returns context chunks and sources (no LLM call)."""
    hits = _retrieve(req.question, req.session_id, req.top_k)
    return {
        "hits": hits,
        "context": "\n\n---\n\n".join(h["text"] for h in hits),
        "sources": list({h["filename"] for h in hits}),
    }


@router.post("/chat")
async def rag_chat(req: ChatRequest):
    """
    RAG-augmented streaming chat:
      1. Retrieve context for the last user message
      2. Inject context into system prompt
      3. Stream Ollama response back as SSE
    """
    # Find last user message for retrieval
    last_user = next(
        (m["content"] for m in reversed(req.messages) if m["role"] == "user"), ""
    )
    hits = _retrieve(last_user, req.session_id, req.top_k)
    context_block = "\n\n---\n\n".join(h["text"] for h in hits)
    sources = list({h["filename"] for h in hits})

    system_prompt = (
        "You are a helpful assistant. Use the retrieved context below to answer "
        "the user's question. If the context is not relevant, answer from general knowledge.\n\n"
        f"### Retrieved Context\n{context_block}"
        if context_block
        else "You are a helpful assistant."
    )

    # Prepend system message
    messages = [{"role": "system", "content": system_prompt}, *req.messages]

    async def stream() -> AsyncGenerator[str, None]:
        # First yield the sources metadata as a special SSE event
        yield f"event: sources\ndata: {json.dumps(sources)}\n\n"

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                OLLAMA_URL,
                json={"model": req.model, "messages": messages, "stream": True},
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        token = parsed.get("message", {}).get("content", "")
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        if parsed.get("done"):
                            yield "data: [DONE]\n\n"
                    except json.JSONDecodeError:
                        pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

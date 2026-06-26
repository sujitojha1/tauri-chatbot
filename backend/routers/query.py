"""
POST /query       — RAG retrieval (context snippets + sources)
POST /query/chat  — streaming chat. Two modes:
    * session documents → first-page markdown + page image fed straight to a
      vision model (no retrieval).
    * everything else   → RAG-augmented Ollama chat over Qdrant.
"""
import json
from typing import AsyncGenerator

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import OLLAMA_URL, OLLAMA_DEFAULT_MODEL, GLOBAL_COLLECTION
from models import db
from services.embedder import embed_texts
from services import vector_store, session_store

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None   # if set, also searches session collection
    file_id: str | None = None      # if set, filters results to this file
    top_k: int = 5


class ChatRequest(BaseModel):
    messages: list[dict]            # [{role, content}, ...]
    session_id: str | None = None
    file_id: str | None = None      # if set, filters results to this file
    model: str = OLLAMA_DEFAULT_MODEL
    top_k: int = 5


def _session_context(session_id: str) -> str:
    return session_id if session_id.startswith("session:") else f"session:{session_id}"


def _retrieve(question: str, session_id: str | None, top_k: int, file_id: str | None = None) -> list[dict]:
    """Embed question, search global + optional session collection, merge by score."""
    vector = embed_texts([question])[0]
    per_collection = max(top_k, 3)

    hits = vector_store.search(GLOBAL_COLLECTION, vector, limit=per_collection, file_id=file_id)

    if session_id:
        session_hits = vector_store.search(
            _session_context(session_id), vector, limit=per_collection, file_id=file_id
        )
        hits = sorted(hits + session_hits, key=lambda h: h["score"], reverse=True)

    return hits[:top_k]


@router.post("")
async def retrieve(req: QueryRequest):
    """Pure retrieval — returns context chunks and sources (no LLM call)."""
    hits = _retrieve(req.question, req.session_id, req.top_k, req.file_id)
    return {
        "hits": hits,
        "context": "\n\n---\n\n".join(h["text"] for h in hits),
        "sources": list({h["filename"] for h in hits}),
    }


# ── Routing helpers ───────────────────────────────────────────────────────────

async def _session_files(req: ChatRequest) -> list[dict] | None:
    """Return the session file records this request should be answered from, or
    None if it is not a session (VLM) request.

    A request targets session documents when it carries a session_id with no
    specific file, or when the targeted file_id itself lives in a session."""
    if req.file_id:
        rec = await db.get_file(req.file_id)
        if rec and rec["context"].startswith("session:"):
            return [rec]
        return None
    if req.session_id:
        return await db.get_files_by_context(_session_context(req.session_id))
    return None


def _ollama_stream(model: str, messages: list[dict], sources: list[str]) -> StreamingResponse:
    """Stream an Ollama /api/chat response as SSE in the shape the frontend expects."""
    async def stream() -> AsyncGenerator[str, None]:
        yield f"event: sources\ndata: {json.dumps(sources)}\n\n"
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", OLLAMA_URL,
                json={"model": model, "messages": messages, "stream": True},
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = parsed.get("message", {}).get("content", "")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if parsed.get("done"):
                        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
async def rag_chat(req: ChatRequest):
    """Dispatch to the vision (session) path or the RAG path."""
    session_files = await _session_files(req)
    if session_files is not None:
        return _vlm_chat(req, session_files)
    return _rag_chat(req)


# ── Vision path: session documents straight into the model context ────────────

def _vlm_chat(req: ChatRequest, files: list[dict]) -> StreamingResponse:
    md_parts: list[str] = []
    images: list[str] = []
    sources: list[str] = []

    for f in files:
        markdown, image_b64 = session_store.load(f["id"])
        sources.append(f["filename"])
        if markdown:
            md_parts.append(f"### {f['filename']}\n\n{markdown}")
        if image_b64:
            images.append(image_b64)

    context_block = "\n\n---\n\n".join(md_parts) if md_parts else "(no extracted text)"
    system_prompt = (
        "You are reviewing engineering design documents. For each uploaded "
        "document the first page is provided below as extracted markdown text, "
        "and the corresponding page image is attached to the latest user "
        "message. Base your answer strictly on these documents.\n\n"
        f"### Documents\n{context_block}"
    )

    # Attach the page images to the most recent user message so the VLM sees them.
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    convo = [dict(m) for m in req.messages]
    if images:
        for m in reversed(convo):
            if m.get("role") == "user":
                m["images"] = images
                break
    messages += convo

    return _ollama_stream(req.model, messages, sources)


# ── RAG path ──────────────────────────────────────────────────────────────────

def _rag_chat(req: ChatRequest) -> StreamingResponse:
    last_user = next(
        (m["content"] for m in reversed(req.messages) if m["role"] == "user"), ""
    )
    hits = _retrieve(last_user, req.session_id, req.top_k, req.file_id)
    context_block = "\n\n---\n\n".join(h["text"] for h in hits)
    sources = list({h["filename"] for h in hits})

    system_prompt = (
        "You are a helpful assistant. Use the retrieved context below to answer "
        "the user's question. If the context is not relevant, answer from general knowledge.\n\n"
        f"### Retrieved Context\n{context_block}"
        if context_block
        else "You are a helpful assistant."
    )
    messages = [{"role": "system", "content": system_prompt}, *req.messages]
    return _ollama_stream(req.model, messages, sources)

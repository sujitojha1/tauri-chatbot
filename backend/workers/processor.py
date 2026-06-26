"""
Async background ingestion job.

Two pipelines, chosen by upload context:

  * session:<id>  → liteparse the **first page** into markdown + a page image,
    stashed on disk for direct (non-RAG) consumption by the vision model.
  * everything else → liteparse the full document → chunk → embed → upsert to
    Qdrant for retrieval-augmented chat.

Runs via FastAPI BackgroundTasks (no Redis/Celery needed). CPU-bound parsing
and embedding run in the default thread pool to keep the event loop free
(REQ-NFR-02).
"""
import asyncio
import logging
from pathlib import Path

from config import CHUNK_SIZE, CHUNK_OVERLAP
from models import db
from services import parsing, session_store, vector_store
from services.embedder import embed_texts

logger = logging.getLogger(__name__)


async def process_file(file_id: str, path: Path, context: str, filename: str):
    await db.update_status(file_id, "processing")
    logger.info(f"[{file_id}] Starting processing: {filename} (context={context})")

    try:
        if context.startswith("session:"):
            await _process_session_file(file_id, path)
        else:
            await _process_rag_file(file_id, path, context, filename)
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        logger.exception(f"[{file_id}] Processing failed")
        await db.update_status(file_id, "failed", error=str(e))


# ── Session pipeline: first page → markdown + image for the VLM ───────────────

async def _process_session_file(file_id: str, path: Path):
    loop = asyncio.get_event_loop()
    markdown, image_b64 = await loop.run_in_executor(
        None, parsing.process_session_file, path
    )
    session_store.save(file_id, markdown, image_b64)
    logger.info(
        f"[{file_id}] Session assets ready (md={len(markdown)} chars, image={'yes' if image_b64 else 'no'})"
    )
    # No chunks/vectors for session files; mark ready so the UI can proceed.
    await db.update_status(file_id, "indexed", total_chunks=1)


# ── RAG pipeline: full document → chunks → embeddings → Qdrant ────────────────

async def _process_rag_file(file_id: str, path: Path, context: str, filename: str):
    loop = asyncio.get_event_loop()

    raw_text = await loop.run_in_executor(None, parsing.parse_markdown, path)
    logger.info(f"[{file_id}] Parsed {len(raw_text)} chars")

    chunks = _chunk_text(raw_text)
    logger.info(f"[{file_id}] Created {len(chunks)} chunks")
    await db.update_status(file_id, "chunked", total_chunks=len(chunks))

    await loop.run_in_executor(
        None, _embed_and_upsert, file_id, filename, context, chunks
    )
    await db.update_status(file_id, "indexed", total_chunks=len(chunks))
    logger.info(f"[{file_id}] Indexed successfully")


# ── Sync helpers (run in thread pool) ─────────────────────────────────────────

def _chunk_text(text: str) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [c for c in splitter.split_text(text) if c.strip()]


def _embed_and_upsert(
    file_id: str,
    filename: str,
    context: str,
    chunks: list[str],
    batch_size: int = 64,
):
    if not chunks:
        return
    all_vectors = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        all_vectors.extend(embed_texts(batch))

    vector_store.upsert_chunks(
        collection=context,
        file_id=file_id,
        filename=filename,
        chunks=chunks,
        vectors=all_vectors,
    )

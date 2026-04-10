"""
Async background job: parse → chunk → embed → upsert.
Runs via FastAPI BackgroundTasks (no Redis/Celery needed).
"""
import asyncio
import logging
from pathlib import Path

from config import CHUNK_SIZE, CHUNK_OVERLAP
from models import db
from services.embedder import embed_texts
from services import vector_store

logger = logging.getLogger(__name__)


async def process_file(file_id: str, path: Path, context: str, filename: str):
    """
    Pipeline:
      1. Parse with docling (runs in thread pool to avoid blocking event loop)
      2. Chunk with langchain RecursiveCharacterTextSplitter
      3. Embed with sentence-transformers
      4. Upsert to Qdrant
    """
    await db.update_status(file_id, "processing")
    logger.info(f"[{file_id}] Starting processing: {filename}")

    try:
        # --- Step 1: Parse (CPU-bound, run in thread pool) ---
        raw_text = await asyncio.get_event_loop().run_in_executor(
            None, _parse_document, path
        )
        logger.info(f"[{file_id}] Parsed {len(raw_text)} chars")

        # --- Step 2: Chunk ---
        chunks = _chunk_text(raw_text)
        logger.info(f"[{file_id}] Created {len(chunks)} chunks")
        await db.update_status(file_id, "chunked", total_chunks=len(chunks))

        # --- Step 3 & 4: Embed + upsert (batched, in thread pool) ---
        await asyncio.get_event_loop().run_in_executor(
            None, _embed_and_upsert, file_id, filename, context, chunks
        )

        await db.update_status(file_id, "indexed", total_chunks=len(chunks))
        logger.info(f"[{file_id}] Indexed successfully")

    except Exception as e:
        logger.exception(f"[{file_id}] Processing failed")
        await db.update_status(file_id, "failed", error=str(e))


# ── Sync helpers (run in thread pool) ─────────────────────────────────────────

def _parse_document(path: Path) -> str:
    """Use docling for structured parsing; fall back to plain text."""
    suffix = path.suffix.lower()

    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(str(path))
        return result.document.export_to_markdown()
    except Exception:
        pass

    # Plain text fallback
    return path.read_text(errors="replace")


def _chunk_text(text: str) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def _embed_and_upsert(
    file_id: str,
    filename: str,
    context: str,
    chunks: list[str],
    batch_size: int = 64,
):
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

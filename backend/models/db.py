"""
SQLite models for tracking file ingestion state.
Qdrant owns the vectors; this DB owns the metadata.
"""
import asyncio
from datetime import datetime
from typing import Optional

import aiosqlite

from config import DB_PATH


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS files (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    context     TEXT NOT NULL,       -- "global" | "session:<session_id>"
    status      TEXT NOT NULL,       -- pending | processing | chunked | indexed | failed
    total_chunks INTEGER,
    error       TEXT,
    created_at  TEXT NOT NULL
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE)
        await db.commit()


async def create_file_record(record: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO files (id, filename, size_bytes, context, status, created_at)
            VALUES (:id, :filename, :size_bytes, :context, :status, :created_at)
            """,
            {
                "id": record["id"],
                "filename": record["filename"],
                "size_bytes": record["size_bytes"],
                "context": record["context"],
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        await db.commit()


async def update_status(
    file_id: str,
    status: str,
    total_chunks: Optional[int] = None,
    error: Optional[str] = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE files
            SET status = ?, total_chunks = COALESCE(?, total_chunks), error = ?
            WHERE id = ?
            """,
            (status, total_chunks, error, file_id),
        )
        await db.commit()


async def get_file(file_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM files WHERE id = ?", (file_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_files_by_context(context: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM files WHERE context = ? ORDER BY created_at DESC", (context,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def delete_file_record(file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        await db.commit()

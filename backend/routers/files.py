"""
GET /files           — list files for a context
GET /files/{id}      — single file record
GET /files/{id}/stream — SSE stream of status updates
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models import db

router = APIRouter(prefix="/files", tags=["files"])


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _enrich(record: dict) -> dict:
    return {**record, "size_human": _fmt_bytes(record["size_bytes"])}


@router.get("")
async def list_files(context: str = "global"):
    """Return all files for a given context, newest first."""
    records = await db.get_files_by_context(context)
    return [_enrich(r) for r in records]


@router.get("/{file_id}")
async def get_file(file_id: str):
    record = await db.get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")
    return _enrich(record)


@router.get("/{file_id}/stream")
async def stream_status(file_id: str):
    """
    Server-Sent Events stream that pushes status updates until the file
    reaches a terminal state (indexed | failed).
    Frontend: new EventSource('/files/<id>/stream')
    """
    async def event_gen():
        terminal = {"indexed", "failed"}
        while True:
            record = await db.get_file(file_id)
            if not record:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break

            payload = {
                "status": record["status"],
                "total_chunks": record["total_chunks"],
                "error": record["error"],
            }
            yield f"data: {json.dumps(payload)}\n\n"

            if record["status"] in terminal:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

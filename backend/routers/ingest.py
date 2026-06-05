"""
POST /ingest/upload  — upload a file, start async processing job
DELETE /ingest/{file_id} — remove file + its vectors
"""
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from config import UPLOAD_DIR
from models import db
from workers.processor import process_file

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    context: str = Form("global"),  # "global" | "session:<session_id>"
):
    """
    Upload a document and kick off the async ingestion pipeline.
    Returns immediately with file_id and status="pending".
    """
    allowed = {".pdf", ".docx", ".txt", ".md", ".html", ".pptx", ".xlsx"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(allowed)}",
        )

    file_id = str(uuid4())
    dest_dir = UPLOAD_DIR / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename

    # Stream to disk
    size = 0
    with dest_path.open("wb") as f:
        while chunk := await file.read(1024 * 256):  # 256 KB chunks
            f.write(chunk)
            size += len(chunk)

    await db.create_file_record(
        {
            "id": file_id,
            "filename": file.filename,
            "size_bytes": size,
            "context": context,
        }
    )

    background_tasks.add_task(process_file, file_id, dest_path, context, file.filename)

    return {
        "file_id": file_id,
        "filename": file.filename,
        "size_bytes": size,
        "context": context,
        "status": "pending",
    }


@router.post("/{file_id}/reprocess")
async def reprocess_file(file_id: str, background_tasks: BackgroundTasks):
    """
    Re-run the ingestion pipeline for a file already on disk.
    Useful when processing failed or never completed. Existing vectors are
    cleared first to avoid duplicates.
    """
    record = await db.get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    dest_dir = UPLOAD_DIR / file_id
    dest_path = dest_dir / record["filename"]
    if not dest_path.exists():
        # Fall back to whatever single file is stored in the folder
        candidates = list(dest_dir.glob("*")) if dest_dir.exists() else []
        if not candidates:
            raise HTTPException(status_code=404, detail="Uploaded file missing on disk")
        dest_path = candidates[0]

    # Clear any partial vectors before re-indexing
    from services import vector_store
    vector_store.delete_file_vectors(record["context"], file_id)

    await db.update_status(file_id, "pending", error=None)
    background_tasks.add_task(
        process_file, file_id, dest_path, record["context"], record["filename"]
    )

    return {"file_id": file_id, "status": "pending"}


@router.delete("/{file_id}")
async def delete_file(file_id: str):
    """Remove file record, uploaded file, and all its vectors from Qdrant."""
    record = await db.get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    # Remove vectors
    from services import vector_store
    vector_store.delete_file_vectors(record["context"], file_id)

    # Remove uploaded file from disk
    dest_dir = UPLOAD_DIR / file_id
    if dest_dir.exists():
        shutil.rmtree(dest_dir)

    await db.delete_file_record(file_id)
    return {"deleted": file_id}

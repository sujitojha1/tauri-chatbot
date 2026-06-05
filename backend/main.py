"""
RAG Backend — FastAPI entry point.

Start:  uvicorn main:app --reload --port 8000
Docs:   http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models.db import init_db
from routers import ingest, files, query

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="RAG Backend",
    version="1.0.0",
    description="Document ingestion, chunking, embedding, and RAG-augmented chat.",
    lifespan=lifespan,
)

# Allow the Tauri webview (origin differs per platform/build) and the browser dev server.
#   - dev server:        http://localhost:1420 / :5173
#   - macOS/Linux build: tauri://localhost
#   - Windows (WebView2) build: http://tauri.localhost / https://tauri.localhost
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?|tauri://localhost)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(files.router)
app.include_router(query.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

# AI-Based PD Checker

A local-first desktop chatbot with RAG (Retrieval-Augmented Generation) built on Tauri, Vue 3, and a Python FastAPI backend. All AI inference and document processing runs entirely on your machine — no cloud, no telemetry.

## Features

- **Local AI chat** — streams responses from any model running in [Ollama](https://ollama.com/) (default: `gemma4:e2b`)
- **RAG document chat** — ingest PDFs, DOCX, PPTX, XLSX, HTML, and plain text files; ask questions grounded in their content
- **Two-tier knowledge base** — upload files to the persistent *Global* store or to a temporary *Session* (discarded on restart)
- **Document pipeline** — parse → chunk → embed → upsert into Qdrant, with live status updates in the sidebar
- **Embeddings via Ollama** — uses `nomic-embed-text` (768-dim, no separate model download beyond `ollama pull nomic-embed-text`)
- **Markdown rendering** — full prose rendering of assistant replies including code blocks and lists
- **Privacy first** — everything stays on `localhost`; no data leaves the machine

## Architecture

```
┌─────────────────────────────────────────┐
│  Tauri Desktop App (Rust shell)         │
│  ┌───────────────────────────────────┐  │
│  │  Vue 3 + Vite frontend            │  │
│  │  - Chat UI / sidebar              │  │
│  │  - Streams from Ollama directly   │  │
│  │  - Calls RAG backend for queries  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
         │ HTTP (localhost:8000)
┌────────▼────────────────────────────────┐
│  FastAPI RAG Backend (Python 3.11)      │
│  - /ingest   → parse, chunk, embed      │
│  - /files    → list, delete, SSE status │
│  - /query/chat → retrieve + LLM stream  │
│  - SQLite (rag.db) for file metadata    │
└────────┬────────────────────────────────┘
         │
┌────────▼──────────┐   ┌─────────────────┐
│  Qdrant (Docker)  │   │  Ollama          │
│  localhost:6333   │   │  localhost:11434  │
│  Vector store     │   │  LLM + embeddings│
└───────────────────┘   └─────────────────┘
```

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| [Rust](https://www.rust-lang.org/tools/install) | stable | Required by Tauri |
| [Node.js](https://nodejs.org/) | 18+ | Frontend build |
| [Python](https://python.org/) | 3.11+ | RAG backend |
| [Docker](https://www.docker.com/) | any | Runs Qdrant |
| [Ollama](https://ollama.com/) | any | LLM + embeddings |

Pull the required Ollama models once:

```bash
ollama pull gemma4:e2b          # or any chat model
ollama pull nomic-embed-text    # embeddings (required for RAG)
```

## Getting Started

### 1. Start the RAG backend

```bash
cd backend
./start.sh
```

This will:
- Create a Python venv and install dependencies
- Start Qdrant in Docker (`qdrant/qdrant` on port 6333)
- Start the FastAPI server on `http://localhost:8000`

API docs are available at `http://localhost:8000/docs`.

### 2. Start the desktop app

In a separate terminal from the project root:

```bash
npm install
npm run tauri dev
```

### Building for production

```bash
npm run tauri build
```

The packaged app (`.dmg` / `.app` on macOS) will be in `src-tauri/target/release/bundle/`.

## Using the App

**Without RAG backend:** The chat connects directly to Ollama and works as a standard local AI assistant.

**With RAG backend running:**

1. Open the sidebar and use the **Add** button in the **Global** section to ingest documents that persist across sessions, or the **Add** button in the **Session** section for temporary files.
2. Files are parsed, chunked, and embedded automatically. A status indicator shows progress (`parsing → chunking → indexed`).
3. Once at least one file is indexed, the **RAG** pill appears in the header — all queries are now grounded in your documents.

## Project Structure

```
├── src/                    # Vue 3 frontend
│   ├── App.vue             # Main UI component
│   ├── ollama.ts           # Direct Ollama chat streaming
│   ├── rag.ts              # RAG backend API client
│   └── styles.css          # Tailwind + theme config
├── src-tauri/              # Tauri / Rust shell
├── backend/                # Python FastAPI RAG backend
│   ├── main.py             # App entry point
│   ├── config.py           # Ports, model names, chunk sizes
│   ├── routers/
│   │   ├── ingest.py       # File upload endpoint
│   │   ├── files.py        # File list / delete / SSE status
│   │   └── query.py        # RAG chat endpoint
│   ├── services/
│   │   ├── vector_store.py # Qdrant wrapper
│   │   └── embedder.py     # Ollama embedding calls
│   ├── workers/
│   │   └── processor.py    # Parse → chunk → embed pipeline
│   ├── requirements.txt
│   └── start.sh            # One-command startup script
```

## Configuration

Edit [backend/config.py](backend/config.py) to change defaults:

| Setting | Default | Description |
|---|---|---|
| `EMBEDDING_MODEL` | `nomic-embed-text:latest` | Ollama embedding model |
| `EMBEDDING_DIM` | `768` | Must match the model's output dimension |
| `OLLAMA_DEFAULT_MODEL` | `gemma4:e2b` | Default chat model |
| `CHUNK_SIZE` | `512` | Tokens per chunk |
| `CHUNK_OVERLAP` | `64` | Overlap between consecutive chunks |
| `QDRANT_PORT` | `6333` | Qdrant HTTP port |

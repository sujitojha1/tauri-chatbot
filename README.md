# AI-Based PD Checker

A local-first engineering desktop application for auditing Product Design (PD) specifications, built on **Tauri**, **Vue 3**, and a **Python FastAPI RAG (Retrieval-Augmented Generation)** backend. All AI inference, document parsing, and database transactions run entirely locally on your machine.

---

## 🚀 Key Features (change)

* **Specs Workspace (File-Scoped RAG Chat)**: Upload global engineering specifications and chat directly with any chosen file. Search queries and context snippets are strictly filtered to the active file bounds.
* **Session Workspace (Compliance Review Dashboard)**:
  * Upload session-specific documents (drawings, parameter list drafts).
  * Run a structured **PD Evaluation Review** with a single click.
  * Generates compliance status tables mapping parameters, requirements, and compliance flags.
  * Unlocks interactive follow-up chat immediately after evaluation is complete.
* **Multi-Session Lifecycle**: Create, switch, and delete review contexts. Chat histories, review states, active selections, and session-specific files are cached and persisted locally.
* **Robust Local Ingestion Pipeline**:
  * Seamless fallback: Ingests documents using Docker Qdrant, or falls back to an embedded local disk client if Docker is offline.
  * Multi-format support: Parses PDFs (using structured layout conversions), DOCX, PPTX, XLSX, HTML, and text.
  * Clean Database namespaces: Automatically sanitizes collection namespaces to meet strict database schemas.
* **Privacy First & Open-Source**: Zero cloud trackers, telemetry, or API tokens required. Everything stays on `localhost`.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────┐
│  Tauri Desktop Application (Rust Shell)  │
│  ┌────────────────────────────────────┐  │
│  │  Vue 3 + Vite Frontend (UI View)    │  │
│  │  - Specs & Sessions Workspaces     │  │
│  │  - Local Storage Session Caching    │  │
│  │  - Streams directly from Ollama     │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
          │ HTTP (localhost:8000)
┌─────────▼────────────────────────────────┐
│  FastAPI RAG Backend (Python 3.11)       │
│  - /ingest     → Parse, chunk, embed     │
│  - /files      → SSE Status & management │
│  - /query/chat → File-scoped retrieve    │
│  - SQLite (rag.db) metadata catalog      │
└─────────┬────────────────────────────────┘
          │
┌─────────▼───────────┐   ┌──────────────────┐
│  Qdrant Database    │   │  Ollama Engine   │
│  (Docker / SQLite)  │   │  (Local Models)  │
│  Vector storage     │   │  LLM + Embeddings│
└─────────────────────┘   └──────────────────┘
```

---

## 🛠️ Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| **Rust** | Stable | Compiles the Tauri Rust host wrapper |
| **Bun** (or Node) | 1.1+ | Package manager and vite build runner |
| **Python** | 3.11+ | Powering the RAG FastAPI backend service |
| **Ollama** | Latest | Running local LLM and embedding models |
| **Docker** | Optional | Runs the Qdrant container (local fallback mode runs on SQLite if offline) |

Before starting, pull the local models in Ollama:
```bash
ollama pull gemma4:e2b          # Default LLM
ollama pull nomic-embed-text    # Embeddings model (required for RAG)
```

---

## 🏁 Getting Started

### 1. Start the RAG Backend

Navigate into the `backend` folder and start the automated server wrapper:

**On Windows (PowerShell)**:
```powershell
cd backend
.\start.ps1
```

**On Linux/macOS (Shell)**:
```bash
cd backend
chmod +x start.sh
./start.sh
```

This installs Python dependencies inside a local `.venv` environment, configures metadata databases, launches local/remote vector engines, and binds FastAPI to `http://localhost:8000`.

### 2. Start the Desktop client

In a separate terminal at the project root directory:

```bash
# Install frontend node modules
bun install

# Run the Tauri application dev client
bun run tauri dev
```

---

## 📂 Configuration

Customize models, chunk overlaps, and index ports inside [backend/config.py](backend/config.py):

* `EMBEDDING_MODEL`: The Ollama model name used to encode document chunks (default: `nomic-embed-text:latest`).
* `CHUNK_SIZE`: Token length constraint per text segment (default: `512`).
* `OLLAMA_DEFAULT_MODEL`: The LLM model utilized in direct and retrieval-augmented streams (default: `gemma4:e2b`).

from pathlib import Path

# Directories
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
# Derived artifacts produced for session files (first-page markdown + screenshot).
ASSET_DIR = BASE_DIR / "assets"
DB_PATH = BASE_DIR / "rag.db"

UPLOAD_DIR.mkdir(exist_ok=True)
ASSET_DIR.mkdir(exist_ok=True)

# Qdrant
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
GLOBAL_COLLECTION = "global"
# Embedded on-disk fallback when no Qdrant server is reachable (REQ-NFR-03).
QDRANT_LOCAL_PATH = BASE_DIR / "qdrant_data"

# Embeddings — served by Ollama (no separate model download needed)
EMBEDDING_MODEL = "nomic-embed-text:latest"
EMBEDDING_DIM = 768          # nomic-embed-text output dimension
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

# Chunking
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# Ollama (for RAG-augmented generation)
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embeddings"
OLLAMA_DEFAULT_MODEL = "gemma4:e2b"
# Vision-capable model used for the direct (non-RAG) session document review.
VLM_DEFAULT_MODEL = "gemma4:12b"

# Session document processing — for simplicity we only process the first page
# of each session file and feed its markdown + page image straight to the VLM.
SESSION_MAX_PAGES = 1

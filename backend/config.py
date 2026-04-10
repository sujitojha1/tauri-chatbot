from pathlib import Path

# Directories
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "rag.db"

UPLOAD_DIR.mkdir(exist_ok=True)

# Qdrant
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
GLOBAL_COLLECTION = "global"

# Embeddings — served by Ollama (no separate model download needed)
EMBEDDING_MODEL = "nomic-embed-text:latest"
EMBEDDING_DIM = 768          # nomic-embed-text output dimension
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

# Chunking
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# Ollama (for RAG-augmented generation)
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_DEFAULT_MODEL = "gemma4:e2b"

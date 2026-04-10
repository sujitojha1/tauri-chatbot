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

# Embeddings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # fast, 384-dim, runs locally
EMBEDDING_DIM = 384

# Chunking
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# Ollama (for RAG-augmented generation)
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_DEFAULT_MODEL = "gemma4:e2b"

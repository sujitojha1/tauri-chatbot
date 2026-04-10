#!/usr/bin/env bash
# Start the RAG backend (assumes Qdrant is already running via Docker)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo ""
echo "Starting Qdrant (Docker)..."
if ! docker ps --format '{{.Names}}' | grep -q '^qdrant$'; then
  docker run -d --name qdrant -p 6333:6333 -v "$(pwd)/qdrant_data:/qdrant/storage" qdrant/qdrant
  echo "Qdrant started."
else
  echo "Qdrant already running."
fi

echo ""
echo "Starting RAG backend on http://localhost:8000"
echo "Docs: http://localhost:8000/docs"
echo ""
uvicorn main:app --reload --host 0.0.0.0 --port 8000

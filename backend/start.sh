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
echo "Checking Docker..."
if docker info >/dev/null 2>&1; then
  echo "Docker is running. Starting Qdrant (Docker)..."
  if ! docker ps --format '{{.Names}}' | grep -q '^qdrant$'; then
    docker run -d --name qdrant -p 6333:6333 -v "$(pwd)/qdrant_data:/qdrant/storage" qdrant/qdrant
    echo "Qdrant started."
  else
    echo "Qdrant already running."
  fi
else
  echo "Docker daemon is offline or not installed."
  echo "RAG backend will run using local fallback mode (no Docker required!)."
fi

echo ""
echo "Starting RAG backend on http://localhost:8000"
echo "Docs: http://localhost:8000/docs"
echo ""
uvicorn main:app --reload --host 0.0.0.0 --port 8000

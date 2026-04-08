import os
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from lightrag import LightRAG, QueryParam
from lightrag.llm import ollama_model_complete, ollama_embedding

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKING_DIR = "./rag_storage"
if not os.path.exists(WORKING_DIR):
    os.mkdir(WORKING_DIR)

# Global variables to retain RAG instance
_rag_instances = {}

def get_rag(model_name: str) -> LightRAG:
    if model_name in _rag_instances:
        return _rag_instances[model_name]
    
    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=ollama_model_complete,
        llm_model_name=model_name,
        llm_model_max_async=2,
        llm_model_max_token_size=32768,
        embedding_func=ollama_embedding,
        embedding_model="nomic-embed-text:latest"
    )
    _rag_instances[model_name] = rag
    return rag

@app.post("/ingest")
async def ingest_file(model: str = Form(...), file: UploadFile = File(...)):
    try:
        content = await file.read()
        text = content.decode("utf-8")
        rag = get_rag(model)
        rag.insert(text)
        return {"status": "success", "message": f"Successfully ingested {file.filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ChatRequest(BaseModel):
    query: str
    model: str

@app.post("/chat")
async def chat_rag(request: ChatRequest):
    try:
        rag = get_rag(request.model)
        # Using native, naive or local mode. "naive" is standard vector search, "local" uses graph structures.
        answer = rag.query(request.query, param=QueryParam(mode="naive"))
        return {"response": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

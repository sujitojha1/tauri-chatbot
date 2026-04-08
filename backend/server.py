import os
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from lightrag import LightRAG, QueryParam
from lightrag.llm.ollama import ollama_model_complete, ollama_embed
from raganything import RAGAnything, RAGAnythingConfig
import shutil

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

def get_rag(model_name: str):
    if model_name in _rag_instances:
        return _rag_instances[model_name]
    
    lightrag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=ollama_model_complete,
        llm_model_name=model_name,
        llm_model_max_async=2,
        llm_model_max_token_size=32768,
        embedding_func=ollama_embed,
        embedding_model="nomic-embed-text:latest"
    )
    
    config = RAGAnythingConfig(
        working_dir=WORKING_DIR,
        parser="mineru",
        parse_method="auto"
    )
    
    rag = RAGAnything(
        config=config,
        lightrag=lightrag
    )
    _rag_instances[model_name] = rag
    return rag

@app.post("/ingest")
async def ingest_file(model: str = Form(...), file: UploadFile = File(...)):
    try:
        rag = get_rag(model)
        
        # Save file to disk temporarily for RAGAnything MinerU processing
        temp_dir = os.path.join(WORKING_DIR, "temp_uploads")
        if not os.path.exists(temp_dir):
            os.mkdir(temp_dir)
            
        temp_path = os.path.join(temp_dir, file.filename)
        with open(temp_path, "wb") as f:
            f.write(await file.read())
            
        # Let RAGAnything fully process the document natively using MinerU / extraction
        await rag.process_document_complete(
            file_path=temp_path,
            output_dir=os.path.join(WORKING_DIR, "output"),
            parse_method="auto"
        )
        
        # Cleanup
        os.remove(temp_path)
        
        return {"status": "success", "message": f"Successfully ingested {file.filename} using RAGAnything"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ChatRequest(BaseModel):
    query: str
    model: str

@app.post("/chat")
async def chat_rag(request: ChatRequest):
    try:
        rag = get_rag(request.model)
        # Using RAGAnything's asynchronous multimodal query pipeline
        answer = await rag.aquery(request.query, mode="hybrid")
        return {"response": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

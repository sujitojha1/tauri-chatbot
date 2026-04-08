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

from lightrag.utils import EmbeddingFunc
import ollama

async def my_vision_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    if history_messages is None:
        history_messages = []
    
    image_data = kwargs.pop("image_data", None)
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(history_messages)
    
    user_msg = {"role": "user", "content": prompt}
    if image_data:
        user_msg["images"] = [image_data]
    messages.append(user_msg)
    
    client = ollama.AsyncClient()
    response = await client.chat(model="llama3.2-vision", messages=messages)
    return response["message"]["content"]

def get_rag(model_name: str):
    if model_name in _rag_instances:
        return _rag_instances[model_name]
    
    lightrag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=ollama_model_complete,
        llm_model_name=model_name,
        llm_model_max_async=2,
        embedding_func=EmbeddingFunc(
            embedding_dim=768,
            max_token_size=8192,
            func=lambda texts: ollama_embed.func(texts, embed_model="nomic-embed-text")
        )
    )
    
    config = RAGAnythingConfig(
        working_dir=WORKING_DIR,
        parser="docling",
        parse_method="auto"
    )
    
    rag = RAGAnything(
        config=config,
        lightrag=lightrag,
        vision_model_func=my_vision_func
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
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return {"status": "success", "message": f"Successfully ingested {file.filename} using RAGAnything"}
    except Exception as e:
        import traceback
        traceback.print_exc()
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

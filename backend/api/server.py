from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal
import json
import os
from pathlib import Path

# Import new pipeline components
from backend.pipeline.orchestrator import PipelineOrchestrator
from backend.pipeline.layers.query_layer import QueryLayer
from backend.pipeline.layers.channel_layer import ChannelLayer
from backend.pipeline.layers.video_layer import VideoLayer
from backend.pipeline.layers.content_layer import ContentLayer
from backend.pipeline.layers.context_layer import ContextLayer
from backend.pipeline.layers.generation_layer import GenerationLayer

from backend.ingestion.manager import IngestionManager
from backend.storage.vector_store import VectorStore
from backend.storage.video_store import VideoStore
from backend.storage.transcript_store import TranscriptStore
from backend.agent.llm_client import LLMClient
from backend.ingestion.youtube_client import YouTubeClient
from backend.data_models.models import Channel
from backend.utils.logger import log, get_logs, LogMessage
from dotenv import load_dotenv

# Load environment variables
BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = BACKEND_DIR.parent
ENV_PATH = BACKEND_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")

if not YOUTUBE_API_KEY or not GROK_API_KEY:
    log(f"Error: Please set YOUTUBE_API_KEY and GROK_API_KEY in .env file at {ENV_PATH}", "ERROR")
    pass 

# Initialize components
log("Initializing components...")
try:
    if not YOUTUBE_API_KEY or not GROK_API_KEY:
         raise ValueError("Missing API Keys")
         
    vector_store = VectorStore()
    video_store = VideoStore()
    transcript_store = TranscriptStore()
    youtube_client = YouTubeClient(api_key=YOUTUBE_API_KEY)
    llm_client = LLMClient(api_key=GROK_API_KEY)

    ingestion_manager = IngestionManager(youtube_client, vector_store, video_store, transcript_store)

    # Migrate legacy Chroma-only transcripts once. Future ingestions write to
    # SQLite and Chroma together.
    if transcript_store.count_chunks() == 0 and vector_store.chunks_collection.count() > 0:
        migrated = transcript_store.import_chunks(vector_store.get_all_chunks())
        log(f"Migrated {migrated} legacy transcript chunks into SQLite.")
    
    # Initialize Pipeline Layers
    query_layer = QueryLayer(llm_client)
    channel_layer = ChannelLayer(llm_client)
    video_layer = VideoLayer(video_store, vector_store, llm_client) # Pass LLMClient to VideoLayer
    content_layer = ContentLayer(ingestion_manager, vector_store, video_store, transcript_store)
    context_layer = ContextLayer(video_store, channels_file=str(BASE_DIR / "channels.json"))
    generation_layer = GenerationLayer(llm_client)
    
    # Initialize Pipeline Orchestrator
    pipeline_orchestrator = PipelineOrchestrator(
        query_layer, channel_layer, video_layer, content_layer, context_layer, generation_layer
    )
    
    log("Components initialized successfully.")
except Exception as e:
    log(f"Failed to initialize components: {e}", "ERROR")
    pipeline_orchestrator = None
    ingestion_manager = None

app = FastAPI()

# Simple JSON-based storage for channels
CHANNELS_FILE = "channels.json"

def load_channels() -> List[Channel]:
    if not os.path.exists(CHANNELS_FILE):
        return []
    try:
        with open(CHANNELS_FILE, "r") as f:
            data = json.load(f)
            return [Channel(**item) for item in data]
    except Exception as e:
        log(f"Error loading channels: {e}", "ERROR")
        return []

def save_channel(channel: Channel):
    channels = load_channels()
    # Check if exists
    if any(c.id == channel.id for c in channels):
        return # Already exists
    
    channels.append(channel)
    with open(CHANNELS_FILE, "w") as f:
        # Convert datetime to string for JSON serialization
        json.dump([c.dict() for c in channels], f, default=str, indent=2)

def delete_channel_from_file(channel_id: str):
    channels = load_channels()
    channels = [c for c in channels if c.id != channel_id]
    with open(CHANNELS_FILE, "w") as f:
        json.dump([c.dict() for c in channels], f, default=str, indent=2)

class ChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class QuestionRequest(BaseModel):
    question: str
    history: List[ChatMessageRequest] = Field(default_factory=list)

class ChannelRequest(BaseModel):
    channel_id: str

@app.post("/ask")
async def ask_question(request: QuestionRequest):
    if not pipeline_orchestrator:
        raise HTTPException(status_code=500, detail="Server not initialized properly. Check logs.")
        
    log(f"Received question: {request.question}")
    try:
        # Use the new pipeline
        answer = pipeline_orchestrator.run(
            request.question,
            [message.model_dump() for message in request.history],
        )
        log(f"Generated answer: {answer[:50]}...")
        return {"answer": answer}
    except Exception as e:
        log(f"Error processing question: {str(e)}", "ERROR")
        raise HTTPException(status_code=500, detail=f"Error processing question: {str(e)}")

@app.post("/channels")
async def add_channel(request: ChannelRequest):
    if not ingestion_manager:
        raise HTTPException(status_code=500, detail="Server not initialized properly. Check logs.")

    log(f"Received request to add channel: {request.channel_id}")
    try:
        # Validate channel ID format (basic check)
        if not request.channel_id.startswith("UC"):
             log(f"Invalid Channel ID format: {request.channel_id}", "WARNING")
             raise HTTPException(status_code=400, detail="Invalid Channel ID format. Must start with 'UC'.")

        # Process channel and get details
        channel = ingestion_manager.process_channel(request.channel_id)
        
        # Save to local storage
        save_channel(channel)
        
        log(f"Channel {channel.name} added successfully.")
        return channel
    except ValueError as e:
        log(f"Channel not found: {str(e)}", "WARNING")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log(f"Error adding channel: {str(e)}", "ERROR")
        raise HTTPException(status_code=500, detail=f"Error adding channel: {str(e)}")

@app.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str):
    if not ingestion_manager:
        raise HTTPException(status_code=500, detail="Server not initialized properly. Check logs.")

    log(f"Received request to delete channel: {channel_id}")
    try:
        # Delete from ingestion manager (DBs)
        ingestion_manager.delete_channel(channel_id)
        
        # Delete from local JSON file
        delete_channel_from_file(channel_id)
        
        log(f"Channel {channel_id} deleted successfully.")
        return {"message": f"Channel {channel_id} deleted successfully."}
    except Exception as e:
        log(f"Error deleting channel: {str(e)}", "ERROR")
        raise HTTPException(status_code=500, detail=f"Error deleting channel: {str(e)}")

@app.get("/channels")
async def get_channels():
    return load_channels()

@app.get("/logs")
async def get_server_logs() -> List[LogMessage]:
    return get_logs()

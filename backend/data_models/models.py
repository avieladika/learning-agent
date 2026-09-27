from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class Channel(BaseModel):
    id: str
    name: str
    last_scanned: Optional[datetime] = None

class Video(BaseModel):
    id: str
    channel_id: str
    title: str
    url: str
    published_at: datetime
    transcript_downloaded: bool = False

class TranscriptChunk(BaseModel):
    video_id: str
    text: str
    start_time: float
    end_time: float
    chunk_index: Optional[int] = None
    embedding: Optional[List[float]] = None

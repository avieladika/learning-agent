from typing import List, Optional
from backend.ingestion.youtube_client import YouTubeClient
from backend.storage.vector_store import VectorStore
from backend.storage.video_store import VideoStore
from backend.storage.transcript_store import TranscriptStore
from backend.ingestion.text_processor import TextProcessor
from backend.data_models.models import Channel, Video
from backend.utils.logger import log

class IngestionManager:
    def __init__(self, youtube_client: YouTubeClient, vector_store: VectorStore, video_store: VideoStore, transcript_store: TranscriptStore):
        self.youtube_client = youtube_client
        self.vector_store = vector_store
        self.video_store = video_store
        self.transcript_store = transcript_store
        self.text_processor = TextProcessor()

    def process_channel(self, channel_id: str) -> Channel:
        """
        Main flow for ingesting a channel:
        1. Validate channel
        2. Fetch ALL videos metadata
        3. Save metadata to VideoStore
        4. Index video titles for semantic search
        5. Return channel details
        """
        log(f"Processing channel: {channel_id}")
        
        # 1. Validate channel
        if not self.youtube_client.validate_channel(channel_id):
            log(f"Channel with ID {channel_id} not found or invalid.", "WARNING")
            raise ValueError(f"Channel with ID {channel_id} not found or invalid.")
        
        # 2. Fetch videos metadata
        log("Fetching all videos metadata...")
        videos = self.youtube_client.get_all_videos_metadata(channel_id)
        
        if not videos:
            log(f"No videos found for channel {channel_id}", "WARNING")
        else:
            # 3. Save to VideoStore (SQLite)
            self.video_store.add_videos(videos)
            log(f"Saved {len(videos)} videos metadata to VideoStore.")
            
            # 4. Index titles for semantic search (VectorStore)
            self.vector_store.add_video_titles(videos)
            log(f"Indexed {len(videos)} video titles for semantic search.")
        
        # 5. Fetch and return channel details
        channel = self.youtube_client.get_channel_details(channel_id)
        if not channel:
             channel = Channel(id=channel_id, name="Unknown Channel")
             
        return channel

    def ingest_video_transcript(self, video_id: str):
        """
        Downloads and ingests transcript for a specific video.
        """
        log(f"Ingesting transcript for video: {video_id}")
        self.video_store.mark_ingestion_started(video_id)
        
        # Fetch transcript
        raw_chunks = self.youtube_client.get_transcript(video_id)
        
        if raw_chunks:
            # Process transcript (merge small chunks)
            processed_chunks = self.text_processor.process_transcript(raw_chunks)

            # SQLite is the canonical transcript store; Chroma is the semantic index.
            self.transcript_store.replace_video_chunks(video_id, processed_chunks)
            self.vector_store.save_chunks(processed_chunks)
            
            # Mark as downloaded in VideoStore
            self.video_store.mark_transcript_downloaded(video_id)
            
            log(f"Saved {len(processed_chunks)} chunks for video {video_id}")
        else:
            self.video_store.mark_ingestion_failed(video_id, "No transcript available", no_transcript=True)
            log(f"No transcript found for video {video_id}", "WARNING")

    def delete_channel(self, channel_id: str):
        """
        Deletes all data associated with a channel.
        """
        log(f"Deleting channel: {channel_id}")
        
        # 1. Get all video IDs for this channel from VideoStore
        videos = self.video_store.get_videos_by_channel(channel_id)
        video_ids = [v.id for v in videos]
        
        if not video_ids:
            log(f"No videos found for channel {channel_id} to delete.", "WARNING")
            return

        # 2. Delete from VectorStore (titles and chunks)
        self.vector_store.delete_channel_data(video_ids)
        
        # 3. Delete from VideoStore
        self.video_store.delete_channel_videos(channel_id)
        
        log(f"Channel {channel_id} deleted successfully.")

from typing import List
from backend.agent.llm_client import LLMClient
from backend.storage.vector_store import VectorStore
from backend.storage.video_store import VideoStore
from backend.ingestion.manager import IngestionManager
from backend.data_models.models import TranscriptChunk
from backend.utils.logger import log
import time
import random
import re

class AgentOrchestrator:
    def __init__(self, llm_client: LLMClient, vector_store: VectorStore, video_store: VideoStore, ingestion_manager: IngestionManager):
        self.llm_client = llm_client
        self.vector_store = vector_store
        self.video_store = video_store
        self.ingestion_manager = ingestion_manager

    def ask(self, question: str) -> str:
        """
        Main flow for answering a question:
        1. Check for direct URL
        2. Keyword search (if no URL)
        3. Semantic search (fallback)
        4. Deep scan (iterate and ingest)
        5. Generate answer
        """
        log(f"User asked: {question}")
        
        relevant_video_ids = []
        
        # 1. Check for direct URL
        url_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", question)
        if url_match:
            video_id = url_match.group(1)
            log(f"Detected video URL/ID: {video_id}")
            
            # Verify we track this video
            video = self.video_store.get_video(video_id)
            if video:
                relevant_video_ids = [video_id]
                log("Video found in database.")
            else:
                log("Video not found in database. Ignoring URL.", "WARNING")
        
        # 2. Keyword Search (if no URL found)
        if not relevant_video_ids:
            keywords = self._extract_keywords(question)
            if keywords:
                log(f"Searching for keywords: {keywords}")
                keyword_videos = self.video_store.search_by_keywords(keywords, limit=20)
                if keyword_videos:
                    relevant_video_ids = [v.id for v in keyword_videos]
                    log(f"Found {len(relevant_video_ids)} videos via keyword search.")
        
        # 3. Semantic Search (Fallback)
        if not relevant_video_ids:
            log("Searching for relevant videos (Semantic Search)...")
            relevant_video_ids = self.vector_store.search_video_titles(question, top_k=100)
            log(f"Found {len(relevant_video_ids)} videos via semantic search.")
            
        if not relevant_video_ids:
             return "I couldn't find any relevant videos in the database."
            
        log(f"Starting deep scan on {len(relevant_video_ids)} videos...")
        
        # 4. Deep Scan Logic
        batch_size = 5
        collected_chunks = []
        max_chunks_needed = 10 
        
        for i in range(0, len(relevant_video_ids), batch_size):
            batch_ids = relevant_video_ids[i:i+batch_size]
            log(f"Scanning batch {i//batch_size + 1}: {len(batch_ids)} videos...")
            
            for video_id in batch_ids:
                video = self.video_store.get_video(video_id)
                if not video: continue
                    
                if not video.transcript_downloaded:
                    log(f"Downloading transcript for video: {video.title}")
                    self.ingestion_manager.ingest_video_transcript(video.id)
                    delay = random.uniform(2.0, 5.0)
                    time.sleep(delay)
            
            batch_chunks = self.vector_store.search_in_videos(
                question, 
                video_ids=batch_ids, 
                top_k=10, 
                threshold=1.0 
            )
            
            if batch_chunks:
                log(f"Found {len(batch_chunks)} relevant chunks in this batch.")
                collected_chunks.extend(batch_chunks)
            else:
                log("No relevant chunks found in this batch.")
                
            if len(collected_chunks) >= max_chunks_needed:
                log(f"Collected enough chunks ({len(collected_chunks)}). Stopping scan.")
                break
        
        if not collected_chunks:
            log("Scanned all relevant videos but found no relevant information.", "WARNING")
            return "I couldn't find any relevant information in the videos I scanned."
            
        log(f"Generating answer based on {len(collected_chunks)} chunks...")
        
        # 5. Generate answer
        answer = self.llm_client.generate_answer(question, collected_chunks)
        
        if "i don't know" in answer.lower() or "couldn't find" in answer.lower():
            debug_info = "\n\n--- Debug: Context sent to LLM ---\n"
            for chunk in collected_chunks:
                debug_info += f"- Video {chunk.video_id} (Time: {chunk.start_time:.2f}s): {chunk.text}\n"
            return answer + debug_info
            
        return answer

    def _extract_keywords(self, text: str) -> List[str]:
        """
        Extracts important keywords from the question, removing stop words.
        """
        stop_words = {
            "what", "is", "are", "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", 
            "how", "do", "does", "did", "can", "could", "should", "would", "why", "when", "where",
            "video", "videos", "show", "me", "tell", "about", "explain", "describe"
        }
        
        # Simple tokenization
        words = re.findall(r'\b\w+\b', text.lower())
        
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return keywords

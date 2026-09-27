from .base_layer import BaseLayer
from typing import List
from backend.storage.video_store import VideoStore
from backend.storage.vector_store import VectorStore
from backend.utils.logger import log
from backend.agent.llm_client import LLMClient
import json

class VideoLayer(BaseLayer):
    """
    Layer 2: Selects relevant videos from the selected channels.
    Uses Hybrid Search (URL -> Keyword + Semantic) + LLM Re-ranking.
    """
    
    def __init__(self, video_store: VideoStore, vector_store: VectorStore, llm_client: LLMClient = None):
        self.video_store = video_store
        self.vector_store = vector_store
        self.llm_client = llm_client

    def execute(self, query_data: dict, channel_ids: List[str]) -> List[str]:
        """
        Finds relevant video IDs.
        
        Args:
            query_data: Output from QueryLayer.
            channel_ids: Output from ChannelLayer.
            
        Returns:
            List[str]: A list of relevant video IDs (up to 100).
        """
        video_id = query_data.get("video_id")
        keywords = query_data.get("keywords")
        question = query_data.get("translated_question") or query_data.get("original_question")
        
        # 1. Direct URL
        if video_id:
            video = self.video_store.get_video(video_id)
            if video:
                log(f"VideoLayer: Found direct video match {video_id}")
                return [video_id]
            return []
        
        candidate_video_ids = set()
        
        # 2. Keyword Search across all selected channels
        if keywords:
            log(f"VideoLayer: Searching keywords: {keywords}")
            # This search is across all videos, so we filter by channel_ids
            keyword_videos = self.video_store.search_by_keywords(keywords, limit=50)
            for v in keyword_videos:
                if v.channel_id in channel_ids:
                    candidate_video_ids.add(v.id)
            log(f"VideoLayer: Found {len(candidate_video_ids)} videos via keywords.")

        # 3. Semantic Search (Vector) across all titles
        log("VideoLayer: Performing semantic search...")
        # This search is also across all titles, so we filter
        semantic_ids = self.vector_store.search_video_titles(question, top_k=50)
        
        for vid in semantic_ids:
            video = self.video_store.get_video(vid)
            if video and video.channel_id in channel_ids:
                candidate_video_ids.add(vid)
                
        log(f"VideoLayer: Total candidates before ranking: {len(candidate_video_ids)}")
        
        if not candidate_video_ids:
            return []
            
        # Convert IDs to Video objects for ranking
        candidate_videos = []
        for vid in candidate_video_ids:
            v = self.video_store.get_video(vid)
            if v:
                candidate_videos.append(v)
                
        # 4. LLM Re-ranking
        if self.llm_client and len(candidate_videos) > 0:
            log("VideoLayer: Re-ranking candidates with LLM...")
            try:
                ranking_json = self.llm_client.rank_videos(query_data, candidate_videos)
                ranking_data = json.loads(ranking_json)
                ranked_list = ranking_data.get("ranked_videos", [])
                
                # Sort by score descending
                ranked_list.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
                
                # Take top 10-20
                top_videos = ranked_list[:20]
                
                log("VideoLayer: Top ranked videos:")
                for item in top_videos:
                    log(f"  [{item.get('relevance_score')}] {item.get('title')}")
                    
                return [item.get("id") for item in top_videos]
                
            except Exception as e:
                log(f"VideoLayer: Error during re-ranking: {e}", "ERROR")
                # Fallback: return all candidates
                return list(candidate_video_ids)
        
        return list(candidate_video_ids)

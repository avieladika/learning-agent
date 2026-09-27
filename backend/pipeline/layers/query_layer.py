from .base_layer import BaseLayer
from typing import Dict, Any, List
import re
import json
from backend.agent.llm_client import LLMClient
from backend.utils.logger import log

class QueryLayer(BaseLayer):
    """
    Layer 0: Understands and processes the user's query using an LLM.
    """
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def execute(self, question: str) -> Dict[str, Any]:
        """
        Analyzes the user's question using an LLM.
        
        Args:
            question (str): The raw user question.
            
        Returns:
            A dictionary containing the analyzed query components.
        """
        # First, check for a URL locally to avoid unnecessary LLM calls
        video_id = self._extract_video_id(question)
        
        # If it's just a URL, we don't need deep analysis
        if video_id and len(question.strip().split()) < 5:
             return {
                "original_question": question,
                "translated_question": question,
                "intent": "direct_url",
                "keywords": [],
                "entities": [],
                "search_queries": [question],
                "video_id": video_id
            }

        # Use LLM for deep analysis
        analysis_prompt = self._build_analysis_prompt(question)
        
        try:
            # We need a method in LLMClient that returns raw JSON
            # Let's assume we add one or modify the existing one.
            # For now, let's create a new method in LLMClient for this.
            
            # I will add `analyze_query` to LLMClient.
            # This method will use a smaller, faster model if available.
            analysis_json_str = self.llm_client.analyze_query(question)
            
            # Parse the JSON response
            analysis_data = json.loads(analysis_json_str)
            
            # Combine with locally found video_id
            analysis_data["video_id"] = video_id
            analysis_data["original_question"] = question
            
            return analysis_data
            
        except Exception as e:
            log(f"QueryLayer: Failed to analyze query with LLM. Falling back to basic extraction. Error: {e}", "WARNING")
            # Fallback to basic method if LLM fails
            return {
                "original_question": question,
                "translated_question": question, # No translation
                "intent": "unknown",
                "keywords": self._extract_keywords(question),
                "entities": [],
                "search_queries": [question],
                "video_id": video_id
            }

    def _build_analysis_prompt(self, question: str) -> str:
        # This prompt is now handled inside LLMClient
        pass

    def _extract_video_id(self, text: str) -> str | None:
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", text)
        return match.group(1) if match else None

    def _extract_keywords(self, text: str) -> List[str]:
        stop_words = {
            "what", "is", "are", "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", 
            "how", "do", "does", "did", "can", "could", "should", "would", "why", "when", "where",
            "video", "videos", "show", "me", "tell", "about", "explain", "describe"
        }
        words = re.findall(r'\b\w+\b', text.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return keywords

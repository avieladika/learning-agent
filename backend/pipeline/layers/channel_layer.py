from .base_layer import BaseLayer
from typing import List
from backend.data_models.models import Channel
from backend.agent.llm_client import LLMClient
from backend.utils.logger import log
import json
import os

class ChannelLayer(BaseLayer):
    """
    Layer 1: Selects relevant channels based on the query using LLM.
    """
    
    def __init__(self, llm_client: LLMClient = None, channels_file: str = "channels.json"):
        self.llm_client = llm_client
        self.channels_file = channels_file

    def execute(self, query_data: dict) -> List[str]:
        """
        Selects channels.
        
        Args:
            query_data: Output from QueryLayer.
            
        Returns:
            List[str]: A list of channel IDs to search in.
        """
        channels = self._load_channels()
        if not channels:
            return []
            
        # If no LLM client provided (or for testing), return all
        if not self.llm_client:
            return [c.id for c in channels]
            
        try:
            selection_json = self.llm_client.select_channels(query_data, channels)
            selection_data = json.loads(selection_json)
            
            selected = selection_data.get("selected_channels", [])
            
            # Log the reasoning (Artifact)
            log(f"Channel Selection Reasoning:")
            for item in selected:
                log(f"  [SELECTED] {item.get('name')}: {item.get('reason')}")
                
            selected_ids = [item.get("id") for item in selected]
            
            # Safety net: If nothing selected, return all
            if not selected_ids:
                 log("No channels selected by LLM. Defaulting to all channels.", "WARNING")
                 return [c.id for c in channels]
                 
            return selected_ids
            
        except Exception as e:
            log(f"ChannelLayer: Error selecting channels: {e}", "ERROR")
            return [c.id for c in channels]

    def _load_channels(self) -> List[Channel]:
        if not os.path.exists(self.channels_file):
            return []
        try:
            with open(self.channels_file, "r") as f:
                data = json.load(f)
                return [Channel(**item) for item in data]
        except Exception:
            return []

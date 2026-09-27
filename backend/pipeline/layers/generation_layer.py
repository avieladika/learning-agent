from .base_layer import BaseLayer
from backend.agent.llm_client import LLMClient

class GenerationLayer(BaseLayer):
    """
    Layer 5: Generates the final answer using the LLM.
    """
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def execute(self, question: str, context_str: str, sources_str: str = "") -> str:
        """
        Generates answer.
        """
        if not context_str:
            return "I couldn't find any relevant information in the videos I scanned."
            
        answer = self.llm_client.generate_answer_from_string(question, context_str)
        if sources_str and not answer.startswith("LLM Error:"):
            return f"{answer.rstrip()}\n\n{sources_str}"
        return answer

    def assess_evidence(self, question: str, context_str: str) -> dict:
        return self.llm_client.assess_evidence(question, context_str)

from backend.pipeline.layers.query_layer import QueryLayer
from backend.pipeline.layers.channel_layer import ChannelLayer
from backend.pipeline.layers.video_layer import VideoLayer
from backend.pipeline.layers.content_layer import ContentLayer
from backend.pipeline.layers.context_layer import ContextLayer
from backend.pipeline.layers.generation_layer import GenerationLayer
from backend.utils.logger import log
from backend.utils.token_budget import TokenBudgets, TokenCounter, trim_history

class PipelineOrchestrator:
    def __init__(self, query_layer, channel_layer, video_layer, content_layer, context_layer, generation_layer):
        self.query_layer = query_layer
        self.channel_layer = channel_layer
        self.video_layer = video_layer
        self.content_layer = content_layer
        self.context_layer = context_layer
        self.generation_layer = generation_layer
        self.budgets = TokenBudgets()
        self.token_counter = TokenCounter(generation_layer.llm_client.model)

    def run(self, question: str, history: list[dict] | None = None) -> str:
        question = self.token_counter.truncate(question.strip(), self.budgets.question)
        history = trim_history(history or [], self.token_counter, self.budgets.history)
        standalone_question = self.generation_layer.llm_client.rewrite_question(question, history)
        standalone_question = self.token_counter.truncate(standalone_question, self.budgets.question)
        log(f"Pipeline started for: {question}")
        if standalone_question != question:
            log(f"Contextual question rewritten as: {standalone_question}")
        
        # 1. Query Analysis
        query_data = self.query_layer.execute(standalone_question)
        # Rewriting must not erase an explicit source constraint in this turn.
        explicit_video_id = self.query_layer._extract_video_id(question)
        if explicit_video_id:
            query_data["video_id"] = explicit_video_id
        log(f"Query analyzed: {query_data}")
        
        # 2. Channel Selection
        channel_ids = self.channel_layer.execute(query_data)
        log(f"Selected {len(channel_ids)} channels.")
        
        # 3. Video Retrieval
        video_ids = self.video_layer.execute(query_data, channel_ids)
        log(f"Selected {len(video_ids)} videos.")
        
        if not video_ids:
            return "I couldn't find any relevant videos."
            
        # 4. Content Extraction
        chunks = self.content_layer.execute(query_data, video_ids, channel_ids)
        log(f"Extracted {len(chunks)} content chunks.")
        
        # 5. Context Construction
        context_str = self.context_layer.execute(
            chunks, token_counter=self.token_counter, max_tokens=self.budgets.transcripts
        )
        log(
            "Token budget usage — "
            f"history: {sum(self.token_counter.count(item['content']) for item in history)}/{self.budgets.history}, "
            f"question: {self.token_counter.count(standalone_question)}/{self.budgets.question}, "
            f"transcripts: {self.token_counter.count(context_str)}/{self.budgets.transcripts}, "
            f"answer reserve: {self.budgets.answer}, safety margin: {self.budgets.safety_margin}."
        )

        # Check whether all parts of the question are supported. If not, use
        # evaluator-generated queries for one targeted retrieval pass.
        evidence = self.generation_layer.assess_evidence(standalone_question, context_str)
        targeted_queries = evidence.get("targeted_queries") or []
        if not evidence.get("sufficient", True) and targeted_queries:
            log(
                "Evidence incomplete; running targeted retrieval for: "
                + ", ".join(evidence.get("missing_concepts") or targeted_queries)
            )
            targeted_query_data = dict(query_data)
            targeted_query_data["search_queries"] = targeted_queries
            additional_chunks = self.content_layer.execute(
                targeted_query_data, video_ids, channel_ids
            )
            seen = {
                (chunk.video_id, chunk.chunk_index, chunk.start_time)
                for chunk in chunks
            }
            for chunk in additional_chunks:
                key = (chunk.video_id, chunk.chunk_index, chunk.start_time)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)
            context_str = self.context_layer.execute(
                chunks, token_counter=self.token_counter, max_tokens=self.budgets.transcripts
            )

        included_chunks = self.context_layer.select_chunks(
            chunks, self.token_counter, self.budgets.transcripts
        )
        sources_str = self.context_layer.build_sources(included_chunks)
        
        # 6. Generation
        answer = self.generation_layer.execute(standalone_question, context_str, sources_str)
        log("Answer generated.")
        
        # Debug info if needed
        if "i don't know" in answer.lower() or "couldn't find" in answer.lower():
            answer += f"\n\n--- Debug: Scanned {len(video_ids)} videos, found {len(chunks)} chunks. ---"
            
        return answer

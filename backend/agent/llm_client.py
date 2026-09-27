from typing import List, Dict, Any
from backend.data_models.models import TranscriptChunk, Channel, Video
import openai
import os
import json
from backend.utils.token_budget import TokenBudgets, TokenCounter

class LLMClient:
    def __init__(self, api_key: str, model: str | None = None):
        # Initialize OpenAI client with Groq's base URL
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )
        # Keep the model configurable so provider deprecations do not require
        # code changes. GPT-OSS 120B replaces Llama 3.3 70B on Groq's
        # free/developer tiers as of August 2026.
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.budgets = TokenBudgets()
        self.token_counter = TokenCounter(self.model)

    def rewrite_question(self, question: str, history: List[Dict[str, str]]) -> str:
        """Resolve follow-up references without allowing history to become evidence."""
        if not history:
            return question
        prompt = f"""
        Rewrite the current question as a complete standalone search question using conversation history only
        to resolve references such as "it", "that", "he", and omitted subjects. Preserve names, numbers,
        constraints, and the user's language. Do not answer the question and do not add facts. If the question
        is already standalone, return it unchanged.

        Conversation history:
        {json.dumps(history, ensure_ascii=False)}

        Current question: {question}

        Return only JSON: {{"standalone_question": "..."}}
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.budgets.answer,
                messages=[
                    {"role": "system", "content": "You rewrite follow-up questions and output only JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            rewritten = json.loads(response.choices[0].message.content).get("standalone_question", "").strip()
            return rewritten or question
        except Exception:
            return question

    def generate_answer(self, question: str, context: List[TranscriptChunk]) -> str:
        context_str = "\n".join([
            f"- Video {chunk.video_id} (Time: {chunk.start_time:.2f}s): {chunk.text}"
            for chunk in context
        ])
        return self.generate_answer_from_string(question, context_str)

    def generate_answer_from_string(self, question: str, context_str: str) -> str:
        # Enforce limits here too, including callers outside the pipeline.
        question = self.token_counter.truncate(question, self.budgets.question)
        context_str = self.token_counter.truncate(context_str, self.budgets.transcripts)
        prompt = f"""
        You are a helpful learning assistant. Your goal is to answer the user's question based ONLY on the provided context from YouTube videos.
        
        Strict Rules:
        1. Answer ONLY based on the information in the Context below. Do not use outside knowledge.
        2. You may combine multiple explicit statements from different excerpts into a cautious conclusion when
           the conclusion logically follows from them. Clearly distinguish direct speaker guidance from your
           synthesis (for example, "Taken together, these points suggest..."). Do not require the complete answer
           to appear word-for-word in one excerpt. Answer supported parts and identify precisely what is missing.
           If requested percentages or units are absent but related guidance is present, explain that and give
           the actual guidance in the speaker's units. Never invent a ratio or missing conversion inputs.
           Use "I don't know based on the provided videos" only when no substantive answer is supported.
        3. Start with a complete, self-contained answer to the question. Synthesize the relevant information
           into clear paragraphs and do not interrupt the answer with inline citations or source labels.
        4. If the context is empty or irrelevant, say "I couldn't find relevant information in the videos."
        5. Do not write a Sources section and do not reproduce source metadata. The backend appends verified
           channel, video, and timestamp citations after your answer.
        6. Use clean Markdown with clear paragraphs and lists where useful.

        Context:
        {context_str}
        
        Question: {question}
        
        Answer:
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.budgets.answer,
                messages=[{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": prompt}],
                temperature=0.0,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"LLM Error: {str(e)}"

    def analyze_query(self, question: str) -> str:
        prompt = f"""
        Analyze the following user query and return a JSON object with the following fields:
        1. "translated_question": Translate the query to English if it's not already. If it is, keep it as is.
        2. "intent": The user's intent (e.g., "informational", "instructional", "summary", "search").
        3. "keywords": A list of 3-5 most important keywords for searching YouTube videos. Expand with synonyms if helpful.
        4. "entities": A list of specific entities mentioned (e.g., "Dr. Mike", "Squat", "Mesocycle").
        5. "search_queries": A list of 4-6 concise retrieval queries. Cover every distinct part of the
           question and aggressively expand ambiguous terms into likely transcript wording and technical
           synonyms (for example: cut -> cutting, dieting, calorie deficit, fat loss, recovery, fatigue).
           Do not imitate or attribute invented statements to a named person; these are search formulations only.

        Query: "{question}"

        Return ONLY the JSON object. Do not include any other text.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.budgets.answer,
                messages=[{"role": "system", "content": "You are a helpful assistant that outputs only JSON."}, {"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content
        except Exception as e:
            return json.dumps({"translated_question": question, "intent": "unknown", "keywords": question.split(), "entities": [], "search_queries": [question]})

    def select_channels(self, query_data: Dict[str, Any], channels: List[Channel]) -> str:
        channels_info = [{"id": c.id, "name": c.name} for c in channels]
        channels_json = json.dumps(channels_info, indent=2)
        query_json = json.dumps(query_data, indent=2)
        
        prompt = f"""
        You are an intelligent router. Your task is to select which YouTube channels are relevant to answer the user's question, based on the query analysis.
        
        User Query Analysis:
        {query_json}
        
        Available Channels:
        {channels_json}
        
        Return a JSON object with a single list:
        "selected_channels": A list of objects, each containing "id", "name", and "reason" (why it's relevant).
        
        If you are unsure, err on the side of selecting the channel.
        If the question is general, you may select all channels.
        
        Return ONLY the JSON object.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.budgets.answer,
                messages=[{"role": "system", "content": "You are a helpful assistant that outputs only JSON."}, {"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content
        except Exception as e:
            fallback = {"selected_channels": [{"id": c.id, "name": c.name, "reason": "Fallback due to error"} for c in channels]}
            return json.dumps(fallback)

    def assess_evidence(self, question: str, context_str: str) -> Dict[str, Any]:
        """Check multi-part evidence coverage and propose targeted retrieval queries."""
        question = self.token_counter.truncate(question, self.budgets.question)
        context_str = self.token_counter.truncate(context_str, self.budgets.transcripts)
        prompt = f"""
        Determine whether the transcript context contains enough evidence to answer every material part of
        the user's question. Evidence may consist of multiple explicit spoken claims whose combination logically
        supports a cautious answer; the complete conclusion does not need to appear word-for-word in one excerpt.
        Relevant videos or titles alone are not sufficient.

        Question: {question}

        Context:
        {context_str}

        Return only JSON with:
        - "sufficient": boolean
        - "missing_concepts": list of concise concepts not supported by the excerpts
        - "targeted_queries": 2-4 transcript-search queries using synonyms and likely spoken wording for the
          missing concepts. If evidence is sufficient, return an empty list.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.budgets.answer,
                messages=[
                    {"role": "system", "content": "You evaluate evidence coverage and output only JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
            return {
                "sufficient": bool(data.get("sufficient")),
                "missing_concepts": data.get("missing_concepts") or [],
                "targeted_queries": data.get("targeted_queries") or [],
            }
        except Exception:
            # A failed evaluator must not prevent the normal grounded answer.
            return {"sufficient": True, "missing_concepts": [], "targeted_queries": []}

    def rank_videos(self, query_data: Dict[str, Any], videos: List[Video]) -> str:
        """
        Ranks a list of videos based on relevance to the query.
        Returns a JSON string with a ranked list of video IDs.
        """
        # Include channel_id in the video info so LLM can diversify
        videos_info = [{"id": v.id, "title": v.title, "channel_id": v.channel_id} for v in videos]
        videos_json = json.dumps(videos_info, indent=2)
        query_json = json.dumps(query_data, indent=2)

        prompt = f"""
        You are a search relevance expert. Your task is to rank the following list of YouTube videos based on how relevant their titles are to the user's query.
        
        User Query Analysis:
        {query_json}
        
        Candidate Videos:
        {videos_json}
        
        Return a JSON object with a single list:
        "ranked_videos": A list of objects, each containing "id", "title", and a "relevance_score" from 1 (least relevant) to 10 (most relevant).
        
        Strict Rules:
        1. Sort the list from most relevant to least relevant.
        2. Try to include videos from DIFFERENT channels if they are relevant (Diversity).
        3. If multiple videos seem equally relevant, prioritize diversity of channels.
        
        Return ONLY the JSON object.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.budgets.answer,
                messages=[{"role": "system", "content": "You are a helpful assistant that outputs only JSON."}, {"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content
        except Exception as e:
            # Fallback: Return original order if LLM fails
            fallback = {"ranked_videos": [{"id": v.id, "title": v.title, "relevance_score": 5} for v in videos]}
            return json.dumps(fallback)

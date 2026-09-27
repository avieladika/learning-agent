from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from .base_layer import BaseLayer
from backend.data_models.models import TranscriptChunk
from backend.ingestion.manager import IngestionManager
from backend.storage.transcript_store import TranscriptStore
from backend.storage.vector_store import VectorStore
from backend.storage.video_store import VideoStore
from backend.utils.logger import log


class ContentLayer(BaseLayer):
    """Global hybrid transcript retrieval with contextual window expansion."""

    def __init__(
        self,
        ingestion_manager: IngestionManager,
        vector_store: VectorStore,
        video_store: VideoStore,
        transcript_store: TranscriptStore,
    ):
        self.ingestion_manager = ingestion_manager
        self.vector_store = vector_store
        self.video_store = video_store
        self.transcript_store = transcript_store

    @staticmethod
    def _query_variants(query_data: dict) -> List[str]:
        variants = [
            query_data.get("original_question"),
            query_data.get("translated_question"),
            *(query_data.get("search_queries") or []),
        ]
        keywords = query_data.get("keywords") or []
        entities = query_data.get("entities") or []
        if keywords or entities:
            variants.append(" ".join([*entities, *keywords]))
        return list(dict.fromkeys(value.strip() for value in variants if value and value.strip()))

    @staticmethod
    def _key(chunk: TranscriptChunk) -> Tuple[str, int]:
        index = chunk.chunk_index if chunk.chunk_index is not None else int(chunk.start_time)
        return chunk.video_id, index

    def _canonical(self, chunk: TranscriptChunk) -> TranscriptChunk | None:
        if chunk.chunk_index is not None:
            return chunk
        return self.transcript_store.find_chunk(chunk.video_id, chunk.start_time)

    def execute(
        self,
        query_data: dict,
        video_ids: List[str],
        channel_ids: Sequence[str] | None = None,
    ) -> List[TranscriptChunk]:
        log(f"ContentLayer: preparing {len(video_ids)} title-ranked videos.")

        # Retain on-demand fallback, but bound the amount of work inside /ask.
        for video_id in video_ids[:10]:
            video = self.video_store.get_video(video_id)
            if video and not video.transcript_downloaded:
                self.ingestion_manager.ingest_video_transcript(video_id)

        direct_video_id = query_data.get("video_id")
        searchable_ids = {direct_video_id} if direct_video_id else set(video_ids)
        if channel_ids and not direct_video_id:
            # Search every transcript already indexed for routed channels. Title
            # ranking is a relevance boost, not a hard passage-retrieval gate.
            searchable_ids.update(self.video_store.get_ready_video_ids_by_channels(list(channel_ids)))
        searchable_ids = list(searchable_ids)
        if not searchable_ids:
            return []

        variants = self._query_variants(query_data)
        log(
            f"ContentLayer: hybrid search across {len(searchable_ids)} indexed videos "
            f"using {len(variants)} query variants."
        )

        rrf_scores: Dict[Tuple[str, int], float] = defaultdict(float)
        chunks_by_key: Dict[Tuple[str, int], TranscriptChunk] = {}
        coverage_keys: List[Tuple[str, int]] = []
        rrf_k = 60
        expansion_queries = set(query_data.get("search_queries") or [])

        for query in variants:
            dense = self.vector_store.search_in_videos_with_scores(query, searchable_ids, top_k=40)
            lexical = self.transcript_store.search(query, searchable_ids, limit=40)

            for rank, (chunk, _distance) in enumerate(dense, start=1):
                canonical = self._canonical(chunk)
                if not canonical:
                    continue
                key = self._key(canonical)
                chunks_by_key[key] = canonical
                rrf_scores[key] += 1.0 / (rrf_k + rank)
                if query in expansion_queries and rank <= 3:
                    coverage_keys.append(key)

            for rank, (chunk, _bm25) in enumerate(lexical, start=1):
                key = self._key(chunk)
                chunks_by_key[key] = chunk
                rrf_scores[key] += 1.0 / (rrf_k + rank)
                if query in expansion_queries and rank <= 5:
                    coverage_keys.append(key)

        title_rank = {video_id: rank for rank, video_id in enumerate(video_ids, start=1)}
        for key, chunk in chunks_by_key.items():
            if chunk.video_id in title_rank:
                rrf_scores[key] += 0.005 / title_rank[chunk.video_id]

        # Preserve coverage from LLM-expanded queries before filling remaining
        # slots by global RRF score. This prevents a recurring general concept
        # from crowding out a decisive passage for another part of the question.
        ranked_keys = list(dict.fromkeys(coverage_keys))
        for key in sorted(rrf_scores, key=rrf_scores.get, reverse=True):
            if key not in ranked_keys:
                ranked_keys.append(key)
            if len(ranked_keys) >= 16:
                break
        log(f"ContentLayer: selected {len(ranked_keys)} seed passages after RRF.")

        expanded = []
        seen = set()
        for key in ranked_keys:
            seed = chunks_by_key[key]
            if seed.chunk_index is None:
                continue
            window = self.transcript_store.get_window(seed.video_id, seed.chunk_index, radius=1)
            # Keep the relevant seed ahead of its neighbors for budget selection.
            for chunk in [seed, *window]:
                chunk_key = self._key(chunk)
                if chunk_key not in seen:
                    seen.add(chunk_key)
                    expanded.append(chunk)

        log(f"ContentLayer: expanded seed passages to {len(expanded)} contextual chunks.")
        return expanded

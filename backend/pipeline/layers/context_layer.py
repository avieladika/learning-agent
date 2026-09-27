from .base_layer import BaseLayer
from typing import List
from backend.data_models.models import TranscriptChunk
from backend.storage.video_store import VideoStore
import json
from pathlib import Path

class ContextLayer(BaseLayer):
    """
    Layer 4: Constructs the context/artifact for the LLM.
    """
    
    def __init__(self, video_store: VideoStore, channels_file: str = "channels.json", max_videos: int = 5):
        self.video_store = video_store
        self.channels_file = Path(channels_file)
        self.max_videos = max_videos

    def _channel_names(self) -> dict[str, str]:
        try:
            with self.channels_file.open() as file:
                return {item["id"]: item["name"] for item in json.load(file)}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    def execute(self, chunks: List[TranscriptChunk], token_counter=None, max_tokens: int | None = None) -> str:
        """
        Builds the context string.
        """
        if not chunks:
            return ""
        if token_counter is not None and max_tokens is not None:
            chunks = self.select_chunks(chunks, token_counter, max_tokens)
            
        # Chroma returns chunks in relevance order. Preserve the first occurrence
        # of each video to select the strongest sources, then put excerpts from
        # each selected video into chronological order.
        ranked_video_ids = list(dict.fromkeys(chunk.video_id for chunk in chunks))
        selected_video_ids = ranked_video_ids[:self.max_videos]
        channel_names = self._channel_names()
        sections = []

        if len(ranked_video_ids) > self.max_videos:
            sections.append(
                f"SELECTION NOTE: {len(ranked_video_ids)} relevant videos were found. "
                f"Only the top {self.max_videos} are included, ranked by semantic relevance "
                "of their transcript excerpts to the user's question."
            )

        for rank, video_id in enumerate(selected_video_ids, start=1):
            video = self.video_store.get_video(video_id)
            if not video:
                continue

            channel_name = channel_names.get(video.channel_id, video.channel_id)
            video_chunks = sorted(
                (chunk for chunk in chunks if chunk.video_id == video_id),
                key=lambda chunk: chunk.start_time,
            )
            lines = [
                f"SOURCE {rank}",
                f"Channel: {channel_name}",
                f"Video: {video.title}",
                f"Video URL: {video.url}",
            ]
            for chunk in video_chunks:
                timestamp = self._format_timestamp(chunk.start_time)
                timestamp_url = f"https://www.youtube.com/watch?v={video.id}&t={int(chunk.start_time)}s"
                lines.append(f"Excerpt at {timestamp} ({timestamp_url}): {chunk.text}")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def select_chunks(self, chunks, token_counter, max_tokens):
        """Pack complete excerpts by relevance before chronological rendering."""
        selected = []
        seen = set()
        video_ids = set()
        for chunk in chunks:
            key = (chunk.video_id, chunk.chunk_index, chunk.start_time)
            if key in seen or not self.video_store.get_video(chunk.video_id):
                continue
            seen.add(key)
            if chunk.video_id not in video_ids and len(video_ids) >= self.max_videos:
                continue
            candidate = [*selected, chunk]
            if token_counter.count(self.execute(candidate)) <= max_tokens:
                selected.append(chunk)
                video_ids.add(chunk.video_id)
        return selected

    def build_sources(self, chunks: List[TranscriptChunk]) -> str:
        """Build verified Markdown citations without asking the LLM to copy metadata."""
        if not chunks:
            return ""
        ranked_video_ids = list(dict.fromkeys(chunk.video_id for chunk in chunks))
        selected_video_ids = ranked_video_ids[:self.max_videos]
        channel_names = self._channel_names()
        entries = ["## Sources"]
        if len(ranked_video_ids) > self.max_videos:
            entries.append(
                f"_Selected the {self.max_videos} most relevant videos from "
                f"{len(ranked_video_ids)} candidates using hybrid transcript relevance._"
            )

        for video_id in selected_video_ids:
            video = self.video_store.get_video(video_id)
            if not video:
                continue
            channel_name = channel_names.get(video.channel_id, video.channel_id)
            ordered = sorted(
                (chunk for chunk in chunks if chunk.video_id == video_id),
                key=lambda chunk: chunk.start_time,
            )
            timestamps = []
            seen_seconds = set()
            for chunk in ordered:
                seconds = max(0, int(chunk.start_time))
                if seconds in seen_seconds:
                    continue
                seen_seconds.add(seconds)
                label = self._format_timestamp(chunk.start_time)
                url = f"https://www.youtube.com/watch?v={video.id}&t={seconds}s"
                timestamps.append(f"[{label}]({url})")
            entries.append(
                f"- **{channel_name} - {video.title}**\n"
                f"  Timestamps: {', '.join(timestamps)}"
            )
        return "\n\n".join(entries)

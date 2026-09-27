from typing import List
from backend.data_models.models import TranscriptChunk

class TextProcessor:
    def __init__(self, min_chunk_duration: float = 30.0, max_chunk_duration: float = 60.0):
        self.min_chunk_duration = min_chunk_duration
        self.max_chunk_duration = max_chunk_duration

    def process_transcript(self, raw_chunks: List[TranscriptChunk]) -> List[TranscriptChunk]:
        """
        Merges small transcript chunks into larger, more meaningful chunks.
        """
        if not raw_chunks:
            return []

        processed_chunks = []
        current_chunk_text = ""
        current_start_time = raw_chunks[0].start_time
        current_end_time = raw_chunks[0].end_time
        current_video_id = raw_chunks[0].video_id

        for chunk in raw_chunks:
            # If adding this chunk exceeds max duration, save current and start new
            if (chunk.end_time - current_start_time) > self.max_chunk_duration:
                processed_chunks.append(TranscriptChunk(
                    video_id=current_video_id,
                    text=current_chunk_text.strip(),
                    start_time=current_start_time,
                    end_time=current_end_time,
                    chunk_index=len(processed_chunks),
                ))
                # Start new chunk
                current_chunk_text = chunk.text + " "
                current_start_time = chunk.start_time
                current_end_time = chunk.end_time
            else:
                # Append to current chunk
                current_chunk_text += chunk.text + " "
                current_end_time = chunk.end_time

        # Add the last chunk
        if current_chunk_text:
            processed_chunks.append(TranscriptChunk(
                video_id=current_video_id,
                text=current_chunk_text.strip(),
                start_time=current_start_time,
                end_time=current_end_time,
                chunk_index=len(processed_chunks),
            ))

        return processed_chunks

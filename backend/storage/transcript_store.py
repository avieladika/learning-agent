import sqlite3
from collections import defaultdict
from typing import Iterable, List, Sequence, Tuple

from backend.data_models.models import TranscriptChunk
from backend.utils.logger import log


class TranscriptStore:
    """Canonical transcript storage and lexical (FTS5/BM25) retrieval."""

    def __init__(self, db_path: str = "videos.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS transcript_chunks (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    UNIQUE(video_id, chunk_index)
                );
                CREATE INDEX IF NOT EXISTS idx_transcript_video
                    ON transcript_chunks(video_id, chunk_index);
                CREATE VIRTUAL TABLE IF NOT EXISTS transcript_chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    video_id UNINDEXED,
                    text,
                    tokenize='porter unicode61'
                );
                """
            )

    @staticmethod
    def _normalize_indexes(chunks: Iterable[TranscriptChunk]) -> List[TranscriptChunk]:
        grouped = defaultdict(list)
        for chunk in chunks:
            grouped[chunk.video_id].append(chunk)

        normalized = []
        for video_chunks in grouped.values():
            for index, chunk in enumerate(sorted(video_chunks, key=lambda item: item.start_time)):
                normalized.append(chunk.model_copy(update={"chunk_index": index}))
        return normalized

    def replace_video_chunks(self, video_id: str, chunks: Sequence[TranscriptChunk]):
        normalized = self._normalize_indexes(chunks)
        normalized = [chunk for chunk in normalized if chunk.video_id == video_id]
        with self._connect() as conn:
            old_ids = [row[0] for row in conn.execute(
                "SELECT id FROM transcript_chunks WHERE video_id = ?", (video_id,)
            )]
            if old_ids:
                conn.executemany(
                    "DELETE FROM transcript_chunks_fts WHERE chunk_id = ?",
                    [(chunk_id,) for chunk_id in old_ids],
                )
            conn.execute("DELETE FROM transcript_chunks WHERE video_id = ?", (video_id,))

            rows = []
            for chunk in normalized:
                chunk_id = f"{chunk.video_id}_{chunk.chunk_index}"
                rows.append((
                    chunk_id, chunk.video_id, chunk.chunk_index, chunk.text,
                    chunk.start_time, chunk.end_time,
                ))
            conn.executemany(
                """
                INSERT INTO transcript_chunks
                    (id, video_id, chunk_index, text, start_time, end_time)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.executemany(
                "INSERT INTO transcript_chunks_fts(chunk_id, video_id, text) VALUES (?, ?, ?)",
                [(row[0], row[1], row[3]) for row in rows],
            )
        log(f"Stored {len(normalized)} canonical chunks for video {video_id}.")

    def import_chunks(self, chunks: Iterable[TranscriptChunk]) -> int:
        normalized = self._normalize_indexes(chunks)
        grouped = defaultdict(list)
        for chunk in normalized:
            grouped[chunk.video_id].append(chunk)
        for video_id, video_chunks in grouped.items():
            self.replace_video_chunks(video_id, video_chunks)
        return len(normalized)

    def count_chunks(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM transcript_chunks").fetchone()[0]

    def get_video_chunks(self, video_id: str) -> List[TranscriptChunk]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT video_id, text, start_time, end_time, chunk_index
                FROM transcript_chunks
                WHERE video_id = ?
                ORDER BY chunk_index
                """,
                (video_id,),
            ).fetchall()
        return [TranscriptChunk(**dict(row)) for row in rows]

    def get_window(self, video_id: str, chunk_index: int, radius: int = 1) -> List[TranscriptChunk]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT video_id, text, start_time, end_time, chunk_index
                FROM transcript_chunks
                WHERE video_id = ? AND chunk_index BETWEEN ? AND ?
                ORDER BY chunk_index
                """,
                (video_id, chunk_index - radius, chunk_index + radius),
            ).fetchall()
        return [TranscriptChunk(**dict(row)) for row in rows]

    def find_chunk(self, video_id: str, start_time: float) -> TranscriptChunk | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT video_id, text, start_time, end_time, chunk_index
                FROM transcript_chunks
                WHERE video_id = ?
                ORDER BY ABS(start_time - ?)
                LIMIT 1
                """,
                (video_id, start_time),
            ).fetchone()
        return TranscriptChunk(**dict(row)) if row else None

    def search(self, query: str, video_ids: Sequence[str], limit: int = 40) -> List[Tuple[TranscriptChunk, float]]:
        tokens = [token.replace('"', '') for token in query.split() if len(token) > 1]
        if not tokens or not video_ids:
            return []
        # OR improves recall; BM25 reranking later rewards multiple term matches.
        match_query = " OR ".join(f'"{token}"' for token in tokens)
        placeholders = ",".join("?" for _ in video_ids)
        sql = f"""
            SELECT c.video_id, c.text, c.start_time, c.end_time, c.chunk_index,
                   bm25(transcript_chunks_fts) AS score
            FROM transcript_chunks_fts
            JOIN transcript_chunks c ON c.id = transcript_chunks_fts.chunk_id
            WHERE transcript_chunks_fts MATCH ?
              AND c.video_id IN ({placeholders})
            ORDER BY score
            LIMIT ?
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, [match_query, *video_ids, limit]).fetchall()
        except sqlite3.OperationalError as exc:
            log(f"FTS search failed: {exc}", "WARNING")
            return []
        return [
            (TranscriptChunk(
                video_id=row["video_id"], text=row["text"],
                start_time=row["start_time"], end_time=row["end_time"],
                chunk_index=row["chunk_index"],
            ), float(row["score"]))
            for row in rows
        ]

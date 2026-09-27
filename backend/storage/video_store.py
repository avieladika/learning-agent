import sqlite3
from typing import List, Optional
from backend.data_models.models import Video
from datetime import datetime
from backend.utils.logger import log

class VideoStore:
    def __init__(self, db_path: str = "videos.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    channel_id TEXT,
                    title TEXT,
                    url TEXT,
                    published_at TEXT,
                    transcript_downloaded BOOLEAN DEFAULT 0,
                    ingestion_status TEXT DEFAULT 'NOT_REQUESTED',
                    ingestion_error TEXT,
                    ingestion_attempts INTEGER DEFAULT 0,
                    indexed_at TEXT
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(videos)")}
            migrations = {
                "ingestion_status": "ALTER TABLE videos ADD COLUMN ingestion_status TEXT DEFAULT 'NOT_REQUESTED'",
                "ingestion_error": "ALTER TABLE videos ADD COLUMN ingestion_error TEXT",
                "ingestion_attempts": "ALTER TABLE videos ADD COLUMN ingestion_attempts INTEGER DEFAULT 0",
                "indexed_at": "ALTER TABLE videos ADD COLUMN indexed_at TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    conn.execute(statement)
            conn.execute(
                "UPDATE videos SET ingestion_status = 'READY' "
                "WHERE transcript_downloaded = 1 AND ingestion_status = 'NOT_REQUESTED'"
            )
            # Create index for faster search
            conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_id ON videos (channel_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_title ON videos (title)")

    def add_videos(self, videos: List[Video]):
        if not videos:
            return
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for video in videos:
                cursor.execute("""
                    INSERT INTO videos (id, channel_id, title, url, published_at, transcript_downloaded)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        channel_id = excluded.channel_id,
                        title = excluded.title,
                        url = excluded.url,
                        published_at = excluded.published_at
                """, (
                    video.id,
                    video.channel_id,
                    video.title,
                    video.url,
                    video.published_at.isoformat(),
                    video.transcript_downloaded
                ))
            conn.commit()
        log(f"Added/Updated {len(videos)} videos in VideoStore.")

    def get_video(self, video_id: str) -> Optional[Video]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_video(row)
            return None

    def get_videos_by_channel(self, channel_id: str) -> List[Video]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE channel_id = ?", (channel_id,))
            rows = cursor.fetchall()
            return [self._row_to_video(row) for row in rows]

    def get_ready_video_ids_by_channels(self, channel_ids: List[str]) -> List[str]:
        if not channel_ids:
            return []
        placeholders = ",".join("?" for _ in channel_ids)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT id FROM videos
                WHERE channel_id IN ({placeholders}) AND transcript_downloaded = 1
                """,
                channel_ids,
            ).fetchall()
        return [row[0] for row in rows]

    def search_videos(self, query: str, limit: int = 10) -> List[Video]:
        """
        Simple keyword search in title.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Use LIKE for simple partial match
            search_term = f"%{query}%"
            cursor.execute("""
                SELECT * FROM videos 
                WHERE title LIKE ? 
                ORDER BY published_at DESC 
                LIMIT ?
            """, (search_term, limit))
            rows = cursor.fetchall()
            return [self._row_to_video(row) for row in rows]

    def search_by_keywords(self, keywords: List[str], limit: int = 20) -> List[Video]:
        """
        Searches for videos containing ANY of the keywords in the title.
        """
        if not keywords:
            return []
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Build query dynamically: title LIKE ? OR title LIKE ? ...
            conditions = " OR ".join(["title LIKE ?" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]
            
            query = f"""
                SELECT * FROM videos 
                WHERE {conditions}
                ORDER BY published_at DESC 
                LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_video(row) for row in rows]

    def mark_transcript_downloaded(self, video_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE videos
                SET transcript_downloaded = 1, ingestion_status = 'READY',
                    ingestion_error = NULL, indexed_at = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), video_id),
            )

    def mark_ingestion_started(self, video_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE videos
                SET ingestion_status = 'DOWNLOADING', ingestion_error = NULL,
                    ingestion_attempts = COALESCE(ingestion_attempts, 0) + 1
                WHERE id = ?
                """,
                (video_id,),
            )

    def mark_ingestion_failed(self, video_id: str, error: str, no_transcript: bool = False):
        status = "NO_TRANSCRIPT" if no_transcript else "FAILED"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE videos SET ingestion_status = ?, ingestion_error = ? WHERE id = ?",
                (status, error[:1000], video_id),
            )

    def delete_channel_videos(self, channel_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM videos WHERE channel_id = ?", (channel_id,))
        log(f"Deleted videos for channel {channel_id} from VideoStore.")

    def _row_to_video(self, row) -> Video:
        return Video(
            id=row[0],
            channel_id=row[1],
            title=row[2],
            url=row[3],
            published_at=datetime.fromisoformat(row[4]),
            transcript_downloaded=bool(row[5])
        )

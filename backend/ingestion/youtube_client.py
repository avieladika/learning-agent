from typing import List, Optional
import yt_dlp
from backend.data_models.models import Video, TranscriptChunk, Channel
from backend.utils.logger import log
from datetime import datetime
import json
import os
import glob

class YouTubeClient:
    def __init__(self, api_key: str = None):
        # yt-dlp doesn't need an API key
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'ignoreerrors': True,
        }

    def validate_channel(self, channel_id: str) -> bool:
        url = f"https://www.youtube.com/channel/{channel_id}"
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info is not None
        except Exception as e:
            log(f"Error validating channel {channel_id}: {e}", "ERROR")
            return False

    def get_channel_details(self, channel_id: str) -> Optional[Channel]:
        url = f"https://www.youtube.com/channel/{channel_id}"
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None
                
                return Channel(
                    id=channel_id,
                    name=info.get('uploader') or info.get('title') or "Unknown Channel",
                    last_scanned=datetime.now()
                )
        except Exception as e:
            log(f"Error fetching channel details {channel_id}: {e}", "ERROR")
            return None

    def get_all_videos_metadata(self, channel_id: str) -> List[Video]:
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
        videos = []
        
        log(f"Fetching videos from channel {channel_id} using yt-dlp...")
        
        opts = self.ydl_opts.copy()
        opts['extract_flat'] = 'in_playlist'
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return []
                
                entries = info.get('entries', [])
                if not entries:
                    return []
                
                for entry in entries:
                    if not entry: continue
                    
                    video_id = entry.get('id')
                    title = entry.get('title')
                    url = entry.get('url') or f"https://www.youtube.com/watch?v={video_id}"
                    
                    upload_date = entry.get('upload_date')
                    published_at = datetime.now()
                    if upload_date:
                        try:
                            published_at = datetime.strptime(upload_date, "%Y%m%d")
                        except ValueError:
                            pass
                    
                    video = Video(
                        id=video_id,
                        channel_id=channel_id,
                        title=title,
                        url=url,
                        published_at=published_at
                    )
                    videos.append(video)
                    
                    if len(videos) >= 500:
                        break
                        
        except Exception as e:
            log(f"Error fetching videos for channel {channel_id}: {e}", "ERROR")
            return []

        log(f"Fetched {len(videos)} videos total.")
        return videos

    def get_transcript(self, video_id: str) -> Optional[List[TranscriptChunk]]:
        """
        Fetches the transcript by letting yt-dlp download it to a temp file,
        then reading and parsing that file.
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Create a temporary filename template
        # We use the current directory for simplicity, but could use /tmp
        temp_filename = f"temp_{video_id}"
        
        opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,      # Don't download the video
            'writesubtitles': True,     # Download manual subtitles
            'writeautomaticsub': True,  # Download auto-generated subtitles
            'subtitleslangs': ['en.*', 'he'], # Get English (any variant) or Hebrew
            'subtitlesformat': 'json3', # JSON3 is easiest to parse
            'outtmpl': temp_filename,   # Output filename template
        }
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file. yt-dlp appends the language code.
            # e.g., temp_VIDEOID.en.json3
            found_file = None
            
            # Look for any json3 file starting with our temp name
            potential_files = glob.glob(f"{temp_filename}*.json3")
            
            if not potential_files:
                log(f"No subtitle file downloaded for {video_id}", "WARNING")
                return None
                
            # Prefer English if multiple exist
            for f in potential_files:
                if '.en' in f:
                    found_file = f
                    break
            
            # If no English, take the first one
            if not found_file:
                found_file = potential_files[0]
                
            # Read and parse
            with open(found_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Clean up ALL temp files for this video
            for f in potential_files:
                try:
                    os.remove(f)
                except OSError:
                    pass
                    
            return self._parse_json3_transcript(video_id, data)

        except Exception as e:
            log(f"Error fetching transcript for video {video_id}: {e}", "WARNING")
            # Cleanup on error
            for f in glob.glob(f"{temp_filename}*.json3"):
                try:
                    os.remove(f)
                except OSError:
                    pass
            return None

    def _parse_json3_transcript(self, video_id: str, data: dict) -> List[TranscriptChunk]:
        chunks = []
        events = data.get('events', [])
        
        for event in events:
            if 'segs' not in event:
                continue
                
            start_ms = event.get('tStartMs', 0)
            duration_ms = event.get('dDurationMs', 0)
            
            text = ""
            for seg in event['segs']:
                text += seg.get('utf8', '')
            
            text = text.strip()
            if not text:
                continue
                
            start_time = start_ms / 1000.0
            end_time = (start_ms + duration_ms) / 1000.0
            
            chunk = TranscriptChunk(
                video_id=video_id,
                text=text,
                start_time=start_time,
                end_time=end_time
            )
            chunks.append(chunk)

        return chunks

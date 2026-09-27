import os
from dotenv import load_dotenv
from backend.ingestion.youtube_client import YouTubeClient

# Load environment variables
load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")

if not API_KEY or API_KEY == "YOUR_YOUTUBE_API_KEY_HERE":
    print("Error: Please set your YOUTUBE_API_KEY in the .env file.")
    exit(1)

client = YouTubeClient(api_key=API_KEY)

# Example Channel ID (Google Developers)
CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw" 

print(f"Fetching videos for channel: {CHANNEL_ID}...")
videos = client.get_videos_from_channel(CHANNEL_ID, max_results=3)

if not videos:
    print("No videos found or error occurred.")
else:
    print(f"Found {len(videos)} videos:")
    for video in videos:
        print(f"- {video.title} ({video.url})")
        
        # Try to get transcript for the first video
        print(f"  Fetching transcript for video {video.id}...")
        transcript = client.get_transcript(video.id)
        
        if transcript:
            print(f"  Transcript found! First 3 lines:")
            for chunk in transcript[:3]:
                print(f"    [{chunk.start_time:.2f}s]: {chunk.text}")
        else:
            print("  No transcript available.")
        print("-" * 20)

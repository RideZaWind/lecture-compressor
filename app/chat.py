from youtube_transcript_api import YouTubeTranscriptApi
from bson import ObjectId
import yt_dlp
from dotenv import load_dotenv
import os
import re

from app.database import videos_collection



load_dotenv()
PROXY = os.getenv("PROXY")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COOKIES_PATH = os.path.join(BASE_DIR, "youtube_cookies.txt")

def get_video_data(video_id):
    document = videos_collection.find_one({"_id": ObjectId(video_id)})
    url = document.get("url")
    
    # 1. Fetch Metadata
    ydl_opts = {
        'proxy': PROXY,
        'cookiefile': COOKIES_PATH,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0',
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title')
        description = info.get('description')

    # 2. Fetch Transcript
    try:
        transcript_list = YouTubeTranscriptApi.fetch(get_video_id(url))
        transcript_text = " ".join([item['text'] for item in transcript_list])
    except Exception:
        transcript_text = "Transcript not available for this video."

    return title, description, transcript_text

def get_video_id(url):
    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(pattern, url)
    return match.group(1) if match else None
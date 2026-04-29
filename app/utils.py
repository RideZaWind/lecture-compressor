import yt_dlp
import re
import os
from dotenv import load_dotenv

load_dotenv()
PROXY = os.getenv("PROXY")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COOKIES_PATH = os.path.join(BASE_DIR, "youtube_cookies.txt")

BASE_OPTS = {
    # 'verbose': True,
    # 'runtimes': ['node'],
    'proxy': PROXY,
    'cookiefile': COOKIES_PATH,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0',
    },
    'extractor_args': {
        'youtube': {
            # Force yt-dlp to use mobile clients that don't trigger JS challenges
            'player_client': ['ios', 'android'],
        }
    },
    'ignore_no_formats_error': True, 
    # "js_runtimes": {'node':{}},
    # "compat_opts": ['ejs'],      # Enables the external JS solver
    # "js_runtime": "node",        # Specifies Node.js as the runtime
}

def is_valid_youtube_url(url):
    # Regex to capture standard, shortened, and embed links
    youtube_regex = (
        r'(https?://)?(www\.)?'
        r'(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    
    match = re.match(youtube_regex, url)
    return match is not None

def can_download_video(url, cookies_path=None):
    ydl_opts = {
        'simulate': True,          # Do NOT download the video
        'quiet': True,             # Keep logs clean
        'no_warnings': True,
    }
    
    ydl_opts.update(BASE_OPTS)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # This only fetches the "Info Dict"
            ydl.extract_info(url, download=False)
        return True, None
    except Exception as e:
        # Catch private, deleted, or regional block errors
        error_msg = str(e).split(';')[0] # Clean up the error string
        return False, error_msg
    
def format_seconds(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"

import subprocess

def get_video_duration(file_path):
    """Returns the duration of a video in seconds as a float."""
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1', 
        file_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        return float(result.stdout)
    except Exception as e:
        print(f"Error probing video: {e}")
        return 0.0
import yt_dlp
import re

def is_valid_youtube_url(url):
    # Regex to capture standard, shortened, and embed links
    youtube_regex = (
        r'(https?://)?(www\.)?'
        '(youtube|youtu|youtube-nocookie)\.(com|be)/'
        '(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    
    match = re.match(youtube_regex, url)
    return match is not None

def can_download_video(url, cookies_path=None):
    ydl_opts = {
        'simulate': True,          # Do NOT download the video
        'quiet': True,             # Keep logs clean
        'no_warnings': True,
        'cookiefile': cookies_path,
        'javascript_runtimes': ['deno'],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # This only fetches the "Info Dict"
            ydl.extract_info(url, download=False)
        return True, None
    except Exception as e:
        # Catch private, deleted, or regional block errors
        error_msg = str(e).split(';')[0] # Clean up the error string
        return False, error_msg
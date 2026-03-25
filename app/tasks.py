from bson import ObjectId
from celery import Celery
import os
import yt_dlp
import subprocess
import re
import time
from datetime import datetime
import tempfile
from dotenv import load_dotenv

from app.database import videos_collection
from app.utils import get_video_duration
    
# 1. Initialize Celery
# In production, move 'redis://localhost:6379/0' to an environment variable
celery = Celery('tasks', broker='redis://localhost:6379/0')

# 2. Define the Export Path
# This ensures files go into a dedicated folder at the root of your project
load_dotenv()
PROXY = os.getenv("PROXY")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COOKIES_PATH = os.path.join(BASE_DIR, "youtube_cookies.txt")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")

# Ensure the exports folder exists so FFmpeg doesn't crash
os.makedirs(EXPORT_DIR, exist_ok=True)

@celery.task(name='process_video_task')  # CRITICAL: Hardcoded name prevents 'Unregistered Task' error
def process_video_task(video_id):
    # We define the filenames here. 
    # NOTE: yt-dlp is told to save as .mp4 specifically in the download function
    input_file = os.path.join(BASE_DIR, f"{video_id}_input.mp4")
    output_filename = f"{video_id}_final.mp4"
    output_path = os.path.join(EXPORT_DIR, output_filename)
    
    try:
        # Convert string ID back to BSON ObjectId for MongoDB
        oid = ObjectId(video_id)
        document = videos_collection.find_one({"_id": oid})
        
        if not document:
            print(f"Error: No document found for ID {video_id}")
            return

        url = document["url"]
        params = document["params"]

        # Step 1: Download
        videos_collection.update_one({"_id": oid}, {"$set": {"status": "downloading"}})
        download_youtube_video(url, input_file)

        # Step 2: Process with FFmpeg
        videos_collection.update_one({"_id": oid}, {"$set": {"status": "processing"}})
        stats = process_video(input_file, output_path, params["threshold"], params["speed"], params["min_silence"])

        # Step 3: Success Update
        videos_collection.update_one({"_id": oid}, {
            "$set": {
                "status": "completed", 
                "path": output_filename, # Store just the filename for the download route
                "completed_at": datetime.now(),
                "stats": stats
            }
        })
        print(f"Task Completed Successfully: {video_id}")

    except Exception as e:
        # Step 4: Error Handling
        error_msg = str(e)
        print(f"Task Failed for {video_id}: {error_msg}")
        videos_collection.update_one({"_id": ObjectId(video_id)}, {
            "$set": {
                "status": "error", 
                "error_details": error_msg
            }
        })

    finally:
        # Step 5: Cleanup - Delete the temporary input file
        if os.path.exists(input_file):
            try:
                os.remove(input_file)
                print(f"Cleaned up temporary file: {input_file}")
            except Exception as e:
                print(f"Could not delete {input_file}: {e}")

def download_youtube_video(url, output_path_full):
    clean_path = output_path_full.replace("\\", "/")
    path_without_ext = os.path.splitext(clean_path)[0]
    

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': f'{path_without_ext}.%(ext)s',
        'noplaylist': True,
        'proxy': PROXY,
        'cookiefile': COOKIES_PATH,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0',
        }
    }
    
    print(f"Starting download to: {path_without_ext}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    print("yt-dlp has returned control to Python.")


def get_silence_intervals(input_file, threshold=-45, duration=0.5):
    """Pass 1: Detect silence and write to a temp file to avoid pipe deadlock."""
    # We use a temp file to store the silence logs
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp_log:
        log_path = tmp_log.name

    try:
        # We tell FFmpeg to output its logs to our temp file
        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-af", f"silencedetect=noise={threshold}dB:d={duration}",
            "-f", "null", "-"
        ]
        
        print("Starting Silence Detection Pass...")
        # We don't use capture_output=True here to avoid the hang
        with open(log_path, 'w') as f:
            subprocess.run(cmd, stderr=f, check=True)
            
        with open(log_path, 'r') as f:
            output = f.read()

        starts = re.findall(r"silence_start: ([\d\.]+)", output)
        ends = re.findall(r"silence_end: ([\d\.]+) \| silence_duration:", output)
        
        intervals = []
        last_end = 0.0
        for s, e in zip(starts, ends):
            if float(s) > last_end:
                intervals.append((last_end, float(s)))
            last_end = float(e)
        
        intervals.append((last_end, 999999.0)) 
        print(f"Detected {len(intervals)} loud segments.")
        return intervals
    finally:
        if os.path.exists(log_path):
            os.remove(log_path)

def process_video(input_file, output_file, db_threshold=-45, speed_rate=1.5, min_silence_duration=0.5):
    orig_duration = get_video_duration(input_file)
    intervals = get_silence_intervals(input_file, db_threshold, min_silence_duration)
    
    if not intervals:
        print("No speech detected. Skipping processing.")
        return None

    # Build a single 'select' expression instead of hundreds of trim nodes
    # Logic: select='between(t,s1,e1)+between(t,s2,e2)+...'
    select_expr = "+".join([f"between(t,{s},{e})" for s, e in intervals])
    
    # We combine silence removal and speed into one streamlined filter
    # 1. select/aselect: Keep only the speech intervals
    # 2. setpts/asetpts: Re-time the frames so there are no gaps
    # 3. Final setpts/atempo: Apply your 1.5x speedup
    
    v_filter = (
        f"select='{select_expr}',"
        f"setpts=N/FRAME_RATE/TB,"       # Smooths out the cuts
        f"setpts={1/speed_rate}*PTS"     # Applies speed
    )
    
    a_filter = (
        f"aselect='{select_expr}',"
        f"asetpts=N/SR/TB,"              # Smooths out the audio cuts
        f"atempo={speed_rate}"           # Applies speed
    )

    filter_script = f"[0:v]{v_filter}[v_fast];[0:a]{a_filter}[a_fast]"

    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=".txt") as f:
        f.write(filter_script)
        script_path = f.name.replace("\\", "/")

    try:
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-i", input_file,
            "-filter_complex_script", script_path,
            "-map", "[v_fast]", "-map", "[a_fast]",
            "-preset", "ultrafast", 
            "-c:v", "libx264",
            "-crf", "23",                 # Better balance of quality/speed
            "-c:a", "aac", "-b:a", "128k", # Ensure audio remains compatible
            "-movflags", "+faststart",
            output_file
        ]
        
        print(f"Processing {len(intervals)} speech segments...")
        subprocess.run(cmd, check=True)
        print("Success!")
        
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)
            
    final_duration = get_video_duration(output_file)
    
    return {
        "original_duration": orig_duration,
        "final_duration": final_duration,
        "time_saved": orig_duration - final_duration,
        "segments_processed": len(intervals)
    }
    
            
@celery.task(name="cleanup_old_videos")
def cleanup_old_videos():
    # 86400 seconds = 24 hours
    threshold = time.time() - 86400 

    if not os.path.exists(EXPORT_DIR):
        return "Export directory not found."

    count = 0
    for filename in os.listdir(EXPORT_DIR):
        file_path = os.path.join(EXPORT_DIR, filename)
        
        # Check if it's a file and if it's older than the threshold
        if os.path.isfile(file_path):
            if os.path.getmtime(file_path) < threshold:
                os.remove(file_path)
                count += 1
    
    return f"Cleaned up {count} old video files."
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, make_response
from bson.objectid import ObjectId
import yt_dlp
import os


from app.database import videos_collection, create_video_entry
from app.tasks import process_video_task


app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COOKIES_PATH = os.path.join(BASE_DIR, "youtube_cookies.txt")
EXPORT_FOLDER = os.path.join(app.root_path, '..', 'exports') 
os.makedirs(EXPORT_FOLDER, exist_ok=True)

@app.route('/', methods=["GET", "POST"])
def index():
    if request.method == "POST":
        youtube_url = request.form.get('youtube_url')
        # Optional: Add basic URL validation here
        return redirect(url_for('customize', url=youtube_url))
    return render_template('index.html')

@app.route('/customize')
def customize():
    video_url = request.args.get('url')
    ydl_opts = {
        'quiet': True, 
        'skip_download': True,
        'cookiefile': COOKIES_PATH,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
        
        video_data = {
            "title": info.get('title', 'Unknown Title'),
            "url": video_url,
            "thumbnail": info.get('thumbnail')
        }
        return render_template('customize.html', video=video_data)
    except Exception as e:
        return f"Error fetching YouTube metadata: {e}", 400

@app.route('/start-processing', methods=['POST'])
def start_processing():
    video_url = request.form.get('video_url')
    db_threshold = request.form.get('db_threshold', default=-45, type=float)
    speed_up = request.form.get('speed', default=1.0, type=float)
    min_silence = request.form.get('min_silence', default=1.0, type=float)
    
    video_task = {
        "url": video_url,
        "params": {
            "threshold": db_threshold,
            "speed": speed_up,
            "min_silence": min_silence
        }
    }
    video_id = create_video_entry(video_task)

    # Trigger Celery Task
    process_video_task.delay(str(video_id))

    # REDIRECT to the status page
    return redirect(url_for('view_status', video_id=str(video_id)))

@app.route('/status-view/<video_id>')
def view_status(video_id):
    return render_template('status.html', video_id=video_id)

from flask import url_for, make_response
from bson.objectid import ObjectId

@app.route('/status-poll/<video_id>')
def status_poll(video_id):
    document = videos_collection.find_one({"_id": ObjectId(video_id)})
    if not document:
        return "<div class='text-red-500'>Error: Job not found.</div>", 404
    
    status = document.get("status")
    
    # CASE 1: SUCCESS - Return the player and STOP polling
    if status == "completed":
        file_name = document.get("path")
        video_url = url_for('serve_video', filename=file_name)
        
        return f"""
        <div id="status-display" class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-green-500/50">
            <h2 class="text-green-400 font-bold text-2xl mb-4">Compression Complete!</h2>
            
            <div class="aspect-video w-full mb-6 bg-black rounded-lg overflow-hidden shadow-inner">
                <video controls class="w-full h-full">
                    <source src="{video_url}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
            </div>
            
            <div class="flex flex-col sm:flex-row gap-4 justify-center">
                <a href="{video_url}" download class="bg-blue-600 hover:bg-blue-500 text-white px-8 py-3 rounded-md font-bold transition">
                    Download MP4
                </a>
                <a href="/" class="bg-gray-700 hover:bg-gray-600 text-white px-8 py-3 rounded-md font-bold transition">
                    New Video
                </a>
            </div>
        </div>
        """

    # CASE 2: ERROR - Show what went wrong and STOP polling
    elif status == "error":
        error_msg = document.get('error_details', 'An unknown error occurred during FFmpeg processing.')
        return f"""
        <div id="status-display" class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-red-500/50">
            <div class="text-red-500 text-5xl mb-4">⚠️</div>
            <h2 class="text-white font-bold text-2xl mb-2">Processing Failed</h2>
            <p class="text-gray-400 mb-6 text-sm">{error_msg}</p>
            <a href="/" class="bg-red-600 hover:bg-red-500 text-white px-6 py-2 rounded-md transition">
                Try Again
            </a>
        </div>
        """

    # CASE 3: IN PROGRESS - Keep polling
    else:
        # Note: We include hx-get and hx-trigger here so the loop CONTINUES
        # while the status is 'downloading' or 'processing'.
        display_status = status.replace("_", " ").capitalize() if status else "Queued"
        
        return f"""
        <div id="status-display" 
             hx-get="/status-poll/{video_id}" 
             hx-trigger="every 5s" 
             hx-swap="outerHTML"
             class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-gray-700 text-center">
            
            <div class="flex flex-col items-center">
                <div class="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500 mb-6"></div>
                <h1 class="text-2xl font-bold mb-2">Status: {display_status}...</h1>
                <p class="text-gray-400 italic text-sm">
                    FFmpeg is currently re-encoding and syncing your streams.
                </p>
            </div>
        </div>
        """

@app.route('/download/<filename>')
def download_file(filename):
    # This route allows the user to actually fetch the MP4 from the 'exports' folder
    return send_from_directory(directory=EXPORT_FOLDER, path=filename, as_attachment=True)

@app.route('/video/<filename>')
def serve_video(filename):
    # This route allows the browser to 'stream' the video into the player
    # We ensure it's pointing to your 'exports' folder
    return send_from_directory(
        directory=EXPORT_FOLDER, 
        path=filename, 
        mimetype='video/mp4',
        as_attachment=False # Crucial: False means 'display in browser'
    )

def main():
    app.run()

if __name__ == '__main__':
    main()
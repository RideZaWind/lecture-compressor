from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from bson.objectid import ObjectId
import yt_dlp
import os
from dotenv import load_dotenv
import openai

from app.database import videos_collection, create_video_entry
from app.tasks import process_video_task
from app.utils import is_valid_youtube_url, format_seconds, BASE_OPTS
from app.chat import get_video_data


app = Flask(__name__)

load_dotenv()
PROXY = os.getenv("PROXY")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COOKIES_PATH = os.path.join(BASE_DIR, "youtube_cookies.txt")
EXPORT_FOLDER = os.path.join(app.root_path, '..', 'exports') 
os.makedirs(EXPORT_FOLDER, exist_ok=True)

from flask import flash, redirect, url_for, request, render_template
from app.utils import is_valid_youtube_url, can_download_video

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('youtube_url')
        
        # 1. Double check the format
        if not is_valid_youtube_url(url):
            flash("Invalid YouTube URL format.", "error")
            return redirect(url_for('index'))

        # 2. Pre-flight check (Simulate download)
        # Assuming COOKIES_PATH is defined in your config
        can_dl, error_msg = can_download_video(url, COOKIES_PATH)
        
        if not can_dl:
            flash(f"Could not reach video: {error_msg}", "error")
            return redirect(url_for('index'))

        # 3. Success -> Move to next step (Customization)
        return redirect(url_for('customize', url=url))
        
    return render_template('index.html')

@app.route('/customize')
def customize():
    video_url = request.args.get('url')
    ydl_opts = {
        'quiet': True, 
        'skip_download': True,
    }
    
    ydl_opts.update(BASE_OPTS)

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


@app.route('/status-poll/<video_id>')
def status_poll(video_id):
    document = videos_collection.find_one({"_id": ObjectId(video_id)})
    if not document:
        return "<div class='text-red-500'>Error: Video not found in database. Please try again.</div>", 404
    
    status = document.get("status")
    
    # CASE 1: SUCCESS - Return the player and STOP polling
    if status == "completed":
        file_name = document.get("path")
        video_url = url_for('serve_video', filename=file_name)
        
        stats = document["stats"]
        time_saved = stats["time_saved"]
        original_duration = stats["original_duration"]  # avoid divide by zero
        final_duration = stats["final_duration"]
        params = document["params"]
        speed = params["speed"]
        threshold = params["threshold"]
        min_silence = params["min_silence"]
        
        efficiency = round((time_saved / original_duration) * 100, 1)
        
        return f"""
        <div id="status-display" class="bg-gray-800 p-8 rounded-2xl shadow-2xl border border-green-500/50">
            <h2 class="text-green-400 font-bold text-2xl mb-4">Compression Complete!</h2>

            <div class="aspect-video w-full mb-6 bg-black rounded-lg overflow-hidden shadow-inner">
                <video controls class="w-full h-full">
                    <source src="{video_url}" type="video/mp4">
                </video>
            </div>

            <div class="flex flex-col sm:flex-row gap-4 justify-center mb-8">
                <a href="{video_url}" download class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-md font-bold transition text-center">
                    Download MP4
                </a>

                <a href="/chat/{video_id}" target="_blank" class="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-3 rounded-md font-bold transition text-center flex items-center justify-center">
                    AI Summary & Chat
                </a>

                <a href="/" class="bg-gray-700 hover:bg-gray-600 text-white px-6 py-3 rounded-md font-bold transition text-center">
                    New Video
                </a>
            </div>

            <!-- STATS SECTION -->
            <div class="grid grid-cols-2 gap-4 mb-8">
                <div class="bg-blue-900/20 border border-blue-500/30 p-4 rounded-xl text-center">
                    <p class="text-xs text-blue-300 uppercase tracking-wider font-semibold">Time Shaved Off</p>
                    <p class="text-3xl font-bold text-white mt-1">{format_seconds(time_saved)}</p>
                </div>

                <div class="bg-green-900/20 border border-green-500/30 p-4 rounded-xl text-center">
                    <p class="text-xs text-green-300 uppercase tracking-wider font-semibold">Efficiency Boost</p>
                    <p class="text-3xl font-bold text-white mt-1">{efficiency}%</p>
                </div>
            </div>

            <div class="bg-gray-900 rounded-xl p-4 border border-gray-700">
                <h3 class="text-sm font-semibold text-gray-400 mb-3 border-b border-gray-800 pb-2">
                    Customization Parameters
                </h3>

                <div class="space-y-3">
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-500">Playback Speed</span>
                        <span class="text-white font-mono">{speed}x</span>
                    </div>

                    <div class="flex justify-between text-sm">
                        <span class="text-gray-500">Silence Threshold</span>
                        <span class="text-white font-mono">{threshold}dB</span>
                    </div>
                    
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-500">Min. Silence Length</span>
                        <span class="text-white font-mono">{min_silence}s</span>
                    </div>

                    <div class="flex justify-between text-sm">
                        <span class="text-gray-500">Original Length</span>
                        <span class="text-white">{format_seconds(original_duration)}</span>
                    </div>

                    <div class="flex justify-between text-sm">
                        <span class="text-gray-500">New Length</span>
                        <span class="text-white font-bold text-blue-400">{format_seconds(final_duration)}</span>
                    </div>
                </div>
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
    

@app.route('/submit-url', methods=['POST'])
def submit_url():
    url = request.form.get('youtube_url')
    
    # 1. Structural Check (Regex)
    if not is_valid_youtube_url(url):
        flash("That format doesn't look like a YouTube link.", "error")
        return redirect(url_for('index'))

    # 2. Availability Check (Simulation)
    # Pass your COOKIES_PATH here to check for age-restricted videos
    is_available, error = can_download_video(url, COOKIES_PATH)
    
    if not is_available:
        flash(f"YouTube says: {error}", "error")
        return redirect(url_for('index'))

    # 3. Success
    return redirect(url_for('customize_page', video_url=url))

@app.route('/chat/<video_id>')
def video_chat(video_id):
    return render_template('chat_interface.html', video_id=video_id)

@app.route('/api/chat', methods=['POST'])
def ai_chat():
    data = request.json
    user_message = data.get('message')
    title, description, transcript_text = get_video_data(data.get('video_id'))

    response = openai.chat.completions.create(
        model="gpt-4o-mini", # Efficient and cheap for summaries
        messages=[
            {"role": "system", "content": f"You are an assistant for this video. Metadata: {title}. Description: {description}. Transcript: {transcript_text}"},
            {"role": "user", "content": user_message}
        ]
    )
    return {"reply": response.choices[0].message.content}

def main():
    app.run()

if __name__ == '__main__':
    main()
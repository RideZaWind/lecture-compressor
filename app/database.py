from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
client = MongoClient(os.getenv("MONGO_URI"))
db = client["lecture_db"]
videos_collection = db["videos"]
    
# TODO: rename method and param
def create_video_entry(task_details: dict):
    task_details.update({
        "created_at": datetime.now(),
        "status": "queued"
    })
    return videos_collection.insert_one(task_details).inserted_id
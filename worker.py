from app.tasks import celery
from app.tasks import cleanup_old_videos
from celery.schedules import crontab

if __name__ == '__main__':
    celery.start()
    
celery.conf.beat_schedule = {
    'cleanup-hourly': {
        'task': 'cleanup_old_videos',
        'schedule': crontab(minute=0), # Runs once an hour, at the 0 minute mark
    },
}
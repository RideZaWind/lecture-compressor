from app.tasks import celery
from celery.schedules import crontab

if __name__ == '__main__':
    celery.start()
    
celery.conf.beat_schedule = {
    'cleanup-hourly': {
        'task': 'app.tasks.cleanup_old_videos',
        'schedule': crontab(minute=0), # Runs once an hour, at the 0 minute mark
    },
}
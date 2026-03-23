from app.tasks import celery
from celery.schedules import crontab

if __name__ == '__main__':
    celery.start()
    
celery.conf.beat_schedule = {
    'cleanup-every-midnight': {
        'task': 'cleanup_old_videos',
        'schedule': crontab(minute=0, hour=0), # Runs at 00:00 every day
    },
}
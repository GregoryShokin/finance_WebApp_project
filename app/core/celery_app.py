from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery("finance_worker", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.beat_schedule = {
    "monthly-capital-snapshot": {
        "task": "monthly_capital_snapshot",
        "schedule": crontab(day_of_month="1", hour="3", minute="0"),
    },
}

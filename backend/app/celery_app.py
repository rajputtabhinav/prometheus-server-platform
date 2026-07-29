from celery import Celery

from app.core.config import settings


celery_app = Celery("prometheus", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_always_eager = settings.celery_task_always_eager
celery_app.conf.beat_schedule = {
    "process-due-schedules": {
        "task": "app.jobs.process_due_schedules",
        "schedule": max(15, settings.reconcile_interval_seconds),
    },
    "reconcile-runtime": {
        "task": "app.jobs.reconcile_runtime",
        "schedule": max(15, settings.reconcile_interval_seconds),
    },
}
celery_app.conf.task_routes = {
    "app.jobs.process_due_schedules": {"queue": "workflows"},
    "app.jobs.reconcile_runtime": {"queue": "runtime"},
    "app.jobs.refresh_workflow": {"queue": "workflows"},
}

celery_app.autodiscover_tasks(["app"])

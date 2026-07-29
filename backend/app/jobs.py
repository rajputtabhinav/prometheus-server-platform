from __future__ import annotations

from app.celery_app import celery_app
from app.services.runtime import runtime


@celery_app.task(name="app.jobs.process_due_schedules")
def process_due_schedules() -> dict[str, int]:
    dispatched = runtime.process_due_schedules()
    return {"dispatched": dispatched}


@celery_app.task(name="app.jobs.reconcile_runtime")
def reconcile_runtime() -> dict[str, int]:
    timed_out = runtime.reconcile_runtime()
    return {"timed_out": timed_out}


@celery_app.task(name="app.jobs.refresh_workflow")
def refresh_workflow(workflow_id: str) -> dict[str, str]:
    runtime.refresh_workflow(workflow_id)
    return {"workflow_id": workflow_id}

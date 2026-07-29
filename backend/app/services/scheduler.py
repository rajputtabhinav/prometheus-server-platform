from __future__ import annotations

from sqlalchemy.orm import Session

from app.db_models import ScheduleTable
from app.services.repositories import repository


def collect_due_schedules(session: Session) -> list[ScheduleTable]:
    return repository.due_schedules(session)

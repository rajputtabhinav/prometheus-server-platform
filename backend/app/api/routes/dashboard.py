from typing import Literal

from fastapi import APIRouter

from app.models import DashboardHistory, DashboardSummary
from app.services.runtime import runtime


router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary() -> DashboardSummary:
    return runtime.dashboard_summary()


@router.get("/history", response_model=DashboardHistory)
def dashboard_history(period: Literal["week", "month", "year"] = "month") -> DashboardHistory:
    return runtime.dashboard_history(period)

from fastapi import APIRouter

from app.api.routes import agents, auth, control, dashboard


api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(control.router, prefix="/control", tags=["control"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

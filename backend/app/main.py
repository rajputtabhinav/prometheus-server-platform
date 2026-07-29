import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette import status
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.migrations import upgrade_database
from app.models import LiveEvent, TerminalInputRequest, TerminalResizeRequest
from app.services.auth import auth_service
from app.services.realtime import realtime_manager
from app.services.runtime import runtime
from app.services.terminal import terminal_socket_manager


app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.on_event("startup")
async def seed_runtime() -> None:
    upgrade_database()
    auth_service.ensure_default_users()
    runtime.initialize()
    if settings.seed_demo_data:
        runtime.seed_demo_data()


@app.get("/health")
def health() -> dict:
    summary = runtime.dashboard_summary()
    return {
        "status": "ok",
        "service": settings.app_name,
        "servers": summary.fleet_total,
        "queued_tasks": len([run for run in summary.recent_runs if run.status == "pending"]),
        "active_runs": summary.active_runs,
    }


async def _monitoring_socket(websocket: WebSocket) -> None:
    await realtime_manager.connect(websocket)
    await websocket.send_json(
        LiveEvent(
            event_type="socket.connected",
            payload={"message": "Live monitoring stream connected."},
        ).model_dump(mode="json")
    )
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json(
                LiveEvent(
                    event_type="socket.keepalive",
                    payload={"status": "alive"},
                ).model_dump(mode="json")
            )
    except WebSocketDisconnect:
        realtime_manager.disconnect(websocket)


@app.websocket("/ws/monitoring")
async def monitoring_socket(websocket: WebSocket) -> None:
    await _monitoring_socket(websocket)


@app.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    await _monitoring_socket(websocket)


@app.websocket("/ws/terminal/{session_id}")
async def terminal_socket(websocket: WebSocket, session_id: str) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Bearer token required.")
        return
    try:
        user = auth_service.authenticate_bearer(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid bearer token.")
        return
    if user.role.value != "admin":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="admin role required.")
        return

    session_record = runtime.touch_terminal_browser(session_id)
    await terminal_socket_manager.connect(session_id, websocket)
    await websocket.send_json(
        {
            "kind": "session",
            "session": session_record.model_dump(mode="json"),
        }
    )
    try:
        while True:
            message = await websocket.receive_json()
            action = str(message.get("kind") or "")
            if action == "input":
                session_record = runtime.queue_terminal_input(
                    session_id,
                    TerminalInputRequest(data=str(message.get("data") or "")),
                    actor=user.username,
                )
                await terminal_socket_manager.broadcast(session_id, {"kind": "status", "session": session_record.model_dump(mode="json")})
            elif action == "resize":
                cols = int(message.get("cols") or 120)
                rows = int(message.get("rows") or 32)
                session_record = runtime.resize_terminal_session(
                    session_id,
                    TerminalResizeRequest(cols=cols, rows=rows),
                    actor=user.username,
                )
                await terminal_socket_manager.broadcast(session_id, {"kind": "status", "session": session_record.model_dump(mode="json")})
            elif action == "close":
                session_record = runtime.close_terminal_session(session_id, actor=user.username)
                await terminal_socket_manager.broadcast(session_id, {"kind": "session", "session": session_record.model_dump(mode="json")})
            else:
                session_record = runtime.touch_terminal_browser(session_id)
                await websocket.send_json({"kind": "status", "session": session_record.model_dump(mode="json")})
    except WebSocketDisconnect:
        await terminal_socket_manager.disconnect(session_id, websocket)

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from app.models import (
    AgentEnrollmentClaimRequest,
    AgentEnrollmentClaimResponse,
    AgentReleaseManifest,
    AgentTargetOS,
    AgentAuthRequest,
    HeartbeatPayload,
    HardwareOverviewResponse,
    HardwareReportPayload,
    LiveEvent,
    MetricEnvelope,
    RegistrationResponse,
    ServerRecord,
    ServerRegistration,
    TerminalAgentSyncRequest,
    TerminalAgentSyncResponse,
    TaskAssignment,
    TaskResult,
    TaskRun,
)
from app.services.agent_install import agent_install_service
from app.services.realtime import realtime_manager
from app.services.runtime import runtime
from app.services.terminal import terminal_socket_manager


router = APIRouter()


@router.post("/register", response_model=RegistrationResponse)
async def register_agent(payload: ServerRegistration) -> RegistrationResponse:
    response = runtime.register_server(payload)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="server.registered",
            payload={"server_id": response.server_id, "server_name": payload.server_name},
        ).model_dump(mode="json")
    )
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="agent.connected",
            payload={"server_id": response.server_id, "server_name": payload.server_name, "group": payload.group},
        ).model_dump(mode="json")
    )
    return response


@router.post("/bootstrap/claim", response_model=AgentEnrollmentClaimResponse)
async def claim_agent_enrollment(payload: AgentEnrollmentClaimRequest) -> AgentEnrollmentClaimResponse:
    claimed = runtime.claim_agent_enrollment(payload)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="agent.enrollment_claimed",
            payload={"enrollment_id": claimed.enrollment_id, "server_id": claimed.server_id, "server_name": claimed.server_name},
        ).model_dump(mode="json")
    )
    return claimed


@router.get("/releases/manifest", response_model=AgentReleaseManifest)
def get_agent_release_manifest(request: Request) -> AgentReleaseManifest:
    return runtime.agent_release_manifest(agent_install_service.public_base_url(str(request.base_url).rstrip("/")))


@router.get("/releases/download/{target_os}/{arch}/{filename}")
def download_agent_release(target_os: AgentTargetOS, arch: str, filename: str) -> FileResponse:
    path = agent_install_service.ensure_release_artifact(target_os, arch)
    if path.name != filename or not path.exists():
        raise HTTPException(status_code=404, detail="Agent release artifact not found.")
    return FileResponse(path=path, filename=filename)


@router.get("/releases/download/{target_os}/{arch}/{filename}.sha256")
def download_agent_release_checksum(target_os: AgentTargetOS, arch: str, filename: str) -> PlainTextResponse:
    path = agent_install_service.ensure_release_artifact(target_os, arch)
    if path.name != filename or not path.exists():
        raise HTTPException(status_code=404, detail="Agent release checksum not found.")
    checksum = agent_install_service.checksum(path)
    return PlainTextResponse(f"{checksum}  {filename}\n")


@router.get("/install/{target_os}")
def bootstrap_install_script(
    target_os: AgentTargetOS,
    request: Request,
    connection_code: str = Query(...),
) -> PlainTextResponse:
    public_base_url = agent_install_service.public_base_url(str(request.base_url).rstrip("/"))
    script = agent_install_service.bootstrap_script(target_os, public_base_url, connection_code)
    return PlainTextResponse(script, media_type="text/plain; charset=utf-8")


@router.post("/{server_id}/heartbeat", response_model=ServerRecord)
async def agent_heartbeat(server_id: str, payload: HeartbeatPayload) -> ServerRecord:
    server = runtime.record_heartbeat(server_id, payload)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="server.heartbeat",
            payload={"server_id": server.server_id, "status": server.status.value},
        ).model_dump(mode="json")
    )
    return server


@router.post("/{server_id}/metrics")
async def ingest_metrics(server_id: str, payload: MetricEnvelope):
    snapshot = runtime.record_metric(server_id, payload)
    await realtime_manager.broadcast(
        LiveEvent(event_type="metric.updated", payload=snapshot.model_dump(mode="json")).model_dump(mode="json")
    )
    return snapshot


@router.post("/{server_id}/hardware-report", response_model=HardwareOverviewResponse)
async def ingest_hardware_report(server_id: str, payload: HardwareReportPayload) -> HardwareOverviewResponse:
    overview = runtime.record_hardware_report(server_id, payload)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="hardware.updated",
            payload={
                "server_id": server_id,
                "overall_health": overview.overall_health.value,
                "hot_components": len(overview.hot_components),
                "failing_components": len(overview.failing_components),
            },
        ).model_dump(mode="json")
    )
    return overview


@router.post("/{server_id}/next-task", response_model=TaskAssignment | None)
async def poll_next_task(server_id: str, payload: AgentAuthRequest) -> TaskAssignment | None:
    assignment = runtime.poll_next_task(server_id, payload)
    if assignment:
        await realtime_manager.broadcast(
            LiveEvent(
                event_type="task.started",
                payload={
                    "task_id": assignment.task_id,
                    "server_id": server_id,
                    "task": assignment.task,
                    "workflow_id": assignment.workflow_id,
                },
            ).model_dump(mode="json")
        )
    return assignment


@router.post("/{server_id}/task-result", response_model=TaskRun)
async def submit_task_result(server_id: str, payload: TaskResult) -> TaskRun:
    task_run = runtime.submit_task_result(server_id, payload)
    event_type = "task.completed"
    if task_run.status == "pending":
        event_type = "task.requeued"
    await realtime_manager.broadcast(
        LiveEvent(
            event_type=event_type,
            payload={
                "task_id": task_run.task_id,
                "server_id": server_id,
                "task": task_run.task,
                "status": task_run.status.value,
                "score": task_run.score,
            },
        ).model_dump(mode="json")
    )
    return task_run


@router.post("/{server_id}/terminal-sync", response_model=TerminalAgentSyncResponse)
async def sync_terminal(server_id: str, payload: TerminalAgentSyncRequest) -> TerminalAgentSyncResponse:
    response = runtime.sync_terminal_agent(server_id, payload)
    for update in payload.sessions:
        try:
            session = runtime.get_terminal_session(update.session_id)
        except HTTPException:
            continue
        for chunk in update.outputs:
            if chunk:
                await terminal_socket_manager.broadcast(
                    update.session_id,
                    {"kind": "output", "session_id": update.session_id, "text": chunk},
                )
        await terminal_socket_manager.broadcast(
            update.session_id,
            {"kind": "session", "session": session.model_dump(mode="json")},
        )
    return response

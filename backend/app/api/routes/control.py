from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from app.core.security import get_current_user, require_role
from app.models import (
    AgentEnrollment,
    AgentEnrollmentCreate,
    AgentInstallCommandResponse,
    AgentTargetOS,
    AllowedTask,
    AlertRecord,
    AlertRule,
    AlertRuleCreate,
    AlertStatusUpdate,
    AuthenticatedUser,
    AuditEvent,
    BaselinePolicy,
    BaselinePolicyCreate,
    FleetMonitoringResponse,
    HardwareInventoryResponse,
    HardwareMetricSeries,
    HardwareOverviewResponse,
    LiveEvent,
    NodeDetailResponse,
    NotificationEndpoint,
    NotificationEndpointCreate,
    RunDetailResponse,
    ScheduleCreate,
    ScheduleRecord,
    ScheduleUpdate,
    ServerView,
    TaskDispatchRequest,
    TaskRun,
    TerminalInputRequest,
    TerminalOpenRequest,
    TerminalResizeRequest,
    TerminalSession,
    TerminalSessionSummary,
    UserRole,
    WorkflowDispatchRequest,
    WorkflowRun,
    WorkflowTemplate,
)
from app.services.catalog import list_allowed_tasks, list_workflow_templates
from app.services.realtime import realtime_manager
from app.services.runtime import runtime


router = APIRouter()


@router.get("/servers", response_model=list[ServerView])
def list_servers(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[ServerView]:
    return runtime.list_servers()


@router.get("/agent-enrollments", response_model=list[AgentEnrollment])
def list_agent_enrollments(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[AgentEnrollment]:
    return runtime.list_agent_enrollments()


@router.post("/agent-enrollments", response_model=AgentEnrollment)
async def create_agent_enrollment(
    payload: AgentEnrollmentCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> AgentEnrollment:
    enrollment = runtime.create_agent_enrollment(payload.model_copy(update={"created_by": current_user.username}))
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="agent.enrollment_created",
            payload={"enrollment_id": enrollment.enrollment_id, "display_name": enrollment.display_name, "target_os": enrollment.target_os.value},
        ).model_dump(mode="json")
    )
    return enrollment


@router.post("/agent-enrollments/{enrollment_id}/revoke", response_model=AgentEnrollment)
async def revoke_agent_enrollment(
    enrollment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> AgentEnrollment:
    enrollment = runtime.revoke_agent_enrollment(enrollment_id, actor=current_user.username)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="agent.enrollment_revoked",
            payload={"enrollment_id": enrollment.enrollment_id, "display_name": enrollment.display_name},
        ).model_dump(mode="json")
    )
    return enrollment


@router.get("/agent-enrollments/{enrollment_id}/install-command", response_model=AgentInstallCommandResponse)
def get_agent_install_command(
    enrollment_id: str,
    request: Request,
    target_os: AgentTargetOS,
    _: UserRole = Depends(require_role(UserRole.VIEWER)),
) -> AgentInstallCommandResponse:
    return runtime.agent_install_command(enrollment_id, target_os, str(request.base_url).rstrip("/"))


@router.get("/nodes/{server_id}", response_model=NodeDetailResponse)
def get_node_detail(server_id: str, _: UserRole = Depends(require_role(UserRole.VIEWER))) -> NodeDetailResponse:
    return runtime.get_node_detail(server_id)


@router.get("/nodes/{server_id}/hardware", response_model=HardwareOverviewResponse)
def get_hardware_overview(server_id: str, _: UserRole = Depends(require_role(UserRole.VIEWER))) -> HardwareOverviewResponse:
    return runtime.get_hardware_overview(server_id)


@router.get("/monitoring/fleet", response_model=FleetMonitoringResponse)
def get_fleet_monitoring(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> FleetMonitoringResponse:
    return runtime.get_fleet_monitoring()


@router.get("/terminal/sessions", response_model=list[TerminalSessionSummary])
def list_terminal_sessions(
    server_id: str | None = None,
    _: UserRole = Depends(require_role(UserRole.ADMIN)),
) -> list[TerminalSessionSummary]:
    return runtime.list_terminal_sessions(server_id=server_id)


@router.post("/terminal/sessions", response_model=TerminalSession)
def open_terminal_session(
    payload: TerminalOpenRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.ADMIN)),
) -> TerminalSession:
    return runtime.open_terminal_session(payload, actor=current_user.username)


@router.get("/terminal/sessions/{session_id}", response_model=TerminalSession)
def get_terminal_session(
    session_id: str,
    _: UserRole = Depends(require_role(UserRole.ADMIN)),
) -> TerminalSession:
    return runtime.get_terminal_session(session_id)


@router.post("/terminal/sessions/{session_id}/input", response_model=TerminalSession)
def send_terminal_input(
    session_id: str,
    payload: TerminalInputRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.ADMIN)),
) -> TerminalSession:
    return runtime.queue_terminal_input(session_id, payload, actor=current_user.username)


@router.post("/terminal/sessions/{session_id}/resize", response_model=TerminalSession)
def resize_terminal_session(
    session_id: str,
    payload: TerminalResizeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.ADMIN)),
) -> TerminalSession:
    return runtime.resize_terminal_session(session_id, payload, actor=current_user.username)


@router.post("/terminal/sessions/{session_id}/close", response_model=TerminalSession)
def close_terminal_session(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.ADMIN)),
) -> TerminalSession:
    return runtime.close_terminal_session(session_id, actor=current_user.username)


@router.get("/nodes/{server_id}/inventory", response_model=HardwareInventoryResponse)
def get_hardware_inventory(server_id: str, _: UserRole = Depends(require_role(UserRole.VIEWER))) -> HardwareInventoryResponse:
    return runtime.get_hardware_inventory(server_id)


@router.get("/components/{component_id}/history", response_model=HardwareMetricSeries)
def get_component_history(
    component_id: str,
    metric_key: str | None = None,
    limit: int = 120,
    _: UserRole = Depends(require_role(UserRole.VIEWER)),
) -> HardwareMetricSeries:
    return runtime.get_component_metric_series(component_id, metric_key=metric_key, limit=limit)


@router.get("/tasks/catalog", response_model=list[AllowedTask])
def task_catalog(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[AllowedTask]:
    return list_allowed_tasks()


@router.get("/workflows/catalog", response_model=list[WorkflowTemplate])
def workflow_catalog(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[WorkflowTemplate]:
    return list_workflow_templates()


@router.post("/tasks/dispatch", response_model=TaskRun)
async def dispatch_task(
    payload: TaskDispatchRequest,
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> TaskRun:
    task_run = runtime.dispatch_task(payload)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="task.queued",
            payload={"task_id": task_run.task_id, "server_id": task_run.server_id, "task": task_run.task},
        ).model_dump(mode="json")
    )
    return task_run


@router.post("/workflows/dispatch", response_model=WorkflowRun)
async def dispatch_workflow(
    payload: WorkflowDispatchRequest,
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> WorkflowRun:
    workflow = runtime.dispatch_workflow(payload)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="workflow.queued",
            payload={
                "workflow_id": workflow.workflow_id,
                "server_id": workflow.server_id,
                "workflow": workflow.workflow,
                "steps": workflow.steps,
            },
        ).model_dump(mode="json")
    )
    return workflow


@router.get("/runs", response_model=list[TaskRun])
def list_runs(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[TaskRun]:
    return runtime.list_runs()


@router.get("/runs/{task_id}", response_model=RunDetailResponse)
def get_run(task_id: str, _: UserRole = Depends(require_role(UserRole.VIEWER))) -> RunDetailResponse:
    return runtime.get_run_detail(task_id)


@router.get("/runs/{task_id}/artifacts/{artifact_id}")
def download_run_artifact(
    task_id: str,
    artifact_id: str,
    _: UserRole = Depends(require_role(UserRole.VIEWER)),
) -> FileResponse:
    artifact, file_path = runtime.get_run_artifact(task_id, artifact_id)
    return FileResponse(path=file_path, media_type=artifact.content_type, filename=f"{artifact.label}{artifact.metadata.get('extension', '')}")


@router.post("/runs/{task_id}/retry", response_model=TaskRun)
async def retry_run(
    task_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> TaskRun:
    task_run = runtime.retry_task(task_id, actor=current_user.username)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="task.requeued",
            payload={"task_id": task_run.task_id, "server_id": task_run.server_id, "task": task_run.task, "status": task_run.status.value},
        ).model_dump(mode="json")
    )
    return task_run


@router.post("/runs/{task_id}/cancel", response_model=TaskRun)
async def cancel_run(
    task_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> TaskRun:
    task_run = runtime.cancel_task(task_id, actor=current_user.username)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="task.cancelled",
            payload={"task_id": task_run.task_id, "server_id": task_run.server_id, "task": task_run.task, "status": task_run.status.value},
        ).model_dump(mode="json")
    )
    return task_run


@router.get("/workflows", response_model=list[WorkflowRun])
def list_workflows(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[WorkflowRun]:
    return runtime.list_workflows()


@router.post("/workflows/{workflow_id}/cancel", response_model=WorkflowRun)
async def cancel_workflow(
    workflow_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> WorkflowRun:
    workflow = runtime.cancel_workflow(workflow_id, actor=current_user.username)
    await realtime_manager.broadcast(
        LiveEvent(
            event_type="workflow.cancelled",
            payload={"workflow_id": workflow.workflow_id, "server_id": workflow.server_id, "workflow": workflow.workflow, "status": workflow.status.value},
        ).model_dump(mode="json")
    )
    return workflow


@router.get("/alerts", response_model=list[AlertRecord])
def list_alerts(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[AlertRecord]:
    return runtime.list_alerts()


@router.get("/alert-rules", response_model=list[AlertRule])
def list_alert_rules(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[AlertRule]:
    return runtime.list_alert_rules()


@router.get("/baselines", response_model=list[BaselinePolicy])
def list_baselines(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[BaselinePolicy]:
    return runtime.list_baselines()


@router.post("/baselines", response_model=BaselinePolicy)
def create_baseline(payload: BaselinePolicyCreate, _: UserRole = Depends(require_role(UserRole.OPERATOR))) -> BaselinePolicy:
    return runtime.create_baseline(payload)


@router.post("/alert-rules", response_model=AlertRule)
def create_alert_rule(payload: AlertRuleCreate, _: UserRole = Depends(require_role(UserRole.OPERATOR))) -> AlertRule:
    return runtime.create_alert_rule(payload)


@router.patch("/alerts/{alert_id}", response_model=AlertRecord)
def update_alert(alert_id: str, payload: AlertStatusUpdate, _: UserRole = Depends(require_role(UserRole.OPERATOR))) -> AlertRecord:
    return runtime.update_alert_status(alert_id, payload)


@router.get("/notifications", response_model=list[NotificationEndpoint])
def list_notification_endpoints(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[NotificationEndpoint]:
    return runtime.list_notification_endpoints()


@router.post("/notifications", response_model=NotificationEndpoint)
def create_notification_endpoint(
    payload: NotificationEndpointCreate,
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> NotificationEndpoint:
    return runtime.create_notification_endpoint(payload)


@router.get("/schedules", response_model=list[ScheduleRecord])
def list_schedules(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> list[ScheduleRecord]:
    return runtime.list_schedules()


@router.post("/schedules", response_model=ScheduleRecord)
def create_schedule(payload: ScheduleCreate, _: UserRole = Depends(require_role(UserRole.OPERATOR))) -> ScheduleRecord:
    return runtime.create_schedule(payload)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRecord)
def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdate,
    _: UserRole = Depends(require_role(UserRole.OPERATOR)),
) -> ScheduleRecord:
    return runtime.update_schedule(schedule_id, payload)


@router.get("/audit", response_model=list[AuditEvent])
def list_audit(_: UserRole = Depends(require_role(UserRole.ADMIN))) -> list[AuditEvent]:
    return runtime.list_audit_events()


@router.get("/exports/runs")
def export_runs(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> JSONResponse:
    runs = [run.model_dump(mode="json") for run in runtime.list_runs(limit=100)]
    return JSONResponse({"export_type": "runs", "count": len(runs), "items": runs})


@router.get("/exports/benchmarks")
def export_benchmarks(_: UserRole = Depends(require_role(UserRole.VIEWER))) -> JSONResponse:
    summary = runtime.dashboard_summary()
    return JSONResponse(
        {
            "export_type": "benchmarks",
            "generated_at": summary.latest_metrics[0].timestamp if summary.latest_metrics else None,
            "average_score": summary.average_score,
            "group_inventory": [group.model_dump(mode="json") for group in summary.group_inventory],
            "recent_runs": [run.model_dump(mode="json") for run in summary.recent_runs],
        }
    )

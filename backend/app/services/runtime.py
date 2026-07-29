from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.celery_app import celery_app
from app.core.config import settings
from app.db import session_scope
from app.db_models import (
    AgentEnrollmentTable,
    AlertRecordTable,
    AlertRuleTable,
    AuditEventTable,
    BaselinePolicyTable,
    CollectorRunTable,
    HardwareComponentMetricTable,
    HardwareComponentTable,
    MetricSnapshotTable,
    NotificationEndpointTable,
    ScheduleTable,
    ServerTable,
    TerminalSessionTable,
    TaskRunEventTable,
    TaskRunTable,
    WorkflowRunTable,
)
from app.models import (
    AdvisoryInsight,
    AgentIdentity,
    AgentEnrollment,
    AgentEnrollmentClaimRequest,
    AgentEnrollmentClaimResponse,
    AgentEnrollmentCreate,
    AgentEnrollmentStatus,
    AgentInstallCommandResponse,
    AgentReleaseManifest,
    AgentTargetOS,
    AgentAuthRequest,
    AlertRecord,
    AlertRule,
    AlertRuleCreate,
    AlertSeverity,
    AlertState,
    AlertStatusUpdate,
    AuditEvent,
    BaselineComparison,
    BaselinePolicy,
    BaselinePolicyCreate,
    FleetComponentSummary,
    FleetMetricHistoryPoint,
    FleetMetricHistorySeries,
    FleetMonitoringCard,
    FleetMonitoringResponse,
    DashboardHistory,
    DashboardSummary,
    BmcIdentity,
    FirmwareIdentity,
    GroupInventorySummary,
    HardwareComponent,
    HardwareInventoryResponse,
    HardwareMetricPoint,
    HardwareMetricSeries,
    HardwareOverviewResponse,
    HardwareReportPayload,
    HealthStatus,
    HeartbeatPayload,
    MetricEnvelope,
    MetricSnapshot,
    NodeDetailResponse,
    NotificationEndpoint,
    NotificationEndpointCreate,
    NetworkIdentity,
    NetworkInterfaceIdentity,
    RegistrationResponse,
    CollectorCapability,
    CollectorStatus,
    HistoryPoint,
    RunDetailResponse,
    RunStatus,
    ScheduleCreate,
    ScheduleRecord,
    ScheduleUpdate,
    ServerRecord,
    ServerRegistration,
    ServerStatus,
    SystemIdentity,
    SoftwareInventory,
    ServerView,
    TerminalAgentCommand,
    TerminalAgentSyncRequest,
    TerminalAgentSyncResponse,
    TerminalFrame,
    TerminalFrameKind,
    TerminalInputRequest,
    TerminalOpenRequest,
    TerminalResizeRequest,
    TerminalSession,
    TerminalSessionStatus,
    TerminalSessionSummary,
    TaskArtifact,
    TaskEvent,
    TaskAssignment,
    TaskDispatchRequest,
    TaskResult,
    TaskRun,
    WorkflowDispatchRequest,
    WorkflowRun,
    utc_now,
)
from app.services.catalog import ALLOWED_TASKS, WORKFLOW_TEMPLATES, list_allowed_tasks, list_workflow_templates
from app.services.artifacts import artifact_storage
from app.services.agent_install import agent_install_service
from app.services.insights import build_node_advisories, build_run_advisories
from app.services.notifications import deliver_alert_notification
from app.services.repositories import repository


def nice_task_name(task_name: str) -> str:
    return task_name.replace("_", " ").strip().title()


class PrometheusRuntime:
    def initialize(self) -> None:
        with session_scope() as session:
            repository.ensure_default_alert_rules(session)
            self._expire_agent_enrollments(session)

    def seed_demo_data(self) -> None:
        with session_scope() as session:
            if session.scalar(select(func.count()).select_from(ServerTable)):
                return

        response = self.register_server(
            ServerRegistration(
                server_name="rack-a100-01",
                server_id="srv-demo-a100",
                api_key="demo-key-a100",
                group="gpu-burnin",
                tags=["demo", "gpu", "rack-a"],
                capabilities=["cpu", "memory", "gpu", "disk", "network", "thermal", "fan", "power", "pcie", "firmware", "system_validation", "workload_test", "baseline"],
            )
        )
        self.record_heartbeat(response.server_id, HeartbeatPayload(api_key=response.api_key, status=ServerStatus.ONLINE))
        self.record_metric(
            response.server_id,
            MetricEnvelope(
                api_key=response.api_key,
                metric={
                    "cpu": 42,
                    "memory": 58,
                    "disk": 61,
                    "network_mbps": 18.4,
                    "temperature_c": 62,
                    "gpu_utilization": 71,
                },
            ),
        )
        workflow = self.dispatch_workflow(
            WorkflowDispatchRequest(server_id=response.server_id, workflow="daily_health_sweep", requested_by="seed")
        )
        self.submit_task_result(
            response.server_id,
            TaskResult(
                api_key=response.api_key,
                task_id=workflow.linked_task_ids[0],
                status=RunStatus.COMPLETED,
                logs=["Validation complete", "No critical deviations found"],
                result={"score": 92.4, "summary": "Ready for scheduled workloads"},
            ),
        )

    def register_server(self, payload: ServerRegistration) -> RegistrationResponse:
        now = utc_now()
        desired_server_id = payload.server_id or self._generate_server_id()
        desired_api_key = payload.api_key or self._generate_api_key()

        with session_scope() as session:
            existing = session.get(ServerTable, desired_server_id)
            if existing and existing.api_key != desired_api_key:
                desired_server_id = self._generate_server_id()
                desired_api_key = self._generate_api_key()
                existing = None

            server = existing or ServerTable(server_id=desired_server_id, api_key=desired_api_key, created_at=now)
            server.server_name = payload.server_name
            server.group = payload.group
            server.tags = payload.tags
            server.capabilities = payload.capabilities
            server.command_capabilities = payload.command_capabilities or server.command_capabilities or {}
            server.status = ServerStatus.ONLINE.value
            server.last_seen = now
            server.last_heartbeat_at = server.last_heartbeat_at or now
            if not existing:
                session.add(server)

            self._audit(session, "agent", "server.registered", server.server_id, {"server_name": payload.server_name, "group": payload.group})

        return RegistrationResponse(server_id=desired_server_id, api_key=desired_api_key, heartbeat_interval_seconds=5)

    def create_agent_enrollment(self, payload: AgentEnrollmentCreate) -> AgentEnrollment:
        with session_scope() as session:
            self._expire_agent_enrollments(session)
            enrollment = repository.create_agent_enrollment(
                session,
                enrollment_id=f"enroll-{secrets.token_hex(5)}",
                connection_code=f"pc-{secrets.token_hex(4)}",
                display_name=payload.display_name,
                group=payload.group,
                tags=payload.tags,
                capabilities=payload.capabilities,
                target_os=payload.target_os.value,
                status=AgentEnrollmentStatus.PENDING.value,
                expires_at=utc_now() + timedelta(minutes=settings.agent_enrollment_expiry_minutes),
                created_by=payload.created_by,
            )
            self._audit(
                session,
                payload.created_by,
                "agent.enrollment_created",
                enrollment.enrollment_id,
                {"display_name": payload.display_name, "target_os": payload.target_os.value},
            )
            return self._agent_enrollment(enrollment)

    def list_agent_enrollments(self, include_completed: bool = True, limit: int = 20) -> list[AgentEnrollment]:
        with session_scope() as session:
            self._expire_agent_enrollments(session)
            rows = repository.list_agent_enrollments(session, include_completed=include_completed, limit=limit)
            return [self._agent_enrollment(row) for row in rows]

    def revoke_agent_enrollment(self, enrollment_id: str, actor: str = "operator") -> AgentEnrollment:
        with session_scope() as session:
            self._expire_agent_enrollments(session)
            enrollment = repository.get_agent_enrollment(session, enrollment_id)
            if not enrollment:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent enrollment not found.")
            repository.update_agent_enrollment_status(session, enrollment, status=AgentEnrollmentStatus.REVOKED.value)
            self._audit(session, actor, "agent.enrollment_revoked", enrollment.enrollment_id, {"connection_code": enrollment.connection_code})
            return self._agent_enrollment(enrollment)

    def claim_agent_enrollment(self, payload: AgentEnrollmentClaimRequest) -> AgentEnrollmentClaimResponse:
        with session_scope() as session:
            self._expire_agent_enrollments(session)
            enrollment = repository.get_agent_enrollment_by_code(session, payload.connection_code)
            if not enrollment:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection code not found.")
            if enrollment.status == AgentEnrollmentStatus.REVOKED.value:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connection code has been revoked.")
            if enrollment.status == AgentEnrollmentStatus.CLAIMED.value:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connection code has already been used.")
            if enrollment.status == AgentEnrollmentStatus.EXPIRED.value or self._as_utc(enrollment.expires_at) < self._as_utc(utc_now()):
                repository.update_agent_enrollment_status(session, enrollment, status=AgentEnrollmentStatus.EXPIRED.value)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connection code has expired.")

            claimed_at = utc_now()
            server_id = self._generate_server_id()
            api_key = self._generate_api_key()
            repository.update_agent_enrollment_status(
                session,
                enrollment,
                status=AgentEnrollmentStatus.CLAIMED.value,
                claimed_server_id=server_id,
                claimed_at=claimed_at,
            )
            self._audit(
                session,
                "agent-bootstrap",
                "agent.enrollment_claimed",
                enrollment.enrollment_id,
                {"server_id": server_id, "target_os": enrollment.target_os},
            )
            return AgentEnrollmentClaimResponse(
                enrollment_id=enrollment.enrollment_id,
                server_id=server_id,
                api_key=api_key,
                server_name=payload.server_name or enrollment.display_name,
                group=enrollment.group,
                tags=sorted(set(enrollment.tags + payload.tags)),
                capabilities=sorted(set(enrollment.capabilities + payload.capabilities)),
                claimed_at=claimed_at,
            )

    def agent_release_manifest(self, public_base_url: str) -> AgentReleaseManifest:
        return agent_install_service.release_manifest(agent_install_service.public_base_url(public_base_url))

    def agent_install_command(self, enrollment_id: str, target_os: AgentTargetOS, public_base_url: str) -> AgentInstallCommandResponse:
        with session_scope() as session:
            self._expire_agent_enrollments(session)
            enrollment = repository.get_agent_enrollment(session, enrollment_id)
            if not enrollment:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent enrollment not found.")
            return agent_install_service.command_response(
                self._agent_enrollment(enrollment),
                target_os,
                agent_install_service.public_base_url(public_base_url),
            )

    def list_terminal_sessions(self, server_id: str | None = None, limit: int = 20) -> list[TerminalSessionSummary]:
        with session_scope() as session:
            statement = select(TerminalSessionTable).order_by(TerminalSessionTable.updated_at.desc()).limit(limit)
            if server_id:
                statement = statement.where(TerminalSessionTable.server_id == server_id)
            rows = session.scalars(statement).all()
            return [self._terminal_session_summary(row) for row in rows]

    def open_terminal_session(self, payload: TerminalOpenRequest, actor: str) -> TerminalSession:
        with session_scope() as session:
            server = session.get(ServerTable, payload.server_id)
            if not server:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")
            terminal_capability = (server.command_capabilities or {}).get("terminal") or {}
            if not terminal_capability.get("supported", False):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Terminal is not supported by this agent.")
            if server.status != ServerStatus.ONLINE.value:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Server is offline.")

            existing = session.scalar(
                select(TerminalSessionTable)
                .where(
                    TerminalSessionTable.server_id == payload.server_id,
                    TerminalSessionTable.status.in_([TerminalSessionStatus.OPEN.value, TerminalSessionStatus.DISCONNECTED.value]),
                )
                .order_by(TerminalSessionTable.updated_at.desc())
                .limit(1)
            )
            if existing:
                existing.last_browser_seen_at = utc_now()
                existing.updated_at = utc_now()
                return self._terminal_session(existing)

            now = utc_now()
            terminal = TerminalSessionTable(
                session_id=f"term-{secrets.token_hex(5)}",
                server_id=payload.server_id,
                opened_by=actor,
                status=TerminalSessionStatus.OPEN.value,
                shell_type=payload.shell_preference,
                terminal_supported=True,
                open_requested=True,
                close_requested=False,
                created_at=now,
                updated_at=now,
                last_browser_seen_at=now,
                recent_output_json=[],
                pending_input_json=[],
                pending_resize_json={"cols": payload.cols, "rows": payload.rows},
                metadata_json={"shell_preference": payload.shell_preference, "cols": payload.cols, "rows": payload.rows},
            )
            session.add(terminal)
            self._append_terminal_frames(
                terminal,
                [TerminalFrame(kind=TerminalFrameKind.STATUS, text="Terminal session requested. Waiting for agent shell.", meta={"actor": actor})],
            )
            self._audit(session, actor, "terminal.opened", terminal.session_id, {"server_id": payload.server_id})
            session.flush()
            return self._terminal_session(terminal)

    def get_terminal_session(self, session_id: str) -> TerminalSession:
        with session_scope() as session:
            terminal = session.get(TerminalSessionTable, session_id)
            if not terminal:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Terminal session not found.")
            return self._terminal_session(terminal)

    def close_terminal_session(self, session_id: str, actor: str) -> TerminalSession:
        with session_scope() as session:
            terminal = session.get(TerminalSessionTable, session_id)
            if not terminal:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Terminal session not found.")
            now = utc_now()
            terminal.close_requested = True
            terminal.status = TerminalSessionStatus.CLOSED.value
            terminal.closed_at = now
            terminal.updated_at = now
            self._append_terminal_frames(
                terminal,
                [TerminalFrame(kind=TerminalFrameKind.CLOSED, text="Terminal session closed from the web console.", meta={"actor": actor})],
            )
            self._audit(session, actor, "terminal.closed", terminal.session_id, {"server_id": terminal.server_id})
            session.flush()
            return self._terminal_session(terminal)

    def touch_terminal_browser(self, session_id: str) -> TerminalSession:
        with session_scope() as session:
            terminal = session.get(TerminalSessionTable, session_id)
            if not terminal:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Terminal session not found.")
            terminal.last_browser_seen_at = utc_now()
            terminal.updated_at = utc_now()
            session.flush()
            return self._terminal_session(terminal)

    def queue_terminal_input(self, session_id: str, payload: TerminalInputRequest, actor: str) -> TerminalSession:
        with session_scope() as session:
            terminal = session.get(TerminalSessionTable, session_id)
            if not terminal:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Terminal session not found.")
            if terminal.status == TerminalSessionStatus.CLOSED.value:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Terminal session is already closed.")
            pending = list(terminal.pending_input_json or [])
            if payload.data:
                pending.append(payload.data)
            terminal.pending_input_json = pending[-120:]
            terminal.last_browser_seen_at = utc_now()
            terminal.updated_at = utc_now()
            self._audit(session, actor, "terminal.input", terminal.session_id, {"server_id": terminal.server_id, "length": len(payload.data)})
            session.flush()
            return self._terminal_session(terminal)

    def resize_terminal_session(self, session_id: str, payload: TerminalResizeRequest, actor: str) -> TerminalSession:
        with session_scope() as session:
            terminal = session.get(TerminalSessionTable, session_id)
            if not terminal:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Terminal session not found.")
            terminal.pending_resize_json = {"cols": payload.cols, "rows": payload.rows}
            terminal.metadata_json = {**(terminal.metadata_json or {}), "cols": payload.cols, "rows": payload.rows}
            terminal.last_browser_seen_at = utc_now()
            terminal.updated_at = utc_now()
            self._append_terminal_frames(
                terminal,
                [TerminalFrame(kind=TerminalFrameKind.RESIZED, cols=payload.cols, rows=payload.rows, meta={"actor": actor})],
            )
            session.flush()
            return self._terminal_session(terminal)

    def sync_terminal_agent(self, server_id: str, payload: TerminalAgentSyncRequest) -> TerminalAgentSyncResponse:
        with session_scope() as session:
            self._validate_agent(session, server_id, payload.api_key)
            for update in payload.sessions:
                terminal = session.get(TerminalSessionTable, update.session_id)
                if not terminal or terminal.server_id != server_id:
                    continue
                terminal.last_agent_seen_at = utc_now()
                terminal.updated_at = utc_now()
                if update.shell_type:
                    terminal.shell_type = update.shell_type
                frames: list[TerminalFrame] = []
                for chunk in update.outputs:
                    if chunk:
                        frames.append(TerminalFrame(kind=TerminalFrameKind.OUTPUT, text=chunk))
                if update.error_message:
                    terminal.status = TerminalSessionStatus.DISCONNECTED.value
                    frames.append(TerminalFrame(kind=TerminalFrameKind.ERROR, text=update.error_message))
                elif update.closed:
                    terminal.status = TerminalSessionStatus.CLOSED.value
                    terminal.closed_at = terminal.closed_at or utc_now()
                    frames.append(TerminalFrame(kind=TerminalFrameKind.CLOSED, text="Remote shell exited."))
                else:
                    terminal.status = TerminalSessionStatus.OPEN.value
                if frames:
                    self._append_terminal_frames(terminal, frames)

            commands: list[TerminalAgentCommand] = []
            terminals = session.scalars(
                select(TerminalSessionTable).where(
                    TerminalSessionTable.server_id == server_id,
                    TerminalSessionTable.status.in_([TerminalSessionStatus.OPEN.value, TerminalSessionStatus.DISCONNECTED.value, TerminalSessionStatus.CLOSED.value]),
                )
            ).all()
            for terminal in terminals:
                shell_preference = (terminal.metadata_json or {}).get("shell_preference")
                if terminal.open_requested and terminal.status != TerminalSessionStatus.CLOSED.value:
                    commands.append(
                        TerminalAgentCommand(
                            session_id=terminal.session_id,
                            action="open",
                            cols=(terminal.pending_resize_json or {}).get("cols"),
                            rows=(terminal.pending_resize_json or {}).get("rows"),
                            shell_type=shell_preference if isinstance(shell_preference, str) else None,
                        )
                    )
                    terminal.open_requested = False
                for chunk in list(terminal.pending_input_json or []):
                    commands.append(TerminalAgentCommand(session_id=terminal.session_id, action="input", data=chunk))
                if terminal.pending_input_json:
                    terminal.pending_input_json = []
                resize = terminal.pending_resize_json or {}
                if resize.get("cols") and resize.get("rows"):
                    commands.append(
                        TerminalAgentCommand(
                            session_id=terminal.session_id,
                            action="resize",
                            cols=int(resize["cols"]),
                            rows=int(resize["rows"]),
                        )
                    )
                    terminal.pending_resize_json = {}
                if terminal.close_requested:
                    commands.append(TerminalAgentCommand(session_id=terminal.session_id, action="close"))
                    terminal.close_requested = False
                terminal.updated_at = utc_now()
            session.flush()
            return TerminalAgentSyncResponse(commands=commands)

    def record_heartbeat(self, server_id: str, payload: HeartbeatPayload) -> ServerRecord:
        with session_scope() as session:
            server = self._validate_agent(session, server_id, payload.api_key)
            server.status = payload.status.value
            now = utc_now()
            server.last_heartbeat_at = now
            server.last_seen = self._merge_server_activity(server)
            self._audit(
                session,
                server_id,
                "server.heartbeat",
                server_id,
                {
                    "status": payload.status.value,
                    "running_tasks": payload.running_tasks,
                    "active_workflow_id": payload.active_workflow_id,
                },
            )
            session.flush()
            return self._server_record(server)

    def record_metric(self, server_id: str, payload: MetricEnvelope) -> MetricSnapshot:
        with session_scope() as session:
            server = self._validate_agent(session, server_id, payload.api_key)
            metric_payload = payload.metric.model_dump()
            snapshot = MetricSnapshotTable(server_id=server_id, **metric_payload)
            session.add(snapshot)
            session.flush()

            server.last_metric_at = utc_now()
            server.last_seen = self._merge_server_activity(server)
            server.status = ServerStatus.ONLINE.value
            server.health = self._derive_health(metric_payload, self._latest_score(session, server_id)).value
            self._evaluate_alerts(session, server_id, metric_payload)
            session.flush()
            return self._metric_snapshot(snapshot)

    def record_hardware_report(self, server_id: str, payload: HardwareReportPayload) -> HardwareOverviewResponse:
        with session_scope() as session:
            server = self._validate_agent(session, server_id, payload.api_key)
            recorded_at = self._as_utc(payload.collected_at)
            component_health: dict[str, dict[str, object]] = {}
            hot_components: list[HardwareComponentTable] = []
            failing_components: list[HardwareComponentTable] = []

            for raw_component in payload.inventory:
                component = repository.upsert_hardware_component(
                    session,
                    component_id=str(raw_component.get("component_id") or f"{server_id}:{raw_component.get('component_type', 'unknown')}:{raw_component.get('name', 'component')}"),
                    server_id=server_id,
                    component_type=str(raw_component.get("component_type") or "unknown"),
                    name=str(raw_component.get("name") or nice_task_name(str(raw_component.get("component_type") or "component"))),
                    slot_or_path=raw_component.get("slot_or_path"),
                    vendor=raw_component.get("vendor"),
                    model=raw_component.get("model"),
                    serial=raw_component.get("serial"),
                    firmware_version=raw_component.get("firmware_version"),
                    status=str(raw_component.get("status") or "healthy"),
                    health=str(raw_component.get("health") or HealthStatus.PASS.value),
                    capabilities=raw_component.get("capabilities") or {},
                    metadata_json=raw_component.get("metadata") or {},
                )
                component_health[component.component_id] = {
                    "component_type": component.component_type,
                    "name": component.name,
                    "health": component.health,
                    "status": component.status,
                }
                if component.health == HealthStatus.FAIL.value:
                    failing_components.append(component)

            for raw_metric in payload.telemetry:
                component_id = str(raw_metric.get("component_id") or "")
                if not component_id:
                    continue
                repository.create_hardware_metric(
                    session,
                    server_id=server_id,
                    component_id=component_id,
                    metric_key=str(raw_metric.get("metric_key") or "unknown"),
                    value=raw_metric.get("value"),
                    unit=raw_metric.get("unit"),
                    status=str(raw_metric.get("status") or "ok"),
                    labels_json=raw_metric.get("labels") or {},
                    recorded_at=self._as_utc(raw_metric.get("recorded_at") or recorded_at),
                )
                metric_key = str(raw_metric.get("metric_key") or "")
                metric_value = raw_metric.get("value")
                if metric_key in {"temperature_c", "gpu.temperature_c", "disk.temperature_c"} and isinstance(metric_value, (int, float)) and metric_value >= 80:
                    component = repository.get_hardware_component(session, component_id)
                    if component is not None and component not in hot_components:
                        hot_components.append(component)

            for collector in payload.collectors:
                repository.record_collector_run(
                    session,
                    collector_run_id=f"collector-{secrets.token_hex(6)}",
                    server_id=server_id,
                    collector_name=collector.collector_name,
                    status=collector.status,
                    message=collector.message,
                    duration_ms=collector.duration_ms,
                    capability_state=collector.capability.state,
                    metrics_emitted=len(collector.telemetry),
                    inventory_items_seen=len(collector.inventory),
                    details={
                        **collector.details,
                        "source": collector.capability.source,
                        "capability_message": collector.capability.message,
                    },
                    recorded_at=recorded_at,
                )

            server.last_telemetry_at = recorded_at
            if payload.inventory:
                server.last_inventory_refresh_at = recorded_at
            server.last_seen = self._merge_server_activity(server)
            server.status = ServerStatus.ONLINE.value
            server.health = self._derive_hardware_health(failing_components, hot_components).value
            session.flush()
            return self._hardware_overview_response(
                server,
                component_health=component_health,
                hot_components=hot_components,
                failing_components=failing_components,
                collector_runs=repository.latest_collector_runs(session, server_id),
            )

    def poll_next_task(self, server_id: str, payload: AgentAuthRequest) -> TaskAssignment | None:
        with session_scope() as session:
            server = self._validate_agent(session, server_id, payload.api_key)
            server.last_task_poll_at = utc_now()
            server.last_seen = self._merge_server_activity(server)
            task_run = session.scalar(
                select(TaskRunTable)
                .where(TaskRunTable.server_id == server_id, TaskRunTable.status == RunStatus.PENDING.value)
                .order_by(TaskRunTable.created_at.asc())
                .limit(1)
            )
            if not task_run:
                return None

            now = utc_now()
            task_run.status = RunStatus.RUNNING.value
            task_run.updated_at = now
            task_run.started_at = task_run.started_at or now
            task_run.attempt_count += 1
            task_run.worker_id = server_id
            task_run.error_message = None
            self._record_task_event(
                session,
                task_id=task_run.task_id,
                event_type="task.started",
                status=RunStatus.RUNNING.value,
                summary=f"{nice_task_name(task_run.task)} started on {server_id}.",
                details={"server_id": server_id, "attempt_count": task_run.attempt_count, "worker_id": server_id},
            )

            if task_run.workflow_id:
                workflow = session.get(WorkflowRunTable, task_run.workflow_id)
                if workflow:
                    workflow.status = RunStatus.RUNNING.value
                    workflow.updated_at = now
                    workflow.finished_at = None

            session.flush()
            return TaskAssignment(
                task_id=task_run.task_id,
                task=task_run.task,
                params=task_run.params,
                queued_at=task_run.created_at,
                workflow_id=task_run.workflow_id,
                attempt_count=task_run.attempt_count,
                worker_id=task_run.worker_id,
            )

    def submit_task_result(self, server_id: str, payload: TaskResult) -> TaskRun:
        workflow_id: str | None = None
        with session_scope() as session:
            server = self._validate_agent(session, server_id, payload.api_key)
            task_run = session.get(TaskRunTable, payload.task_id)
            if not task_run or task_run.server_id != server_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task run not found.")
            if task_run.status in {RunStatus.CANCELLED.value, RunStatus.COMPLETED.value}:
                return self._task_run(task_run)

            now = utc_now()
            server.last_task_result_at = now
            server.last_seen = self._merge_server_activity(server)
            task_run.status = payload.status.value
            task_run.logs = payload.logs
            task_run.result = payload.result
            task_run.score = payload.result.get("score")
            task_run.updated_at = now
            task_run.finished_at = now
            task_run.error_message = payload.result.get("error_message")
            self._record_task_event(
                session,
                task_id=task_run.task_id,
                event_type="task.result_received",
                status=payload.status.value,
                summary=f"Agent reported {payload.status.value} for {nice_task_name(task_run.task)}.",
                details={
                    "server_id": server_id,
                    "log_count": len(payload.logs),
                    "has_error": bool(payload.result.get("error_message")),
                    "score": payload.result.get("score"),
                },
            )
            existing_artifacts = repository.delete_task_artifacts(session, task_run.task_id)
            artifact_storage.reset_task_directory(task_run.task_id, [artifact.file_path for artifact in existing_artifacts])
            stored_artifacts = artifact_storage.persist_result_artifacts(task_run.task_id, payload.result)
            for artifact in stored_artifacts:
                repository.create_task_artifact(
                    session,
                    artifact_id=artifact.artifact_id,
                    task_id=task_run.task_id,
                    label=artifact.label,
                    artifact_type=artifact.artifact_type,
                    content_type=artifact.content_type,
                    file_path=artifact.file_path,
                    size_bytes=artifact.size_bytes,
                    metadata_json=artifact.metadata,
                )
            if stored_artifacts:
                self._record_task_event(
                    session,
                    task_id=task_run.task_id,
                    event_type="task.artifacts_persisted",
                    status=payload.status.value,
                    summary=f"Stored {len(stored_artifacts)} execution artifact(s).",
                    details={"count": len(stored_artifacts), "labels": [artifact.label for artifact in stored_artifacts]},
                )
            retryable = payload.status == RunStatus.FAILED and self._should_retry_task(task_run, payload.result)
            if retryable:
                self._requeue_task_run(
                    session,
                    task_run,
                    reason=payload.result.get("error_message") or "Agent marked the task as retryable.",
                    actor=server_id,
                    audit_action="task.retry_queued",
                )
            else:
                self._audit(session, server_id, "task.completed", payload.task_id, {"status": payload.status.value, "score": task_run.score})
                self._record_task_event(
                    session,
                    task_id=task_run.task_id,
                    event_type=f"task.{payload.status.value}",
                    status=payload.status.value,
                    summary=self._task_terminal_summary(task_run.task, payload.status.value, task_run.score, task_run.error_message),
                    details={
                        "server_id": server_id,
                        "score": task_run.score,
                        "error_message": task_run.error_message,
                        "artifact_count": len(stored_artifacts),
                    },
                )
            if task_run.workflow_id:
                self._refresh_workflow_state(session, task_run.workflow_id)
                workflow_id = task_run.workflow_id
            session.flush()
            result = self._task_run(task_run)
        if workflow_id:
            queue_runtime_job("app.jobs.refresh_workflow", workflow_id)
        return result

    def dispatch_task(self, payload: TaskDispatchRequest) -> TaskRun:
        if payload.task not in ALLOWED_TASKS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task is not whitelisted.")

        with session_scope() as session:
            self._require_server(session, payload.server_id)
            task_run = TaskRunTable(
                task_id=self._generate_task_id(),
                server_id=payload.server_id,
                task=payload.task,
                params=payload.params,
                requested_by=payload.requested_by,
            )
            session.add(task_run)
            self._audit(session, payload.requested_by, "task.queued", task_run.task_id, {"server_id": payload.server_id, "task": payload.task})
            self._record_task_event(
                session,
                task_id=task_run.task_id,
                event_type="task.queued",
                status=RunStatus.PENDING.value,
                summary=f"{nice_task_name(payload.task)} queued for {payload.server_id}.",
                details={"server_id": payload.server_id, "requested_by": payload.requested_by, "params": payload.params},
            )
            session.flush()
            result = self._task_run(task_run)
        queue_runtime_job("app.jobs.reconcile_runtime")
        return result

    def dispatch_workflow(self, payload: WorkflowDispatchRequest) -> WorkflowRun:
        template = WORKFLOW_TEMPLATES.get(payload.workflow)
        if not template:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow template not found.")

        with session_scope() as session:
            self._require_server(session, payload.server_id)
            workflow = WorkflowRunTable(
                workflow_id=self._generate_workflow_id(),
                server_id=payload.server_id,
                workflow=payload.workflow,
                steps=template.steps,
                requested_by=payload.requested_by,
                params=payload.params,
            )
            session.add(workflow)
            session.flush()

            linked_task_ids: list[str] = []
            for step in template.steps:
                task_id = self._generate_task_id()
                linked_task_ids.append(task_id)
                session.add(
                    TaskRunTable(
                        task_id=task_id,
                        server_id=payload.server_id,
                        task=step,
                        params=payload.params,
                        requested_by=payload.requested_by,
                        workflow_id=workflow.workflow_id,
                    )
                )
                self._record_task_event(
                    session,
                    task_id=task_id,
                    event_type="task.queued",
                    status=RunStatus.PENDING.value,
                    summary=f"{nice_task_name(step)} queued as part of workflow {payload.workflow}.",
                    details={
                        "server_id": payload.server_id,
                        "requested_by": payload.requested_by,
                        "workflow_id": workflow.workflow_id,
                        "workflow": payload.workflow,
                    },
                )

            workflow.linked_task_ids = linked_task_ids
            workflow.updated_at = utc_now()
            self._audit(session, payload.requested_by, "workflow.queued", workflow.workflow_id, {"server_id": payload.server_id, "workflow": payload.workflow})
            session.flush()
            result = self._workflow_run(workflow)
        queue_runtime_job("app.jobs.reconcile_runtime")
        return result

    def retry_task(self, task_id: str, actor: str = "operator") -> TaskRun:
        with session_scope() as session:
            task_run = session.get(TaskRunTable, task_id)
            if not task_run:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task run not found.")
            if task_run.status == RunStatus.RUNNING.value:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Running tasks cannot be retried.")
            if task_run.status == RunStatus.PENDING.value:
                return self._task_run(task_run)
            self._requeue_task_run(session, task_run, reason="Manual retry requested by operator.", actor=actor, audit_action="task.retry_requested")
            if task_run.workflow_id:
                self._refresh_workflow_state(session, task_run.workflow_id)
            session.flush()
            result = self._task_run(task_run)
        queue_runtime_job("app.jobs.reconcile_runtime")
        return result

    def cancel_task(self, task_id: str, actor: str = "operator") -> TaskRun:
        workflow_id: str | None = None
        with session_scope() as session:
            task_run = session.get(TaskRunTable, task_id)
            if not task_run:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task run not found.")
            if task_run.status in {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
                return self._task_run(task_run)
            now = utc_now()
            task_run.status = RunStatus.CANCELLED.value
            task_run.updated_at = now
            task_run.finished_at = now
            task_run.error_message = "Cancelled by operator."
            self._audit(session, actor, "task.cancelled", task_run.task_id, {"server_id": task_run.server_id})
            self._record_task_event(
                session,
                task_id=task_run.task_id,
                event_type="task.cancelled",
                status=RunStatus.CANCELLED.value,
                summary=f"{nice_task_name(task_run.task)} was cancelled.",
                details={"server_id": task_run.server_id, "actor": actor},
            )
            if task_run.workflow_id:
                self._refresh_workflow_state(session, task_run.workflow_id)
                workflow_id = task_run.workflow_id
            session.flush()
            result = self._task_run(task_run)
        if workflow_id:
            queue_runtime_job("app.jobs.refresh_workflow", workflow_id)
        return result

    def cancel_workflow(self, workflow_id: str, actor: str = "operator") -> WorkflowRun:
        with session_scope() as session:
            workflow = session.get(WorkflowRunTable, workflow_id)
            if not workflow:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found.")
            if workflow.status in {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
                return self._workflow_run(workflow)
            now = utc_now()
            linked_tasks = session.scalars(
                select(TaskRunTable).where(TaskRunTable.task_id.in_(workflow.linked_task_ids))
            ).all()
            for task_run in linked_tasks:
                if task_run.status in {RunStatus.PENDING.value, RunStatus.RUNNING.value}:
                    task_run.status = RunStatus.CANCELLED.value
                    task_run.updated_at = now
                    task_run.finished_at = now
                    task_run.error_message = "Cancelled as part of workflow cancellation."
            workflow.status = RunStatus.CANCELLED.value
            workflow.updated_at = now
            workflow.finished_at = now
            self._audit(session, actor, "workflow.cancelled", workflow.workflow_id, {"server_id": workflow.server_id})
            session.flush()
            return self._workflow_run(workflow)

    def list_servers(self) -> list[ServerRecord]:
        with session_scope() as session:
            self._reconcile_server_statuses(session)
            servers = session.scalars(select(ServerTable).order_by(func.lower(ServerTable.server_name))).all()
            return [self._server_record(server, self._server_summary_for_server(session, server.server_id)) for server in servers]

    def list_runs(self, limit: int = 20) -> list[TaskRun]:
        with session_scope() as session:
            runs = session.scalars(select(TaskRunTable).order_by(TaskRunTable.created_at.desc()).limit(limit)).all()
            return [self._task_run(run) for run in runs]

    def get_run_detail(self, task_id: str) -> RunDetailResponse:
        with session_scope() as session:
            task_run = session.get(TaskRunTable, task_id)
            if not task_run:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task run not found.")
            server = session.get(ServerTable, task_run.server_id)
            workflow = session.get(WorkflowRunTable, task_run.workflow_id) if task_run.workflow_id else None
            artifacts = repository.list_task_artifacts(session, task_run.task_id)
            timeline = repository.list_task_events(session, task_run.task_id)
            previous_run = repository.previous_completed_run(session, task_run.task_id, task_run.server_id, task_run.task)
            previous_score = previous_run.score if previous_run else None
            baseline = self._baseline_policy_for_run(session, task_run.server_id, task_run.task)
            return RunDetailResponse(
                run=self._task_run(task_run),
                server=self._server_view(server) if server else None,
                workflow=self._workflow_run(workflow) if workflow else None,
                advisories=build_run_advisories(self._task_run(task_run), previous_score),
                regression=(
                    {
                        "previous_task_id": previous_run.task_id,
                        "previous_score": previous_run.score,
                        "score_delta": round((task_run.score or 0) - (previous_run.score or 0), 2),
                    }
                    if previous_run and task_run.score is not None and previous_run.score is not None
                    else {}
                ),
                baseline_comparison=self._baseline_comparison(task_run, baseline),
                artifacts=[self._task_artifact(artifact) for artifact in artifacts],
                timeline=[self._task_event(event) for event in timeline],
            )

    def get_run_artifact(self, task_id: str, artifact_id: str) -> tuple[TaskArtifact, str]:
        with session_scope() as session:
            artifact = repository.get_task_artifact(session, task_id, artifact_id)
            if not artifact:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
            return self._task_artifact(artifact), artifact.file_path

    def list_workflows(self, limit: int = 10) -> list[WorkflowRun]:
        with session_scope() as session:
            workflows = session.scalars(select(WorkflowRunTable).order_by(WorkflowRunTable.created_at.desc()).limit(limit)).all()
            return [self._workflow_run(workflow) for workflow in workflows]

    def list_audit_events(self, limit: int = 30) -> list[AuditEvent]:
        with session_scope() as session:
            events = session.scalars(select(AuditEventTable).order_by(AuditEventTable.timestamp.desc()).limit(limit)).all()
            return [self._audit_event(event) for event in events]

    def get_node_detail(self, server_id: str) -> NodeDetailResponse:
        with session_scope() as session:
            self._reconcile_server_statuses(session)
            server = session.get(ServerTable, server_id)
            if not server:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")
            metric = repository.latest_metric_for_server(session, server_id)
            runs = repository.recent_runs_for_server(session, server_id, limit=6)
            alerts = repository.list_alerts_for_server(session, server_id, limit=6)
            run_models = [self._task_run(run) for run in runs]
            metric_model = self._metric_snapshot(metric) if metric else None
            components = repository.list_hardware_components(session, server_id)
            collector_runs = repository.latest_collector_runs(session, server_id)
            identities = self._identity_groups_from_components(server, components)
            return NodeDetailResponse(
                server=self._server_view(server, self._server_summary(server, identities)),
                latest_metric=metric_model,
                recent_runs=run_models,
                alerts=[self._alert_record(alert) for alert in alerts],
                advisories=build_node_advisories(metric_model, run_models),
                hardware_overview=self._hardware_overview_dict(session, server, components, collector_runs),
                hardware_inventory=[self._hardware_component(component) for component in components],
                collector_statuses=[self._collector_status(run) for run in collector_runs],
                system_identity=identities["system_identity"],
                firmware_identity=identities["firmware_identity"],
                bmc_identity=identities["bmc_identity"],
                agent_identity=identities["agent_identity"],
                network_identity=identities["network_identity"],
                software_inventory=identities["software_inventory"],
                platform_addresses=identities["platform_addresses"],
            )

    def get_hardware_inventory(self, server_id: str) -> HardwareInventoryResponse:
        with session_scope() as session:
            self._reconcile_server_statuses(session)
            server = session.get(ServerTable, server_id)
            if not server:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")
            components = repository.list_hardware_components(session, server_id)
            collector_runs = repository.latest_collector_runs(session, server_id)
            return HardwareInventoryResponse(
                server=self._server_view(server),
                components=[self._hardware_component(component) for component in components],
                collector_statuses=[self._collector_status(run) for run in collector_runs],
            )

    def get_hardware_overview(self, server_id: str) -> HardwareOverviewResponse:
        with session_scope() as session:
            self._reconcile_server_statuses(session)
            server = session.get(ServerTable, server_id)
            if not server:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")
            components = repository.list_hardware_components(session, server_id)
            collector_runs = repository.latest_collector_runs(session, server_id)
            component_health = {
                component.component_id: {
                    "component_type": component.component_type,
                    "name": component.name,
                    "health": component.health,
                    "status": component.status,
                }
                for component in components
            }
            hot_components = [component for component in components if component.health != HealthStatus.FAIL.value and self._component_is_hot(session, component)]
            failing_components = [component for component in components if component.health == HealthStatus.FAIL.value]
            return self._hardware_overview_response(
                server,
                component_health=component_health,
                hot_components=hot_components,
                failing_components=failing_components,
                collector_runs=collector_runs,
            )

    def get_fleet_monitoring(self) -> FleetMonitoringResponse:
        with session_scope() as session:
            self._reconcile_server_statuses(session)
            servers = session.scalars(select(ServerTable).order_by(func.lower(ServerTable.server_name))).all()
            alerts = repository.list_alerts(session, limit=200)
            latest_metrics = {metric.server_id: metric for metric in self._latest_metrics(session)}
            components = session.scalars(select(HardwareComponentTable)).all()
            metric_rows = session.scalars(
                select(HardwareComponentMetricTable).order_by(HardwareComponentMetricTable.recorded_at.desc()).limit(4000)
            ).all()

            components_by_server: dict[str, list[HardwareComponentTable]] = {}
            for component in components:
                components_by_server.setdefault(component.server_id, []).append(component)

            latest_metric_rows: dict[tuple[str, str], HardwareComponentMetricTable] = {}
            for row in metric_rows:
                latest_metric_rows.setdefault((row.server_id, row.metric_key), row)

            collector_runs_by_server = {
                server.server_id: repository.latest_collector_runs(session, server.server_id)
                for server in servers
            }

            cards: list[FleetMonitoringCard] = []
            hot_components: list[HardwareComponentTable] = []
            failing_components: list[HardwareComponentTable] = []
            fleet_online = 0

            for server in servers:
                server_components = components_by_server.get(server.server_id, [])
                collector_runs = collector_runs_by_server.get(server.server_id, [])
                identities = self._identity_groups_from_components(server, server_components) if server_components else None
                summary = self._server_summary(server, identities)
                server_hot = [component for component in server_components if component.health != HealthStatus.FAIL.value and self._component_is_hot(session, component)]
                server_failing = [component for component in server_components if component.health == HealthStatus.FAIL.value]
                hot_components.extend(component for component in server_hot if component not in hot_components)
                failing_components.extend(component for component in server_failing if component not in failing_components)
                if server.status == ServerStatus.ONLINE.value:
                    fleet_online += 1
                cards.append(
                    FleetMonitoringCard(
                        server=self._server_view(server, summary),
                        latest_metric=self._metric_snapshot(latest_metrics[server.server_id]) if server.server_id in latest_metrics else None,
                        overall_health=self._derive_hardware_health(server_failing, server_hot),
                        hot_component_count=len(server_hot),
                        failing_component_count=len(server_failing),
                        collector_issue_count=sum(1 for run in collector_runs if run.status not in {"ok", "healthy"}),
                        fan_speed_rpm=self._latest_numeric_metric(latest_metric_rows, server.server_id, "fan.speed_rpm"),
                        component_counts=self._component_count_map(server_components),
                    )
                )

            return FleetMonitoringResponse(
                generated_at=utc_now(),
                fleet_online=fleet_online,
                fleet_total=len(servers),
                active_alerts=sum(1 for alert in alerts if alert.state != AlertState.RESOLVED.value),
                reporting_servers=sum(1 for server in servers if server.last_telemetry_at is not None),
                hot_components=[self._hardware_component(component) for component in hot_components[:8]],
                failing_components=[self._hardware_component(component) for component in failing_components[:8]],
                collector_issues=[
                    self._collector_status(run)
                    for runs in collector_runs_by_server.values()
                    for run in runs
                    if run.status not in {"ok", "healthy"}
                ][:12],
                cards=cards,
                component_summaries=self._fleet_component_summaries(servers, components, latest_metric_rows),
                histories=self._fleet_metric_histories(metric_rows),
            )

    def get_component_metric_series(self, component_id: str, metric_key: str | None = None, limit: int = 120) -> HardwareMetricSeries:
        with session_scope() as session:
            component = repository.get_hardware_component(session, component_id)
            if not component:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware component not found.")
            metrics = repository.list_component_metrics(session, component_id, metric_key=metric_key, limit=limit)
            series_key = metric_key or (metrics[0].metric_key if metrics else "unknown")
            unit = metrics[0].unit if metrics else None
            return HardwareMetricSeries(
                component_id=component_id,
                metric_key=series_key,
                unit=unit,
                points=[self._hardware_metric_point(row) for row in metrics if metric_key is None or row.metric_key == metric_key],
            )

    def list_alert_rules(self) -> list[AlertRule]:
        with session_scope() as session:
            return [self._alert_rule(rule) for rule in repository.list_alert_rules(session)]

    def list_baselines(self) -> list[BaselinePolicy]:
        with session_scope() as session:
            return [self._baseline_policy(row) for row in repository.list_baselines(session)]

    def create_baseline(self, payload: BaselinePolicyCreate) -> BaselinePolicy:
        with session_scope() as session:
            baseline = repository.create_baseline(
                session,
                name=payload.name,
                group=payload.group,
                task=payload.task,
                minimum_score=payload.minimum_score,
                max_temperature_c=payload.max_temperature_c,
                min_throughput=payload.min_throughput,
            )
            self._audit(session, "operator", "baseline.created", baseline.baseline_id, {"group": payload.group, "task": payload.task})
            return self._baseline_policy(baseline)

    def create_alert_rule(self, payload: AlertRuleCreate) -> AlertRule:
        with session_scope() as session:
            rule = AlertRuleTable(
                rule_id=f"rule-{secrets.token_hex(5)}",
                name=payload.name,
                signal=payload.signal,
                threshold=payload.threshold,
                severity=payload.severity.value,
                enabled=payload.enabled,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(rule)
            self._audit(session, "operator", "alert_rule.created", rule.rule_id, {"signal": payload.signal, "threshold": payload.threshold})
            session.flush()
            return self._alert_rule(rule)

    def list_alerts(self, limit: int = 20, state: str | None = None) -> list[AlertRecord]:
        with session_scope() as session:
            return [self._alert_record(alert) for alert in repository.list_alerts(session, limit=limit, state=state)]

    def update_alert_status(self, alert_id: str, payload: AlertStatusUpdate) -> AlertRecord:
        with session_scope() as session:
            alert = repository.update_alert_status(session, alert_id, payload)
            if not alert:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
            self._audit(session, "operator", "alert.updated", alert.alert_id, {"state": payload.state.value})
            return self._alert_record(alert)

    def list_notification_endpoints(self) -> list[NotificationEndpoint]:
        with session_scope() as session:
            return [self._notification_endpoint(item) for item in repository.list_notification_endpoints(session)]

    def create_notification_endpoint(self, payload: NotificationEndpointCreate) -> NotificationEndpoint:
        with session_scope() as session:
            endpoint = repository.create_notification_endpoint(
                session,
                name=payload.name,
                channel=payload.channel.value,
                target=payload.target,
                enabled=payload.enabled,
            )
            self._audit(session, "operator", "notification_endpoint.created", endpoint.endpoint_id, {"channel": endpoint.channel})
            return self._notification_endpoint(endpoint)

    def list_schedules(self) -> list[ScheduleRecord]:
        with session_scope() as session:
            return [self._schedule_record(schedule) for schedule in repository.list_schedules(session)]

    def create_schedule(self, payload: ScheduleCreate) -> ScheduleRecord:
        if payload.workflow not in WORKFLOW_TEMPLATES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow template not found.")
        with session_scope() as session:
            self._require_server(session, payload.server_id)
            schedule = repository.create_schedule(session, payload)
            self._audit(session, payload.created_by, "schedule.created", schedule.schedule_id, {"workflow": payload.workflow, "server_id": payload.server_id})
            result = self._schedule_record(schedule)
        queue_runtime_job("app.jobs.process_due_schedules")
        return result

    def update_schedule(self, schedule_id: str, payload: ScheduleUpdate) -> ScheduleRecord:
        with session_scope() as session:
            schedule = repository.update_schedule(session, schedule_id, payload)
            if not schedule:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
            self._audit(session, "operator", "schedule.updated", schedule.schedule_id, {"active": schedule.active, "interval_minutes": schedule.interval_minutes})
            return self._schedule_record(schedule)

    def process_due_schedules(self) -> int:
        with session_scope() as session:
            before = repository.due_schedules(session)
            self._process_due_schedules(session)
            return len(before)

    def reconcile_runtime(self) -> int:
        with session_scope() as session:
            self._reconcile_server_statuses(session)
            timed_out = self._reconcile_stale_running_tasks(session)
            return timed_out

    def refresh_workflow(self, workflow_id: str) -> None:
        with session_scope() as session:
            self._refresh_workflow_state(session, workflow_id)

    def dashboard_summary(self) -> DashboardSummary:
        with session_scope() as session:
            self._reconcile_server_statuses(session)
            server_rows = session.scalars(select(ServerTable).order_by(func.lower(ServerTable.server_name))).all()
            latest_metrics = self._latest_metrics(session)
            completed_scores = session.scalars(select(TaskRunTable.score).where(TaskRunTable.score.is_not(None))).all()
            active_runs = session.scalar(select(func.count()).select_from(TaskRunTable).where(TaskRunTable.status == RunStatus.RUNNING.value)) or 0
            alerts = repository.list_alerts(session, limit=6)
            fleet_online = sum(1 for server in server_rows if server.status == ServerStatus.ONLINE.value)

            return DashboardSummary(
                fleet_online=fleet_online,
                fleet_total=len(server_rows),
                active_runs=active_runs,
                alerts=len(alerts),
                average_score=round(sum(completed_scores) / len(completed_scores), 2) if completed_scores else 0,
                servers=[self._server_view(server, self._server_summary_for_server(session, server.server_id)) for server in server_rows],
                recent_runs=[self._task_run(run) for run in session.scalars(select(TaskRunTable).order_by(TaskRunTable.created_at.desc()).limit(8)).all()],
                workflows=[self._workflow_run(workflow) for workflow in session.scalars(select(WorkflowRunTable).order_by(WorkflowRunTable.created_at.desc()).limit(5)).all()],
                latest_metrics=sorted([self._metric_snapshot(metric) for metric in latest_metrics], key=lambda item: item.timestamp, reverse=True),
                recent_alerts=[self._alert_record(alert) for alert in alerts],
                group_inventory=self._group_inventory_summary(session, server_rows),
                allowed_tasks=list_allowed_tasks(),
                workflow_templates=list_workflow_templates(),
            )

    def dashboard_history(self, period: str = "month") -> DashboardHistory:
        with session_scope() as session:
            now = self._as_utc(utc_now())
            normalized_period = period.lower()
            bucket_specs = self._history_bucket_specs(now, normalized_period)
            history_start = bucket_specs[0][1]
            task_runs = session.scalars(select(TaskRunTable).where(TaskRunTable.created_at >= history_start)).all()

            points: list[HistoryPoint] = []
            for label, bucket_start, bucket_end in bucket_specs:
                bucket_runs = [run for run in task_runs if bucket_start <= self._as_utc(run.created_at) < bucket_end]
                completed_runs = [run for run in bucket_runs if run.status == RunStatus.COMPLETED.value]
                scores = [run.score for run in completed_runs if run.score is not None]
                average_score = round(sum(scores) / len(scores), 2) if scores else 0
                points.append(
                    HistoryPoint(
                        label=label,
                        value=average_score,
                        amount=len(completed_runs),
                        total_runs=len(bucket_runs),
                        completed_runs=len(completed_runs),
                    )
                )

            return DashboardHistory(period=normalized_period, points=points)

    def _refresh_workflow_state(self, session, workflow_id: str) -> None:
        workflow = session.get(WorkflowRunTable, workflow_id)
        if not workflow:
            return
        if workflow.status == RunStatus.CANCELLED.value:
            return

        linked_tasks = session.scalars(
            select(TaskRunTable).where(TaskRunTable.task_id.in_(workflow.linked_task_ids)).order_by(TaskRunTable.created_at.asc())
        ).all()
        now = utc_now()
        workflow.updated_at = now

        for index, task in enumerate(linked_tasks):
            if task.status in {RunStatus.PENDING.value, RunStatus.RUNNING.value}:
                workflow.current_step_index = index
                break
        else:
            workflow.current_step_index = max(len(linked_tasks) - 1, 0)

        statuses = {task.status for task in linked_tasks}
        if RunStatus.CANCELLED.value in statuses:
            workflow.status = RunStatus.CANCELLED.value
            workflow.finished_at = now
        elif RunStatus.FAILED.value in statuses:
            workflow.status = RunStatus.FAILED.value
            workflow.finished_at = now
        elif linked_tasks and all(task.status == RunStatus.COMPLETED.value for task in linked_tasks):
            workflow.status = RunStatus.COMPLETED.value
            workflow.finished_at = now
        elif RunStatus.RUNNING.value in statuses or RunStatus.COMPLETED.value in statuses:
            workflow.status = RunStatus.RUNNING.value
            workflow.finished_at = None
        else:
            workflow.status = RunStatus.PENDING.value
            workflow.finished_at = None

    @staticmethod
    def _start_of_day(value: datetime) -> datetime:
        return value.replace(hour=0, minute=0, second=0, microsecond=0)

    def _history_bucket_specs(self, now: datetime, period: str) -> list[tuple[str, datetime, datetime]]:
        if period == "week":
            start = self._start_of_day(now) - timedelta(days=6)
            return [
                ((start + timedelta(days=index)).strftime("%a"), start + timedelta(days=index), start + timedelta(days=index + 1))
                for index in range(7)
            ]

        if period == "month":
            current_week_start = self._start_of_day(now) - timedelta(days=now.weekday())
            first_week_start = current_week_start - timedelta(weeks=5)
            return [
                (
                    f"{(first_week_start + timedelta(weeks=index)).strftime('%d %b')}",
                    first_week_start + timedelta(weeks=index),
                    first_week_start + timedelta(weeks=index + 1),
                )
                for index in range(6)
            ]

        current_month_start = self._start_of_day(now).replace(day=1)
        bucket_starts: list[datetime] = []
        cursor = current_month_start
        for _ in range(12):
            bucket_starts.append(cursor)
            if cursor.month == 1:
                cursor = cursor.replace(year=cursor.year - 1, month=12)
            else:
                cursor = cursor.replace(month=cursor.month - 1)
        bucket_starts.reverse()

        bucket_specs: list[tuple[str, datetime, datetime]] = []
        for index, bucket_start in enumerate(bucket_starts):
            if index + 1 < len(bucket_starts):
                bucket_end = bucket_starts[index + 1]
            else:
                if bucket_start.month == 12:
                    bucket_end = bucket_start.replace(year=bucket_start.year + 1, month=1)
                else:
                    bucket_end = bucket_start.replace(month=bucket_start.month + 1)
            bucket_specs.append((bucket_start.strftime("%b"), bucket_start, bucket_end))
        return bucket_specs

    def _process_due_schedules(self, session) -> None:
        due_schedules = repository.due_schedules(session)
        for schedule in due_schedules:
            template = WORKFLOW_TEMPLATES.get(schedule.workflow)
            if not template:
                continue
            workflow = WorkflowRunTable(
                workflow_id=self._generate_workflow_id(),
                server_id=schedule.server_id,
                workflow=schedule.workflow,
                steps=template.steps,
                requested_by=f"schedule:{schedule.schedule_id}",
                params=schedule.params,
            )
            session.add(workflow)
            session.flush()
            linked_task_ids: list[str] = []
            for step in template.steps:
                task_id = self._generate_task_id()
                linked_task_ids.append(task_id)
                session.add(
                    TaskRunTable(
                        task_id=task_id,
                        server_id=schedule.server_id,
                        task=step,
                        params=schedule.params,
                        requested_by=f"schedule:{schedule.schedule_id}",
                        workflow_id=workflow.workflow_id,
                    )
                )
                self._record_task_event(
                    session,
                    task_id=task_id,
                    event_type="task.queued",
                    status=RunStatus.PENDING.value,
                    summary=f"{nice_task_name(step)} queued from schedule {schedule.name}.",
                    details={
                        "server_id": schedule.server_id,
                        "requested_by": f"schedule:{schedule.schedule_id}",
                        "workflow_id": workflow.workflow_id,
                        "schedule_id": schedule.schedule_id,
                    },
                )
            workflow.linked_task_ids = linked_task_ids
            repository.advance_schedule(session, schedule)
            self._audit(session, schedule.created_by, "schedule.dispatched", schedule.schedule_id, {"workflow_id": workflow.workflow_id})

    def _evaluate_alerts(self, session, server_id: str, metric_payload: dict) -> None:
        rules = repository.list_alert_rules(session)
        active_signals: set[str] = set()
        for rule in rules:
            if not rule.enabled:
                continue
            value = metric_payload.get(rule.signal)
            if value is None or value < rule.threshold:
                repository.resolve_open_alerts_for_signal(session, server_id, rule.signal)
                continue
            active_signals.add(rule.signal)
            existing = repository.get_open_alert(session, server_id, rule.signal, rule.rule_id)
            message = f"{rule.signal.replace('_', ' ').title()} reached {value}, above threshold {rule.threshold}."
            if existing:
                existing.value = value
                existing.message = message
                existing.updated_at = utc_now()
                continue
            alert = repository.create_alert(
                session,
                server_id=server_id,
                signal=rule.signal,
                severity=rule.severity,
                value=value,
                message=message,
                rule_id=rule.rule_id,
            )
            self._audit(session, "system", "alert.created", alert.alert_id, {"server_id": server_id, "signal": rule.signal, "severity": rule.severity})
            self._notify_alert(session, self._alert_record(alert))

        for signal in ("cpu", "memory", "disk", "temperature_c"):
            if signal not in active_signals and metric_payload.get(signal) is not None:
                repository.resolve_open_alerts_for_signal(session, server_id, signal)

    def _expire_agent_enrollments(self, session) -> None:
        now = self._as_utc(utc_now())
        for enrollment in repository.list_agent_enrollments(session, include_completed=True, limit=200):
            if enrollment.status == AgentEnrollmentStatus.PENDING.value and self._as_utc(enrollment.expires_at) < now:
                repository.update_agent_enrollment_status(session, enrollment, status=AgentEnrollmentStatus.EXPIRED.value)

    def _reconcile_server_statuses(self, session) -> None:
        now = utc_now()
        for server in session.scalars(select(ServerTable)).all():
            heartbeat_reference = server.last_heartbeat_at or server.last_seen
            if now - self._as_utc(heartbeat_reference) > timedelta(seconds=settings.heartbeat_timeout_seconds):
                server.status = ServerStatus.OFFLINE.value

    def _reconcile_stale_running_tasks(self, session) -> int:
        now = utc_now()
        stale_runs = session.scalars(
            select(TaskRunTable).where(
                TaskRunTable.status == RunStatus.RUNNING.value,
            )
        ).all()
        for task_run in stale_runs:
            if now - self._as_utc(task_run.updated_at) <= timedelta(seconds=settings.task_stale_timeout_seconds):
                continue
            timed_out_message = "Task timed out while waiting for agent completion."
            if self._should_retry_task(task_run):
                self._requeue_task_run(
                    session,
                    task_run,
                    reason=timed_out_message,
                    actor="system",
                    audit_action="task.retry_queued",
                )
            else:
                task_run.status = RunStatus.FAILED.value
                task_run.finished_at = now
                task_run.updated_at = now
                task_run.error_message = timed_out_message
                self._audit(session, "system", "task.timeout", task_run.task_id, {"server_id": task_run.server_id})
                self._record_task_event(
                    session,
                    task_id=task_run.task_id,
                    event_type="task.timeout",
                    status=RunStatus.FAILED.value,
                    summary=f"{nice_task_name(task_run.task)} timed out waiting for agent completion.",
                    details={"server_id": task_run.server_id, "timeout_seconds": settings.task_stale_timeout_seconds},
                )
            if task_run.workflow_id:
                self._refresh_workflow_state(session, task_run.workflow_id)
        return len(stale_runs)

    def _should_retry_task(self, task_run: TaskRunTable, result: dict | None = None) -> bool:
        if task_run.attempt_count >= settings.task_max_retries:
            return False
        if result is None:
            return True
        return bool(result.get("retryable"))

    def _requeue_task_run(self, session, task_run: TaskRunTable, *, reason: str, actor: str, audit_action: str) -> None:
        now = utc_now()
        retry_history = list(task_run.result.get("retry_history", [])) if isinstance(task_run.result, dict) else []
        retry_history.append(
            {
                "attempt": task_run.attempt_count,
                "reason": reason,
                "timestamp": now.isoformat(),
            }
        )
        task_run.status = RunStatus.PENDING.value
        task_run.updated_at = now
        task_run.finished_at = None
        task_run.worker_id = None
        task_run.error_message = reason
        task_run.score = None
        task_run.result = {"retry_history": retry_history}
        self._audit(
            session,
            actor,
            audit_action,
            task_run.task_id,
            {
                "server_id": task_run.server_id,
                "attempt_count": task_run.attempt_count,
                "reason": reason,
            },
        )
        self._record_task_event(
            session,
            task_id=task_run.task_id,
            event_type="task.requeued",
            status=RunStatus.PENDING.value,
            summary=f"{nice_task_name(task_run.task)} was re-queued for another attempt.",
            details={"server_id": task_run.server_id, "actor": actor, "attempt_count": task_run.attempt_count, "reason": reason},
        )

    def _latest_score(self, session, server_id: str) -> float | None:
        return session.scalar(
            select(TaskRunTable.score)
            .where(TaskRunTable.server_id == server_id, TaskRunTable.score.is_not(None))
            .order_by(TaskRunTable.updated_at.desc())
            .limit(1)
        )

    def _latest_metrics(self, session) -> list[MetricSnapshotTable]:
        latest_by_server: dict[str, MetricSnapshotTable] = {}
        for row in session.scalars(select(MetricSnapshotTable).order_by(MetricSnapshotTable.timestamp.desc())).all():
            latest_by_server.setdefault(row.server_id, row)
        return list(latest_by_server.values())

    def _notify_alert(self, session, alert: AlertRecord) -> None:
        for endpoint in repository.active_notification_endpoints(session):
            try:
                delivery = deliver_alert_notification(endpoint, alert)
            except Exception as exc:
                delivery = f"failed:{exc}"
            self._audit(session, "system", "alert.notified", alert.alert_id, {"endpoint_id": endpoint.endpoint_id, "channel": endpoint.channel, "result": delivery})

    def _baseline_policy_for_run(self, session, server_id: str, task: str) -> BaselinePolicyTable | None:
        server = session.get(ServerTable, server_id)
        if not server:
            return None
        return repository.baseline_for(session, server.group, task)

    def _baseline_comparison(self, task_run: TaskRunTable, baseline: BaselinePolicyTable | None) -> BaselineComparison:
        if not baseline:
            return BaselineComparison()
        metrics = task_run.result.get("metrics", {}) if isinstance(task_run.result, dict) else {}
        checks = {
            "minimum_score": bool(task_run.score is not None and task_run.score >= baseline.minimum_score),
            "max_temperature_c": True if baseline.max_temperature_c is None else (metrics.get("temperature_c") or 0) <= baseline.max_temperature_c,
            "min_throughput": True if baseline.min_throughput is None else (metrics.get("throughput_mbps") or metrics.get("throughput_gbps") or 0) >= baseline.min_throughput,
        }
        return BaselineComparison(
            baseline=self._baseline_policy(baseline),
            matched=all(checks.values()),
            score_delta=(round((task_run.score or 0) - baseline.minimum_score, 2) if task_run.score is not None else None),
            checks=checks,
        )

    def _group_inventory_summary(self, session, servers: list[ServerTable]) -> list[GroupInventorySummary]:
        alerts = repository.list_alerts(session, limit=200)
        scores_by_group: dict[str, list[float]] = {}
        capabilities_by_group: dict[str, set[str]] = {}
        online_by_group: dict[str, int] = {}
        total_by_group: dict[str, int] = {}
        alerts_by_group: dict[str, int] = {}
        server_group = {server.server_id: server.group for server in servers}

        for server in servers:
            total_by_group[server.group] = total_by_group.get(server.group, 0) + 1
            if server.status == ServerStatus.ONLINE.value:
                online_by_group[server.group] = online_by_group.get(server.group, 0) + 1
            capabilities_by_group.setdefault(server.group, set()).update(server.capabilities)

        for run in session.scalars(select(TaskRunTable).where(TaskRunTable.score.is_not(None))).all():
            group = server_group.get(run.server_id)
            if group:
                scores_by_group.setdefault(group, []).append(run.score)

        for alert in alerts:
            group = server_group.get(alert.server_id)
            if group and alert.state != AlertState.RESOLVED.value:
                alerts_by_group[group] = alerts_by_group.get(group, 0) + 1

        groups = sorted(total_by_group.keys())
        return [
            GroupInventorySummary(
                group=group,
                total_servers=total_by_group.get(group, 0),
                online_servers=online_by_group.get(group, 0),
                active_alerts=alerts_by_group.get(group, 0),
                average_score=round(sum(scores_by_group.get(group, [])) / len(scores_by_group.get(group, [])), 2) if scores_by_group.get(group) else 0,
                capabilities=sorted(capabilities_by_group.get(group, set())),
            )
            for group in groups
        ]

    def _derive_health(self, snapshot: dict, latest_score: float | None) -> HealthStatus:
        if snapshot["cpu"] >= 95 or snapshot["memory"] >= 98 or snapshot["disk"] >= 95:
            return HealthStatus.FAIL
        if (snapshot.get("temperature_c") or 0) >= 85:
            return HealthStatus.FAIL
        if latest_score is not None and latest_score < 70:
            return HealthStatus.FAIL
        if snapshot["cpu"] >= 85 or snapshot["memory"] >= 90 or snapshot["disk"] >= 88:
            return HealthStatus.WARNING
        return HealthStatus.PASS

    def _derive_hardware_health(
        self,
        failing_components: list[HardwareComponentTable],
        hot_components: list[HardwareComponentTable],
    ) -> HealthStatus:
        if failing_components:
            return HealthStatus.FAIL
        if hot_components:
            return HealthStatus.WARNING
        return HealthStatus.PASS

    def _component_is_hot(self, session, component: HardwareComponentTable) -> bool:
        for metric in repository.list_component_metrics(session, component.component_id, limit=20):
            if metric.metric_key.endswith("temperature_c") and isinstance(metric.value, (int, float)) and metric.value >= 80:
                return True
        return False

    @staticmethod
    def _component_count_map(components: list[HardwareComponentTable]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for component in components:
            counts[component.component_type] = counts.get(component.component_type, 0) + 1
        return counts

    @staticmethod
    def _latest_numeric_metric(
        latest_metric_rows: dict[tuple[str, str], HardwareComponentMetricTable],
        server_id: str,
        metric_key: str,
    ) -> float | None:
        row = latest_metric_rows.get((server_id, metric_key))
        if row is None or row.value is None:
            return None
        return float(row.value)

    def _fleet_component_summaries(
        self,
        servers: list[ServerTable],
        components: list[HardwareComponentTable],
        latest_metric_rows: dict[tuple[str, str], HardwareComponentMetricTable],
    ) -> list[FleetComponentSummary]:
        summaries: list[FleetComponentSummary] = []
        families = {
            "cpu": ("CPU", "cpu.load_percent", "%"),
            "memory": ("Memory", "memory.used_percent", "%"),
            "storage": ("Storage", "disk.used_percent", "%"),
            "gpu": ("GPU", "gpu.utilization_percent", "%"),
            "network": ("Network", "network.rx_mbps", "Mbps"),
            "thermal_power": ("Thermal / Power", "temperature_c", "C"),
            "pcie_inventory": ("PCIe / Inventory", None, None),
            "system": ("System", None, None),
        }
        for key, (label, metric_key, unit) in families.items():
            family_components = [component for component in components if component.component_type == key]
            values = [
                value
                for server in servers
                for value in [self._latest_numeric_metric(latest_metric_rows, server.server_id, metric_key)] if metric_key and value is not None
            ]
            summaries.append(
                FleetComponentSummary(
                    key=key,
                    label=label,
                    total_components=len(family_components),
                    healthy_components=sum(1 for component in family_components if component.health == HealthStatus.PASS.value),
                    warning_components=sum(1 for component in family_components if component.health == HealthStatus.WARNING.value),
                    failing_components=sum(1 for component in family_components if component.health == HealthStatus.FAIL.value),
                    reporting_servers=len({component.server_id for component in family_components}),
                    unsupported_servers=max(0, len(servers) - len({component.server_id for component in family_components})),
                    average_value=round(sum(values) / len(values), 2) if values else None,
                    unit=unit,
                )
            )

        fan_components = [
            component
            for component in components
            if component.component_type == "thermal_power" and bool((component.capabilities or {}).get("fan_speed"))
        ]
        fan_values = [
            float(row.value)
            for (server_id, metric_key), row in latest_metric_rows.items()
            if metric_key == "fan.speed_rpm" and row.value is not None
        ]
        summaries.append(
            FleetComponentSummary(
                key="fan",
                label="Fan Speed",
                total_components=len(fan_components),
                healthy_components=sum(1 for component in fan_components if component.health == HealthStatus.PASS.value),
                warning_components=sum(1 for component in fan_components if component.health == HealthStatus.WARNING.value),
                failing_components=sum(1 for component in fan_components if component.health == HealthStatus.FAIL.value),
                reporting_servers=len({
                    server_id
                    for (server_id, metric_key), row in latest_metric_rows.items()
                    if metric_key == "fan.speed_rpm" and row.value is not None
                }),
                unsupported_servers=max(0, len(servers) - len({component.server_id for component in fan_components})),
                average_value=round(sum(fan_values) / len(fan_values), 2) if fan_values else None,
                unit="RPM",
            )
        )
        return summaries

    def _fleet_metric_histories(self, metric_rows: list[HardwareComponentMetricTable]) -> list[FleetMetricHistorySeries]:
        metric_map = {
            "cpu": ("CPU Load", "cpu.load_percent", "%"),
            "memory": ("Memory Pressure", "memory.used_percent", "%"),
            "storage": ("Disk Pressure", "disk.used_percent", "%"),
            "gpu": ("GPU Utilization", "gpu.utilization_percent", "%"),
            "network": ("Network Throughput", "network.rx_mbps", "Mbps"),
            "thermal": ("Temperature", "temperature_c", "C"),
            "fan": ("Fan Speed", "fan.speed_rpm", "RPM"),
        }
        series: list[FleetMetricHistorySeries] = []
        for key, (label, metric_key, unit) in metric_map.items():
            rows = [row for row in reversed(metric_rows) if row.metric_key == metric_key and row.value is not None]
            buckets: dict[str, list[float]] = {}
            bucket_times: dict[str, datetime] = {}
            for row in rows:
                bucket_label = self._as_utc(row.recorded_at).strftime("%H:%M")
                buckets.setdefault(bucket_label, []).append(float(row.value))
                bucket_times[bucket_label] = self._as_utc(row.recorded_at)
            points = [
                FleetMetricHistoryPoint(
                    timestamp=bucket_times[bucket_label],
                    label=bucket_label,
                    average_value=round(sum(values) / len(values), 2) if values else None,
                    max_value=round(max(values), 2) if values else None,
                    reporting_components=len(values),
                )
                for bucket_label, values in list(buckets.items())[-12:]
            ]
            series.append(
                FleetMetricHistorySeries(
                    key=key,
                    label=label,
                    metric_key=metric_key,
                    unit=unit,
                    points=points,
                )
            )
        return series

    def _hardware_overview_dict(self, session, server: ServerTable, components: list[HardwareComponentTable], collector_runs: list[CollectorRunTable]) -> dict[str, object]:
        by_type: dict[str, dict[str, object]] = {}
        hot_components: list[HardwareComponentTable] = []
        failing_components: list[HardwareComponentTable] = []
        for component in components:
            bucket = by_type.setdefault(
                component.component_type,
                {"count": 0, "warning_count": 0, "failing_count": 0, "healthy_count": 0},
            )
            bucket["count"] = int(bucket["count"]) + 1
            if component.health == HealthStatus.FAIL.value:
                bucket["failing_count"] = int(bucket["failing_count"]) + 1
                failing_components.append(component)
            elif self._component_is_hot(session, component):
                bucket["warning_count"] = int(bucket["warning_count"]) + 1
                hot_components.append(component)
            else:
                bucket["healthy_count"] = int(bucket["healthy_count"]) + 1
        return {
            "overall_health": self._derive_hardware_health(failing_components, hot_components).value,
            "component_types": by_type,
            "hot_component_count": len(hot_components),
            "failing_component_count": len(failing_components),
            "collector_status_count": len(collector_runs),
            "last_telemetry_at": server.last_telemetry_at,
            "last_inventory_refresh_at": server.last_inventory_refresh_at,
        }

    def _hardware_overview_response(
        self,
        server: ServerTable,
        *,
        component_health: dict[str, dict[str, object]],
        hot_components: list[HardwareComponentTable],
        failing_components: list[HardwareComponentTable],
        collector_runs: list[CollectorRunTable],
    ) -> HardwareOverviewResponse:
        collector_statuses = [self._collector_status(run) for run in collector_runs]
        stale_collectors = [status for status in collector_statuses if status.status not in {"ok", "healthy"}]
        return HardwareOverviewResponse(
            server=self._server_view(server),
            overall_health=self._derive_hardware_health(failing_components, hot_components),
            component_health=component_health,
            hot_components=[self._hardware_component(component) for component in hot_components],
            failing_components=[self._hardware_component(component) for component in failing_components],
            stale_collectors=stale_collectors,
            collector_statuses=collector_statuses,
            last_telemetry_at=server.last_telemetry_at,
            last_inventory_refresh_at=server.last_inventory_refresh_at,
        )

    def _identity_groups_from_components(self, server: ServerTable, components: list[HardwareComponentTable]) -> dict[str, object]:
        system_component = next((component for component in components if component.component_type == "system"), None)
        network_components = [component for component in components if component.component_type == "network"]
        system_metadata = dict(system_component.metadata_json or {}) if system_component else {}
        system_identity_payload = dict(system_metadata.get("system_identity") or {})
        firmware_identity_payload = dict(system_metadata.get("firmware_identity") or {})
        bmc_identity_payload = dict(system_metadata.get("bmc_identity") or {})
        agent_identity_payload = dict(system_metadata.get("agent_identity") or {})
        network_identity_payload = dict(system_metadata.get("network_identity") or {})
        software_inventory_payload = dict(system_metadata.get("software_inventory") or {})

        system_identity = SystemIdentity(
            os=system_identity_payload.get("os") or system_metadata.get("os"),
            platform=system_identity_payload.get("platform") or system_metadata.get("platform"),
            hostname=system_identity_payload.get("hostname") or (system_component.name if system_component else server.server_name),
            architecture=system_identity_payload.get("architecture") or system_metadata.get("architecture") or (system_component.model if system_component else None),
            kernel=system_identity_payload.get("kernel") or system_metadata.get("kernel"),
            build=system_identity_payload.get("build") or system_metadata.get("build"),
            vendor=system_identity_payload.get("vendor") or (system_component.vendor if system_component else None),
            model=system_identity_payload.get("model") or (system_component.model if system_component else None),
            serial=system_identity_payload.get("serial") or (system_component.serial if system_component else None),
            board=system_identity_payload.get("board") or system_metadata.get("board_name") or system_metadata.get("board"),
            board_vendor=system_identity_payload.get("board_vendor") or system_metadata.get("board_vendor"),
            board_serial=system_identity_payload.get("board_serial") or system_metadata.get("board_serial"),
            metadata=system_identity_payload or system_metadata,
        )
        firmware_identity = FirmwareIdentity(
            bios_vendor=firmware_identity_payload.get("bios_vendor") or system_metadata.get("bios_vendor"),
            bios_version=firmware_identity_payload.get("bios_version") or system_metadata.get("bios_version"),
            bios_release_date=firmware_identity_payload.get("bios_release_date") or system_metadata.get("bios_date"),
            board_firmware_version=firmware_identity_payload.get("board_firmware_version") or system_metadata.get("board_firmware_version"),
            metadata=firmware_identity_payload,
        )
        bmc_identity = BmcIdentity(
            present=bool(bmc_identity_payload.get("present")),
            vendor=bmc_identity_payload.get("vendor"),
            model=bmc_identity_payload.get("model"),
            firmware_version=bmc_identity_payload.get("firmware_version"),
            address=bmc_identity_payload.get("address"),
            source=bmc_identity_payload.get("source"),
            metadata=bmc_identity_payload,
        )
        agent_identity = AgentIdentity(
            version=agent_identity_payload.get("version"),
            runtime=agent_identity_payload.get("runtime"),
            executable=agent_identity_payload.get("executable"),
            platform=agent_identity_payload.get("platform"),
            metadata=agent_identity_payload,
        )
        interface_models: list[NetworkInterfaceIdentity] = []
        if network_identity_payload.get("interfaces"):
            for item in network_identity_payload.get("interfaces") or []:
                if isinstance(item, dict):
                    interface_models.append(
                        NetworkInterfaceIdentity(
                            name=str(item.get("name") or "interface"),
                            ipv4_addresses=[str(value) for value in item.get("ipv4_addresses") or []],
                            ipv6_addresses=[str(value) for value in item.get("ipv6_addresses") or []],
                            mac_address=item.get("mac_address"),
                            link_state=item.get("link_state"),
                            speed_mbps=item.get("speed_mbps"),
                            mtu=item.get("mtu"),
                            gateway=item.get("gateway"),
                            dns_servers=[str(value) for value in item.get("dns_servers") or []],
                            counters=dict(item.get("counters") or {}),
                            metadata=dict(item.get("metadata") or {}),
                        )
                    )
        elif network_components:
            for component in network_components:
                metadata = dict(component.metadata_json or {})
                interface_models.append(
                    NetworkInterfaceIdentity(
                        name=component.name,
                        ipv4_addresses=[str(value) for value in metadata.get("ipv4_addresses") or []],
                        ipv6_addresses=[str(value) for value in metadata.get("ipv6_addresses") or []],
                        mac_address=metadata.get("mac_address"),
                        link_state=component.status,
                        speed_mbps=metadata.get("speed_mbps"),
                        mtu=metadata.get("mtu"),
                        gateway=metadata.get("gateway"),
                        dns_servers=[str(value) for value in metadata.get("dns_servers") or []],
                        counters=dict(metadata.get("counters") or {}),
                        metadata=metadata,
                    )
                )
        platform_addresses = [
            address
            for interface in interface_models
            for address in [*interface.ipv4_addresses, *interface.ipv6_addresses]
            if address
        ]
        network_identity = NetworkIdentity(
            primary_ip=network_identity_payload.get("primary_ip") or (platform_addresses[0] if platform_addresses else None),
            primary_mac=network_identity_payload.get("primary_mac") or next((item.mac_address for item in interface_models if item.mac_address), None),
            gateway=network_identity_payload.get("gateway") or next((item.gateway for item in interface_models if item.gateway), None),
            dns_servers=[str(value) for value in network_identity_payload.get("dns_servers") or []]
            or [dns for item in interface_models for dns in item.dns_servers],
            hostname=network_identity_payload.get("hostname") or system_identity.hostname,
            fqdn=network_identity_payload.get("fqdn"),
            interfaces=interface_models,
            metadata=network_identity_payload,
        )
        software_inventory = SoftwareInventory(
            os_edition=software_inventory_payload.get("os_edition"),
            os_build=software_inventory_payload.get("os_build") or system_identity.build,
            kernel_version=software_inventory_payload.get("kernel_version") or system_identity.kernel,
            python_version=software_inventory_payload.get("python_version") or system_metadata.get("python"),
            runtime=software_inventory_payload.get("runtime") or agent_identity.runtime,
            driver_versions=dict(software_inventory_payload.get("driver_versions") or {}),
            metadata=software_inventory_payload,
        )
        return {
            "system_identity": system_identity,
            "firmware_identity": firmware_identity,
            "bmc_identity": bmc_identity,
            "agent_identity": agent_identity,
            "network_identity": network_identity,
            "software_inventory": software_inventory,
            "platform_addresses": platform_addresses,
        }

    def _server_summary_for_server(self, session, server_id: str) -> dict[str, str | None]:
        server = session.get(ServerTable, server_id)
        if server is None:
            return self._server_summary(None, None)
        components = repository.list_hardware_components(session, server_id)
        identities = self._identity_groups_from_components(server, components) if components else None
        return self._server_summary(server, identities)

    @staticmethod
    def _platform_summary(server: ServerTable | None, system_identity: SystemIdentity | None) -> tuple[str | None, str | None]:
        if system_identity is None:
            if server and server.group:
                return (server.group, None)
            return (None, None)
        family = system_identity.os or system_identity.platform
        detail = system_identity.architecture or system_identity.kernel
        if family and detail:
            return (f"{family} / {detail}", family)
        if family:
            return (family, family)
        if server and server.group:
            return (server.group, None)
        return (None, None)

    @classmethod
    def _server_summary(cls, server: ServerTable | None, identities: dict[str, object] | None) -> dict[str, str | None]:
        system_identity = identities.get("system_identity") if identities else None
        network_identity = identities.get("network_identity") if identities else None
        bmc_identity = identities.get("bmc_identity") if identities else None
        platform_label, platform_family = cls._platform_summary(server, system_identity if isinstance(system_identity, SystemIdentity) else None)
        primary_ip = network_identity.primary_ip if isinstance(network_identity, NetworkIdentity) else None
        bmc_address = bmc_identity.address if isinstance(bmc_identity, BmcIdentity) else None
        return {
            "platform_label": platform_label,
            "platform_family": platform_family,
            "primary_ip": primary_ip,
            "bmc_address": bmc_address,
        }

    def _validate_agent(self, session, server_id: str, api_key: str) -> ServerTable:
        server = session.get(ServerTable, server_id)
        if not server or server.api_key != api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent credentials.")
        return server

    def _require_server(self, session, server_id: str) -> None:
        if not session.get(ServerTable, server_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")

    def _audit(self, session, actor: str, action: str, resource: str, details: dict) -> None:
        session.add(AuditEventTable(event_id=f"audit-{secrets.token_hex(6)}", actor=actor, action=action, resource=resource, details=details))

    @staticmethod
    def _append_terminal_frames(terminal: TerminalSessionTable, frames: list[TerminalFrame], max_frames: int = 400) -> None:
        serialized = list(terminal.recent_output_json or [])
        serialized.extend(frame.model_dump(mode="json") for frame in frames)
        terminal.recent_output_json = serialized[-max_frames:]

    def _record_task_event(
        self,
        session,
        *,
        task_id: str,
        event_type: str,
        status: str | None,
        summary: str,
        details: dict[str, object] | None = None,
    ) -> None:
        repository.create_task_event(
            session,
            event_id=f"evt-{secrets.token_hex(6)}",
            task_id=task_id,
            event_type=event_type,
            status=status,
            summary=summary,
            details=details or {},
        )

    @staticmethod
    def _task_terminal_summary(task_name: str, status: str, score: float | None, error_message: str | None) -> str:
        readable_task = nice_task_name(task_name)
        if status == RunStatus.COMPLETED.value:
            score_label = f" with score {round(score, 2)}" if score is not None else ""
            return f"{readable_task} completed successfully{score_label}."
        if status == RunStatus.FAILED.value and error_message:
            return f"{readable_task} failed: {error_message}"
        return f"{readable_task} finished with status {status}."

    @staticmethod
    def _merge_server_activity(server: ServerTable) -> datetime:
        timestamps = [
            server.last_heartbeat_at,
            server.last_metric_at,
            server.last_telemetry_at,
            server.last_inventory_refresh_at,
            server.last_task_poll_at,
            server.last_task_result_at,
            server.last_seen,
            server.created_at,
        ]
        normalized = [PrometheusRuntime._as_utc(timestamp) for timestamp in timestamps if timestamp is not None]
        return max(normalized) if normalized else utc_now()

    @staticmethod
    def _agent_enrollment(enrollment: AgentEnrollmentTable) -> AgentEnrollment:
        return AgentEnrollment(
            enrollment_id=enrollment.enrollment_id,
            connection_code=enrollment.connection_code,
            display_name=enrollment.display_name,
            group=enrollment.group,
            tags=enrollment.tags,
            capabilities=enrollment.capabilities,
            target_os=AgentTargetOS(enrollment.target_os),
            status=AgentEnrollmentStatus(enrollment.status),
            expires_at=enrollment.expires_at,
            claimed_at=enrollment.claimed_at,
            claimed_server_id=enrollment.claimed_server_id,
            created_by=enrollment.created_by,
            created_at=enrollment.created_at,
            updated_at=enrollment.updated_at,
        )

    @staticmethod
    def _server_record(server: ServerTable, summary: dict[str, str | None] | None = None) -> ServerRecord:
        summary = summary or {}
        return ServerRecord(
            server_id=server.server_id,
            server_name=server.server_name,
            group=server.group,
            status=ServerStatus(server.status),
            tags=server.tags,
            capabilities=server.capabilities,
            command_capabilities=server.command_capabilities or {},
            health=HealthStatus(server.health),
            api_key=server.api_key,
            created_at=server.created_at,
            last_seen=server.last_seen,
            last_heartbeat_at=server.last_heartbeat_at,
            last_metric_at=server.last_metric_at,
            last_telemetry_at=server.last_telemetry_at,
            last_inventory_refresh_at=server.last_inventory_refresh_at,
            last_task_poll_at=server.last_task_poll_at,
            last_task_result_at=server.last_task_result_at,
            last_task_activity_at=server.last_task_result_at or server.last_task_poll_at,
            platform_label=summary.get("platform_label"),
            platform_family=summary.get("platform_family"),
            primary_ip=summary.get("primary_ip"),
            bmc_address=summary.get("bmc_address"),
        )

    @staticmethod
    def _server_view(server: ServerTable, summary: dict[str, str | None] | None = None) -> ServerView:
        summary = summary or {}
        return ServerView(
            server_id=server.server_id,
            server_name=server.server_name,
            group=server.group,
            status=ServerStatus(server.status),
            tags=server.tags,
            capabilities=server.capabilities,
            command_capabilities=server.command_capabilities or {},
            health=HealthStatus(server.health),
            created_at=server.created_at,
            last_seen=server.last_seen,
            last_heartbeat_at=server.last_heartbeat_at,
            last_metric_at=server.last_metric_at,
            last_telemetry_at=server.last_telemetry_at,
            last_inventory_refresh_at=server.last_inventory_refresh_at,
            last_task_poll_at=server.last_task_poll_at,
            last_task_result_at=server.last_task_result_at,
            last_task_activity_at=server.last_task_result_at or server.last_task_poll_at,
            platform_label=summary.get("platform_label"),
            platform_family=summary.get("platform_family"),
            primary_ip=summary.get("primary_ip"),
            bmc_address=summary.get("bmc_address"),
        )

    @staticmethod
    def _terminal_frame(payload: dict[str, object]) -> TerminalFrame:
        return TerminalFrame(
            kind=TerminalFrameKind(str(payload.get("kind") or TerminalFrameKind.STATUS.value)),
            text=payload.get("text") if isinstance(payload.get("text"), str) else None,
            cols=int(payload["cols"]) if isinstance(payload.get("cols"), (int, float)) else None,
            rows=int(payload["rows"]) if isinstance(payload.get("rows"), (int, float)) else None,
            timestamp=payload.get("timestamp") if isinstance(payload.get("timestamp"), datetime) else datetime.fromisoformat(str(payload.get("timestamp"))) if payload.get("timestamp") else utc_now(),
            meta=payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
        )

    @classmethod
    def _terminal_session_summary(cls, terminal: TerminalSessionTable) -> TerminalSessionSummary:
        return TerminalSessionSummary(
            session_id=terminal.session_id,
            server_id=terminal.server_id,
            opened_by=terminal.opened_by,
            status=TerminalSessionStatus(terminal.status),
            shell_type=terminal.shell_type,
            terminal_supported=terminal.terminal_supported,
            created_at=terminal.created_at,
            updated_at=terminal.updated_at,
            closed_at=terminal.closed_at,
            last_agent_seen_at=terminal.last_agent_seen_at,
            last_browser_seen_at=terminal.last_browser_seen_at,
            meta=terminal.metadata_json or {},
        )

    @classmethod
    def _terminal_session(cls, terminal: TerminalSessionTable) -> TerminalSession:
        return TerminalSession(
            **cls._terminal_session_summary(terminal).model_dump(),
            recent_output=[cls._terminal_frame(frame) for frame in terminal.recent_output_json or []],
        )

    @staticmethod
    def _hardware_component(component: HardwareComponentTable) -> HardwareComponent:
        return HardwareComponent(
            component_id=component.component_id,
            server_id=component.server_id,
            component_type=component.component_type,
            name=component.name,
            slot_or_path=component.slot_or_path,
            vendor=component.vendor,
            model=component.model,
            serial=component.serial,
            firmware_version=component.firmware_version,
            status=component.status,
            health=HealthStatus(component.health),
            capabilities=component.capabilities or {},
            metadata=component.metadata_json or {},
            created_at=component.created_at,
            updated_at=component.updated_at,
            last_seen_at=component.last_seen_at,
        )

    @staticmethod
    def _hardware_metric_point(metric: HardwareComponentMetricTable) -> HardwareMetricPoint:
        return HardwareMetricPoint(
            component_id=metric.component_id,
            metric_key=metric.metric_key,
            value=metric.value,
            unit=metric.unit,
            status=metric.status,
            labels=metric.labels_json or {},
            recorded_at=metric.recorded_at,
        )

    @staticmethod
    def _collector_status(run: CollectorRunTable) -> CollectorStatus:
        return CollectorStatus(
            collector_name=run.collector_name,
            status=run.status,
            capability=CollectorCapability(
                state=run.capability_state or "unknown",
                supported=(run.capability_state or "unknown") not in {"unsupported", "permission_denied"},
                message=run.details.get("capability_message") if isinstance(run.details, dict) else None,
                source=run.details.get("source") if isinstance(run.details, dict) else None,
            ),
            duration_ms=run.duration_ms,
            message=run.message,
            metrics_emitted=run.metrics_emitted,
            inventory_items_seen=run.inventory_items_seen,
            recorded_at=run.recorded_at,
            details=run.details or {},
        )

    @staticmethod
    def _metric_snapshot(snapshot: MetricSnapshotTable) -> MetricSnapshot:
        return MetricSnapshot(
            server_id=snapshot.server_id,
            cpu=snapshot.cpu,
            memory=snapshot.memory,
            disk=snapshot.disk,
            network_mbps=snapshot.network_mbps,
            temperature_c=snapshot.temperature_c,
            gpu_utilization=snapshot.gpu_utilization,
            fan_speed_rpm=getattr(snapshot, "fan_speed_rpm", None),
            timestamp=snapshot.timestamp,
        )

    @staticmethod
    def _task_run(task_run: TaskRunTable) -> TaskRun:
        return TaskRun(
            task_id=task_run.task_id,
            server_id=task_run.server_id,
            task=task_run.task,
            params=task_run.params,
            requested_by=task_run.requested_by,
            status=RunStatus(task_run.status),
            workflow_id=task_run.workflow_id,
            created_at=task_run.created_at,
            updated_at=task_run.updated_at,
            started_at=task_run.started_at,
            finished_at=task_run.finished_at,
            attempt_count=task_run.attempt_count,
            worker_id=task_run.worker_id,
            error_message=task_run.error_message,
            logs=task_run.logs,
            result=task_run.result,
            score=task_run.score,
        )

    @staticmethod
    def _task_artifact(artifact) -> TaskArtifact:
        return TaskArtifact(
            artifact_id=artifact.artifact_id,
            task_id=artifact.task_id,
            label=artifact.label,
            artifact_type=artifact.artifact_type,
            content_type=artifact.content_type,
            size_bytes=artifact.size_bytes,
            metadata=artifact.metadata_json,
            created_at=artifact.created_at,
            download_path=f"/api/v1/control/runs/{artifact.task_id}/artifacts/{artifact.artifact_id}",
        )

    @staticmethod
    def _task_event(event: TaskRunEventTable) -> TaskEvent:
        return TaskEvent(
            event_id=event.event_id,
            task_id=event.task_id,
            event_type=event.event_type,
            status=RunStatus(event.status) if event.status else None,
            summary=event.summary,
            details=event.details,
            created_at=event.created_at,
        )

    @staticmethod
    def _workflow_run(workflow: WorkflowRunTable) -> WorkflowRun:
        return WorkflowRun(
            workflow_id=workflow.workflow_id,
            server_id=workflow.server_id,
            workflow=workflow.workflow,
            steps=workflow.steps,
            linked_task_ids=workflow.linked_task_ids,
            status=RunStatus(workflow.status),
            current_step_index=workflow.current_step_index,
            requested_by=workflow.requested_by,
            params=workflow.params,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            finished_at=workflow.finished_at,
        )

    @staticmethod
    def _audit_event(event: AuditEventTable) -> AuditEvent:
        return AuditEvent(
            event_id=event.event_id,
            actor=event.actor,
            action=event.action,
            resource=event.resource,
            timestamp=event.timestamp,
            details=event.details,
        )

    @staticmethod
    def _alert_rule(rule: AlertRuleTable) -> AlertRule:
        return AlertRule(
            rule_id=rule.rule_id,
            name=rule.name,
            signal=rule.signal,
            threshold=rule.threshold,
            severity=AlertSeverity(rule.severity),
            enabled=rule.enabled,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )

    @staticmethod
    def _alert_record(alert: AlertRecordTable) -> AlertRecord:
        return AlertRecord(
            alert_id=alert.alert_id,
            server_id=alert.server_id,
            severity=AlertSeverity(alert.severity),
            signal=alert.signal,
            value=alert.value,
            message=alert.message,
            state=AlertState(alert.state),
            rule_id=alert.rule_id,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
        )

    @staticmethod
    def _notification_endpoint(endpoint: NotificationEndpointTable) -> NotificationEndpoint:
        return NotificationEndpoint(
            endpoint_id=endpoint.endpoint_id,
            name=endpoint.name,
            channel=endpoint.channel,
            target=endpoint.target,
            enabled=endpoint.enabled,
            created_at=endpoint.created_at,
        )

    @staticmethod
    def _schedule_record(schedule: ScheduleTable) -> ScheduleRecord:
        return ScheduleRecord(
            schedule_id=schedule.schedule_id,
            name=schedule.name,
            server_id=schedule.server_id,
            workflow=schedule.workflow,
            params=schedule.params,
            interval_minutes=schedule.interval_minutes,
            active=schedule.active,
            next_run_at=schedule.next_run_at,
            last_run_at=schedule.last_run_at,
            created_by=schedule.created_by,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )

    @staticmethod
    def _baseline_policy(baseline: BaselinePolicyTable) -> BaselinePolicy:
        return BaselinePolicy(
            baseline_id=baseline.baseline_id,
            name=baseline.name,
            group=baseline.group,
            task=baseline.task,
            minimum_score=baseline.minimum_score,
            max_temperature_c=baseline.max_temperature_c,
            min_throughput=baseline.min_throughput,
            created_at=baseline.created_at,
            updated_at=baseline.updated_at,
        )

    @staticmethod
    def _generate_server_id() -> str:
        return f"srv-{secrets.token_hex(4)}"

    @staticmethod
    def _generate_api_key() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def _generate_task_id() -> str:
        return f"task-{secrets.token_hex(5)}"

    @staticmethod
    def _generate_workflow_id() -> str:
        return f"wf-{secrets.token_hex(5)}"

    @staticmethod
    def _as_utc(value):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


runtime = PrometheusRuntime()


def queue_runtime_job(task_name: str, *args) -> None:
    if settings.celery_task_always_eager:
        from app.jobs import process_due_schedules, reconcile_runtime, refresh_workflow

        task_map = {
            "app.jobs.process_due_schedules": process_due_schedules,
            "app.jobs.reconcile_runtime": reconcile_runtime,
            "app.jobs.refresh_workflow": refresh_workflow,
        }
        task = task_map[task_name]
        task.apply(args=args)
        return

    celery_app.send_task(task_name, args=list(args))

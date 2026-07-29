from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db_models import (
    AgentEnrollmentTable,
    AlertRecordTable,
    AlertRuleTable,
    BaselinePolicyTable,
    CollectorRunTable,
    HardwareComponentMetricTable,
    HardwareComponentTable,
    MetricSnapshotTable,
    NotificationEndpointTable,
    ScheduleTable,
    ServerTable,
    TaskArtifactTable,
    TaskRunEventTable,
    TaskRunTable,
    WorkflowRunTable,
)
from app.models import AlertState, AlertStatusUpdate, ScheduleCreate, ScheduleUpdate, utc_now


class RuntimeRepository:
    def list_agent_enrollments(self, session: Session, include_completed: bool = True, limit: int = 20) -> list[AgentEnrollmentTable]:
        statement = select(AgentEnrollmentTable).order_by(desc(AgentEnrollmentTable.created_at)).limit(limit)
        if not include_completed:
            statement = statement.where(AgentEnrollmentTable.status == "pending")
        return session.scalars(statement).all()

    def get_agent_enrollment(self, session: Session, enrollment_id: str) -> AgentEnrollmentTable | None:
        return session.get(AgentEnrollmentTable, enrollment_id)

    def get_agent_enrollment_by_code(self, session: Session, connection_code: str) -> AgentEnrollmentTable | None:
        return session.scalar(
            select(AgentEnrollmentTable).where(AgentEnrollmentTable.connection_code == connection_code).limit(1)
        )

    def create_agent_enrollment(
        self,
        session: Session,
        *,
        enrollment_id: str,
        connection_code: str,
        display_name: str,
        group: str,
        tags: list[str],
        capabilities: list[str],
        target_os: str,
        status: str,
        expires_at,
        created_by: str,
    ) -> AgentEnrollmentTable:
        now = utc_now()
        enrollment = AgentEnrollmentTable(
            enrollment_id=enrollment_id,
            connection_code=connection_code,
            display_name=display_name,
            group=group,
            tags=tags,
            capabilities=capabilities,
            target_os=target_os,
            status=status,
            expires_at=expires_at,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        session.add(enrollment)
        session.flush()
        return enrollment

    def update_agent_enrollment_status(
        self,
        session: Session,
        enrollment: AgentEnrollmentTable,
        *,
        status: str,
        claimed_server_id: str | None = None,
        claimed_at=None,
    ) -> AgentEnrollmentTable:
        enrollment.status = status
        enrollment.claimed_server_id = claimed_server_id
        enrollment.claimed_at = claimed_at
        enrollment.updated_at = utc_now()
        session.flush()
        return enrollment

    def list_hardware_components(self, session: Session, server_id: str) -> list[HardwareComponentTable]:
        return session.scalars(
            select(HardwareComponentTable)
            .where(HardwareComponentTable.server_id == server_id)
            .order_by(HardwareComponentTable.component_type.asc(), HardwareComponentTable.name.asc())
        ).all()

    def get_hardware_component(self, session: Session, component_id: str) -> HardwareComponentTable | None:
        return session.get(HardwareComponentTable, component_id)

    def upsert_hardware_component(
        self,
        session: Session,
        *,
        component_id: str,
        server_id: str,
        component_type: str,
        name: str,
        slot_or_path: str | None,
        vendor: str | None,
        model: str | None,
        serial: str | None,
        firmware_version: str | None,
        status: str,
        health: str,
        capabilities: dict,
        metadata_json: dict,
    ) -> HardwareComponentTable:
        now = utc_now()
        component = session.get(HardwareComponentTable, component_id)
        if component is None:
            component = HardwareComponentTable(
                component_id=component_id,
                server_id=server_id,
                component_type=component_type,
                name=name,
                slot_or_path=slot_or_path,
                vendor=vendor,
                model=model,
                serial=serial,
                firmware_version=firmware_version,
                status=status,
                health=health,
                capabilities=capabilities,
                metadata_json=metadata_json,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            session.add(component)
        else:
            component.server_id = server_id
            component.component_type = component_type
            component.name = name
            component.slot_or_path = slot_or_path
            component.vendor = vendor
            component.model = model
            component.serial = serial
            component.firmware_version = firmware_version
            component.status = status
            component.health = health
            component.capabilities = capabilities
            component.metadata_json = metadata_json
            component.updated_at = now
            component.last_seen_at = now
        session.flush()
        return component

    def create_hardware_metric(
        self,
        session: Session,
        *,
        server_id: str,
        component_id: str,
        metric_key: str,
        value: float | None,
        unit: str | None,
        status: str,
        labels_json: dict,
        recorded_at,
    ) -> HardwareComponentMetricTable:
        metric = HardwareComponentMetricTable(
            server_id=server_id,
            component_id=component_id,
            metric_key=metric_key,
            value=value,
            unit=unit,
            status=status,
            labels_json=labels_json,
            recorded_at=recorded_at,
        )
        session.add(metric)
        session.flush()
        return metric

    def list_component_metrics(
        self,
        session: Session,
        component_id: str,
        metric_key: str | None = None,
        limit: int = 120,
    ) -> list[HardwareComponentMetricTable]:
        statement = select(HardwareComponentMetricTable).where(HardwareComponentMetricTable.component_id == component_id)
        if metric_key:
            statement = statement.where(HardwareComponentMetricTable.metric_key == metric_key)
        statement = statement.order_by(desc(HardwareComponentMetricTable.recorded_at)).limit(limit)
        return list(reversed(session.scalars(statement).all()))

    def latest_component_metrics(self, session: Session, server_id: str) -> list[HardwareComponentMetricTable]:
        rows = session.scalars(
            select(HardwareComponentMetricTable)
            .where(HardwareComponentMetricTable.server_id == server_id)
            .order_by(HardwareComponentMetricTable.recorded_at.desc())
        ).all()
        latest: dict[tuple[str, str], HardwareComponentMetricTable] = {}
        for row in rows:
            latest.setdefault((row.component_id, row.metric_key), row)
        return list(latest.values())

    def record_collector_run(
        self,
        session: Session,
        *,
        collector_run_id: str,
        server_id: str,
        collector_name: str,
        status: str,
        message: str | None,
        duration_ms: float | None,
        capability_state: str | None,
        metrics_emitted: int,
        inventory_items_seen: int,
        details: dict,
        recorded_at,
    ) -> CollectorRunTable:
        run = CollectorRunTable(
            collector_run_id=collector_run_id,
            server_id=server_id,
            collector_name=collector_name,
            status=status,
            message=message,
            duration_ms=duration_ms,
            capability_state=capability_state,
            metrics_emitted=metrics_emitted,
            inventory_items_seen=inventory_items_seen,
            details=details,
            recorded_at=recorded_at,
        )
        session.add(run)
        session.flush()
        return run

    def latest_collector_runs(self, session: Session, server_id: str) -> list[CollectorRunTable]:
        rows = session.scalars(
            select(CollectorRunTable)
            .where(CollectorRunTable.server_id == server_id)
            .order_by(CollectorRunTable.recorded_at.desc())
        ).all()
        latest: dict[str, CollectorRunTable] = {}
        for row in rows:
            latest.setdefault(row.collector_name, row)
        return list(latest.values())

    def list_task_events(self, session: Session, task_id: str) -> list[TaskRunEventTable]:
        return session.scalars(
            select(TaskRunEventTable).where(TaskRunEventTable.task_id == task_id).order_by(TaskRunEventTable.created_at.asc())
        ).all()

    def create_task_event(
        self,
        session: Session,
        *,
        event_id: str,
        task_id: str,
        event_type: str,
        status: str | None,
        summary: str,
        details: dict,
    ) -> TaskRunEventTable:
        event = TaskRunEventTable(
            event_id=event_id,
            task_id=task_id,
            event_type=event_type,
            status=status,
            summary=summary,
            details=details,
            created_at=utc_now(),
        )
        session.add(event)
        session.flush()
        return event

    def list_task_artifacts(self, session: Session, task_id: str) -> list[TaskArtifactTable]:
        return session.scalars(
            select(TaskArtifactTable).where(TaskArtifactTable.task_id == task_id).order_by(TaskArtifactTable.created_at.asc())
        ).all()

    def get_task_artifact(self, session: Session, task_id: str, artifact_id: str) -> TaskArtifactTable | None:
        return session.scalar(
            select(TaskArtifactTable).where(TaskArtifactTable.task_id == task_id, TaskArtifactTable.artifact_id == artifact_id).limit(1)
        )

    def delete_task_artifacts(self, session: Session, task_id: str) -> list[TaskArtifactTable]:
        artifacts = self.list_task_artifacts(session, task_id)
        for artifact in artifacts:
            session.delete(artifact)
        session.flush()
        return artifacts

    def create_task_artifact(
        self,
        session: Session,
        *,
        artifact_id: str,
        task_id: str,
        label: str,
        artifact_type: str,
        content_type: str,
        file_path: str,
        size_bytes: int,
        metadata_json: dict,
    ) -> TaskArtifactTable:
        artifact = TaskArtifactTable(
            artifact_id=artifact_id,
            task_id=task_id,
            label=label,
            artifact_type=artifact_type,
            content_type=content_type,
            file_path=file_path,
            size_bytes=size_bytes,
            metadata_json=metadata_json,
            created_at=utc_now(),
        )
        session.add(artifact)
        session.flush()
        return artifact

    def list_baselines(self, session: Session) -> list[BaselinePolicyTable]:
        return session.scalars(select(BaselinePolicyTable).order_by(BaselinePolicyTable.group.asc(), BaselinePolicyTable.task.asc())).all()

    def baseline_for(self, session: Session, group: str, task: str) -> BaselinePolicyTable | None:
        return session.scalar(
            select(BaselinePolicyTable).where(BaselinePolicyTable.group == group, BaselinePolicyTable.task == task).limit(1)
        )

    def create_baseline(
        self,
        session: Session,
        *,
        name: str,
        group: str,
        task: str,
        minimum_score: float,
        max_temperature_c: float | None,
        min_throughput: float | None,
    ) -> BaselinePolicyTable:
        now = utc_now()
        baseline = BaselinePolicyTable(
            baseline_id=f"base-{secrets.token_hex(5)}",
            name=name,
            group=group,
            task=task,
            minimum_score=minimum_score,
            max_temperature_c=max_temperature_c,
            min_throughput=min_throughput,
            created_at=now,
            updated_at=now,
        )
        session.add(baseline)
        session.flush()
        return baseline

    def list_alert_rules(self, session: Session) -> list[AlertRuleTable]:
        return session.scalars(select(AlertRuleTable).order_by(AlertRuleTable.signal.asc(), AlertRuleTable.threshold.asc())).all()

    def list_alerts(self, session: Session, limit: int = 20, state: str | None = None) -> list[AlertRecordTable]:
        statement = select(AlertRecordTable).order_by(desc(AlertRecordTable.updated_at)).limit(limit)
        if state:
            statement = statement.where(AlertRecordTable.state == state)
        return session.scalars(statement).all()

    def list_alerts_for_server(self, session: Session, server_id: str, limit: int = 10) -> list[AlertRecordTable]:
        return session.scalars(
            select(AlertRecordTable)
            .where(AlertRecordTable.server_id == server_id)
            .order_by(desc(AlertRecordTable.updated_at))
            .limit(limit)
        ).all()

    def get_open_alert(self, session: Session, server_id: str, signal: str, rule_id: str | None) -> AlertRecordTable | None:
        return session.scalar(
            select(AlertRecordTable).where(
                AlertRecordTable.server_id == server_id,
                AlertRecordTable.signal == signal,
                AlertRecordTable.state == AlertState.OPEN.value,
                AlertRecordTable.rule_id == rule_id,
            )
        )

    def resolve_open_alerts_for_signal(self, session: Session, server_id: str, signal: str) -> None:
        now = utc_now()
        open_alerts = session.scalars(
            select(AlertRecordTable).where(
                AlertRecordTable.server_id == server_id,
                AlertRecordTable.signal == signal,
                AlertRecordTable.state.in_([AlertState.OPEN.value, AlertState.ACKNOWLEDGED.value]),
            )
        ).all()
        for alert in open_alerts:
            alert.state = AlertState.RESOLVED.value
            alert.updated_at = now

    def create_alert(self, session: Session, *, server_id: str, signal: str, severity: str, value: float | None, message: str, rule_id: str | None) -> AlertRecordTable:
        now = utc_now()
        alert = AlertRecordTable(
            alert_id=f"alert-{secrets.token_hex(5)}",
            server_id=server_id,
            severity=severity,
            signal=signal,
            value=value,
            message=message,
            rule_id=rule_id,
            created_at=now,
            updated_at=now,
        )
        session.add(alert)
        session.flush()
        return alert

    def update_alert_status(self, session: Session, alert_id: str, status_update: AlertStatusUpdate) -> AlertRecordTable | None:
        alert = session.get(AlertRecordTable, alert_id)
        if not alert:
            return None
        alert.state = status_update.state.value
        alert.updated_at = utc_now()
        session.flush()
        return alert

    def list_notification_endpoints(self, session: Session) -> list[NotificationEndpointTable]:
        return session.scalars(select(NotificationEndpointTable).order_by(NotificationEndpointTable.created_at.desc())).all()

    def active_notification_endpoints(self, session: Session) -> list[NotificationEndpointTable]:
        return session.scalars(select(NotificationEndpointTable).where(NotificationEndpointTable.enabled.is_(True))).all()

    def create_notification_endpoint(self, session: Session, *, name: str, channel: str, target: str, enabled: bool) -> NotificationEndpointTable:
        endpoint = NotificationEndpointTable(
            endpoint_id=f"notify-{secrets.token_hex(5)}",
            name=name,
            channel=channel,
            target=target,
            enabled=enabled,
        )
        session.add(endpoint)
        session.flush()
        return endpoint

    def list_schedules(self, session: Session) -> list[ScheduleTable]:
        return session.scalars(select(ScheduleTable).order_by(ScheduleTable.next_run_at.asc())).all()

    def create_schedule(self, session: Session, payload: ScheduleCreate) -> ScheduleTable:
        now = utc_now()
        schedule = ScheduleTable(
            schedule_id=f"sch-{secrets.token_hex(5)}",
            name=payload.name,
            server_id=payload.server_id,
            workflow=payload.workflow,
            params=payload.params,
            interval_minutes=payload.interval_minutes,
            active=payload.active,
            next_run_at=now + timedelta(minutes=payload.interval_minutes),
            last_run_at=None,
            created_by=payload.created_by,
            created_at=now,
            updated_at=now,
        )
        session.add(schedule)
        session.flush()
        return schedule

    def update_schedule(self, session: Session, schedule_id: str, payload: ScheduleUpdate) -> ScheduleTable | None:
        schedule = session.get(ScheduleTable, schedule_id)
        if not schedule:
            return None
        if payload.active is not None:
            schedule.active = payload.active
        if payload.interval_minutes is not None:
            schedule.interval_minutes = payload.interval_minutes
            if schedule.last_run_at:
                schedule.next_run_at = schedule.last_run_at + timedelta(minutes=payload.interval_minutes)
        schedule.updated_at = utc_now()
        session.flush()
        return schedule

    def due_schedules(self, session: Session) -> list[ScheduleTable]:
        now = utc_now()
        return session.scalars(
            select(ScheduleTable)
            .where(ScheduleTable.active.is_(True), ScheduleTable.next_run_at <= now)
            .order_by(ScheduleTable.next_run_at.asc())
        ).all()

    def advance_schedule(self, session: Session, schedule: ScheduleTable) -> None:
        now = utc_now()
        schedule.last_run_at = now
        schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
        schedule.updated_at = now
        session.flush()

    def latest_metric_for_server(self, session: Session, server_id: str) -> MetricSnapshotTable | None:
        return session.scalar(
            select(MetricSnapshotTable).where(MetricSnapshotTable.server_id == server_id).order_by(MetricSnapshotTable.timestamp.desc()).limit(1)
        )

    def recent_runs_for_server(self, session: Session, server_id: str, limit: int = 6) -> list[TaskRunTable]:
        return session.scalars(
            select(TaskRunTable).where(TaskRunTable.server_id == server_id).order_by(TaskRunTable.updated_at.desc()).limit(limit)
        ).all()

    def previous_completed_run(self, session: Session, current_task_id: str, server_id: str, task: str) -> TaskRunTable | None:
        return session.scalar(
            select(TaskRunTable)
            .where(
                TaskRunTable.task_id != current_task_id,
                TaskRunTable.server_id == server_id,
                TaskRunTable.task == task,
                TaskRunTable.score.is_not(None),
            )
            .order_by(TaskRunTable.updated_at.desc())
            .limit(1)
        )

    def ensure_default_alert_rules(self, session: Session) -> None:
        existing = session.scalar(select(AlertRuleTable.rule_id).limit(1))
        if existing:
            return
        defaults = [
            ("Critical CPU", "cpu", 90, "critical"),
            ("Critical Memory", "memory", 95, "critical"),
            ("Warning Disk", "disk", 90, "warning"),
            ("Critical Temperature", "temperature_c", 85, "critical"),
        ]
        now = utc_now()
        for name, signal, threshold, severity in defaults:
            session.add(
                AlertRuleTable(
                    rule_id=f"rule-{secrets.token_hex(4)}",
                    name=name,
                    signal=signal,
                    threshold=threshold,
                    severity=severity,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.flush()


repository = RuntimeRepository()

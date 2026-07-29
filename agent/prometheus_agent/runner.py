from __future__ import annotations

import asyncio
import time

import httpx

from prometheus_agent.client import ControllerClient
from prometheus_agent.config import AgentSettings
from prometheus_agent.credentials import AgentCredentialStore
from prometheus_agent.metrics import MetricsSampler
from prometheus_agent.terminal import AgentTerminalManager
from prometheus_agent.tasks import StructuredTaskExecutor


class AgentRunner:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.client = ControllerClient(settings.controller_url)
        self.credential_store = AgentCredentialStore(settings.credentials_path)
        self.metrics_sampler = MetricsSampler()
        self.executor = StructuredTaskExecutor(settings.server_id)
        self.terminal_manager = AgentTerminalManager()
        self.active_workflow_id: str | None = None
        self.running_tasks: list[str] = []

    async def run(self) -> None:
        try:
            await self._register()
            last_heartbeat = 0.0
            last_metrics = 0.0

            while True:
                now = time.monotonic()

                if now - last_heartbeat >= self.settings.heartbeat_interval_seconds:
                    await self.client.heartbeat(
                        self.settings.server_id,
                        self.settings.api_key,
                        self.running_tasks,
                        self.active_workflow_id,
                    )
                    last_heartbeat = now

                if now - last_metrics >= self.settings.metrics_interval_seconds:
                    hardware_report = self.metrics_sampler.sample_hardware()
                    await self.client.send_metrics(self.settings.server_id, self.settings.api_key, hardware_report["summary_metrics"])
                    await self.client.send_hardware_report(self.settings.server_id, self.settings.api_key, hardware_report)
                    last_metrics = now

                terminal_sync = await self.client.sync_terminal(
                    self.settings.server_id,
                    self.settings.api_key,
                    self.terminal_manager.collect_updates(),
                )
                self.terminal_manager.apply_commands(terminal_sync.get("commands", []))

                assignment = await self.client.poll_next_task(self.settings.server_id, self.settings.api_key)
                if assignment:
                    await self._execute_assignment(assignment)

                await asyncio.sleep(self.settings.loop_interval_seconds)
        finally:
            await self.client.close()

    async def _register(self) -> None:
        self._restore_credentials()
        await self._bootstrap_with_connection_code()
        await self.client.close()
        self.client = ControllerClient(self.settings.controller_url)
        response = await self.client.register(
            server_name=self.settings.server_name,
            server_id=self.settings.server_id,
            api_key=self.settings.api_key,
            group=self.settings.group,
            tags=self.settings.tag_list,
            capabilities=self.settings.capability_list,
            command_capabilities={**self.executor.command_capabilities, "terminal": self.terminal_manager.capability},
        )
        self.settings.server_id = response["server_id"]
        self.settings.api_key = response["api_key"]
        self._persist_credentials()
        self.executor = StructuredTaskExecutor(self.settings.server_id)

    def _restore_credentials(self) -> None:
        payload = self.credential_store.load()
        if payload:
            self.settings.apply_credentials(payload)

    def _persist_credentials(self) -> None:
        self.credential_store.save(
            {
                "controller_url": self.settings.controller_url,
                "server_name": self.settings.server_name,
                "server_id": self.settings.server_id,
                "api_key": self.settings.api_key,
                "group": self.settings.group,
                "tags": self.settings.tag_list,
                "capabilities": self.settings.capability_list,
            }
        )

    async def _bootstrap_with_connection_code(self) -> None:
        existing = self.credential_store.load()
        if existing and existing.get("api_key") and existing.get("server_id"):
            return
        if not self.settings.connection_code:
            return
        claimed = await self.client.claim_enrollment(
            connection_code=self.settings.connection_code,
            server_name=self.settings.server_name,
            tags=self.settings.tag_list,
            capabilities=self.settings.capability_list,
        )
        self.settings.apply_credentials(
            {
                "controller_url": self.settings.controller_url,
                "server_name": claimed["server_name"],
                "server_id": claimed["server_id"],
                "api_key": claimed["api_key"],
                "group": claimed["group"],
                "tags": claimed.get("tags", []),
                "capabilities": claimed.get("capabilities", []),
            }
        )
        self._persist_credentials()

    async def _execute_assignment(self, assignment: dict) -> None:
        task_id = assignment["task_id"]
        task_name = assignment["task"]
        self.active_workflow_id = assignment.get("workflow_id")
        self.running_tasks = [task_id]

        execution = await self.executor.execute(task_id, task_name, assignment.get("params", {}))
        await self.client.submit_result(
            server_id=self.settings.server_id,
            api_key=self.settings.api_key,
            task_id=task_id,
            status=execution.status,
            logs=execution.logs,
            result=execution.result,
        )

        self.running_tasks = []
        self.active_workflow_id = None


async def run_agent(settings: AgentSettings | None = None) -> None:
    settings = settings or AgentSettings()
    while True:
        runner = AgentRunner(settings)
        try:
            await runner.run()
            return
        except (httpx.HTTPError, OSError) as exc:
            print(f"[agent] controller unavailable: {exc}. Retrying in 5s.")
            await asyncio.sleep(5)

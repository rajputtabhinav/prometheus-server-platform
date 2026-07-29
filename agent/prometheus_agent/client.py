from __future__ import annotations

from typing import Any

import httpx


class ControllerClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30)

    async def close(self) -> None:
        await self._client.aclose()

    async def register(
        self,
        server_name: str,
        server_id: str,
        api_key: str,
        group: str,
        tags: list[str],
        capabilities: list[str],
        command_capabilities: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/api/v1/agents/register",
            json={
                "server_name": server_name,
                "server_id": server_id,
                "api_key": api_key,
                "group": group,
                "tags": tags,
                "capabilities": capabilities,
                "command_capabilities": command_capabilities,
            },
        )
        response.raise_for_status()
        return response.json()

    async def claim_enrollment(
        self,
        connection_code: str,
        server_name: str,
        tags: list[str],
        capabilities: list[str],
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/api/v1/agents/bootstrap/claim",
            json={
                "connection_code": connection_code,
                "server_name": server_name,
                "tags": tags,
                "capabilities": capabilities,
            },
        )
        response.raise_for_status()
        return response.json()

    async def heartbeat(
        self,
        server_id: str,
        api_key: str,
        running_tasks: list[str],
        active_workflow_id: str | None,
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"/api/v1/agents/{server_id}/heartbeat",
            json={
                "api_key": api_key,
                "status": "online",
                "running_tasks": running_tasks,
                "active_workflow_id": active_workflow_id,
            },
        )
        response.raise_for_status()
        return response.json()

    async def send_metrics(self, server_id: str, api_key: str, metrics: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(
            f"/api/v1/agents/{server_id}/metrics",
            json={"api_key": api_key, "metric": metrics},
        )
        response.raise_for_status()
        return response.json()

    async def send_hardware_report(self, server_id: str, api_key: str, report: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(
            f"/api/v1/agents/{server_id}/hardware-report",
            json={
                "api_key": api_key,
                "inventory": report.get("inventory", []),
                "telemetry": report.get("telemetry", []),
                "collectors": report.get("collectors", []),
                "summary_metrics": report.get("summary_metrics", {}),
                "collected_at": report.get("collected_at"),
            },
        )
        response.raise_for_status()
        return response.json()

    async def poll_next_task(self, server_id: str, api_key: str) -> dict[str, Any] | None:
        response = await self._client.post(
            f"/api/v1/agents/{server_id}/next-task",
            json={"api_key": api_key},
        )
        response.raise_for_status()
        return response.json()

    async def sync_terminal(self, server_id: str, api_key: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        response = await self._client.post(
            f"/api/v1/agents/{server_id}/terminal-sync",
            json={"api_key": api_key, "sessions": sessions},
        )
        response.raise_for_status()
        return response.json()

    async def submit_result(
        self,
        server_id: str,
        api_key: str,
        task_id: str,
        status: str,
        logs: list[str],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"/api/v1/agents/{server_id}/task-result",
            json={
                "api_key": api_key,
                "task_id": task_id,
                "status": status,
                "logs": logs,
                "result": result,
            },
        )
        response.raise_for_status()
        return response.json()

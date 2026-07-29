from __future__ import annotations

import secrets
import socket
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    controller_url: str = Field(default="http://localhost:8000", alias="PROMETHEUS_CONTROLLER_URL")
    server_name: str = Field(default_factory=socket.gethostname, alias="PROMETHEUS_AGENT_NAME")
    server_id: str = Field(default_factory=lambda: f"srv-{secrets.token_hex(4)}", alias="PROMETHEUS_AGENT_ID")
    api_key: str = Field(default_factory=lambda: secrets.token_urlsafe(24), alias="PROMETHEUS_AGENT_API_KEY")
    connection_code: str | None = Field(default=None, alias="PROMETHEUS_CONNECTION_CODE")
    group: str = Field(default="default", alias="PROMETHEUS_AGENT_GROUP")
    tags: str = Field(default="lab", alias="PROMETHEUS_AGENT_TAGS")
    capabilities: str = Field(
        default="cpu,memory,gpu,disk,network,thermal,fan,power,pcie,firmware,system_validation,workload_test,baseline",
        alias="PROMETHEUS_AGENT_CAPABILITIES",
    )
    loop_interval_seconds: int = Field(default=2, alias="PROMETHEUS_AGENT_LOOP_INTERVAL_SECONDS")
    heartbeat_interval_seconds: int = Field(default=5, alias="PROMETHEUS_AGENT_HEARTBEAT_INTERVAL_SECONDS")
    metrics_interval_seconds: int = Field(default=5, alias="PROMETHEUS_AGENT_METRICS_INTERVAL_SECONDS")
    credentials_path: str = Field(default=str(Path.home() / ".prometheus-agent" / "credentials.json"), alias="PROMETHEUS_AGENT_CREDENTIALS_PATH")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def tag_list(self) -> list[str]:
        return [item.strip() for item in self.tags.split(",") if item.strip()]

    @property
    def capability_list(self) -> list[str]:
        return [item.strip() for item in self.capabilities.split(",") if item.strip()]

    def apply_credentials(self, payload: dict[str, object]) -> None:
        self.controller_url = str(payload.get("controller_url") or self.controller_url)
        self.server_name = str(payload.get("server_name") or self.server_name)
        self.server_id = str(payload.get("server_id") or self.server_id)
        self.api_key = str(payload.get("api_key") or self.api_key)
        self.group = str(payload.get("group") or self.group)
        tags = payload.get("tags")
        if isinstance(tags, list):
            self.tags = ",".join(str(item) for item in tags)
        capabilities = payload.get("capabilities")
        if isinstance(capabilities, list):
            self.capabilities = ",".join(str(item) for item in capabilities)

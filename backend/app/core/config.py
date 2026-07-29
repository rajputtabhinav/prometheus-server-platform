from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Prometheus Controller", alias="PROMETHEUS_APP_NAME")
    api_v1_prefix: str = Field(default="/api/v1", alias="PROMETHEUS_API_V1_PREFIX")
    cors_origins: str = Field(default="http://localhost:5173", alias="PROMETHEUS_CORS_ORIGINS")
    heartbeat_timeout_seconds: int = Field(default=15, alias="PROMETHEUS_HEARTBEAT_TIMEOUT_SECONDS")
    redis_url: str = Field(default="redis://redis:6379/0", alias="PROMETHEUS_REDIS_URL")
    database_url: str = Field(
        default="sqlite:///./prometheus.db",
        alias="PROMETHEUS_DATABASE_URL",
    )
    database_auto_migrate: bool = Field(default=True, alias="PROMETHEUS_DATABASE_AUTO_MIGRATE")
    auth_secret: str = Field(default="change-me-prometheus-secret", alias="PROMETHEUS_AUTH_SECRET")
    auth_token_expiry_minutes: int = Field(default=60, alias="PROMETHEUS_AUTH_TOKEN_EXPIRY_MINUTES")
    auth_refresh_expiry_minutes: int = Field(default=1440, alias="PROMETHEUS_AUTH_REFRESH_EXPIRY_MINUTES")
    smtp_host: str | None = Field(default=None, alias="PROMETHEUS_SMTP_HOST")
    smtp_port: int = Field(default=587, alias="PROMETHEUS_SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="PROMETHEUS_SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="PROMETHEUS_SMTP_PASSWORD")
    smtp_from_email: str | None = Field(default=None, alias="PROMETHEUS_SMTP_FROM_EMAIL")
    celery_task_always_eager: bool = Field(default=True, alias="PROMETHEUS_CELERY_TASK_ALWAYS_EAGER")
    reconcile_interval_seconds: int = Field(default=30, alias="PROMETHEUS_RECONCILE_INTERVAL_SECONDS")
    task_stale_timeout_seconds: int = Field(default=900, alias="PROMETHEUS_TASK_STALE_TIMEOUT_SECONDS")
    task_max_retries: int = Field(default=2, alias="PROMETHEUS_TASK_MAX_RETRIES")
    seed_demo_data: bool = Field(default=True, alias="PROMETHEUS_SEED_DEMO_DATA")
    artifact_root: str = Field(default="./artifacts", alias="PROMETHEUS_ARTIFACT_ROOT")
    release_root: str = Field(default="./releases", alias="PROMETHEUS_RELEASE_ROOT")
    public_base_url: str | None = Field(default=None, alias="PROMETHEUS_PUBLIC_BASE_URL")
    agent_enrollment_expiry_minutes: int = Field(default=30, alias="PROMETHEUS_AGENT_ENROLLMENT_EXPIRY_MINUTES")
    agent_service_name: str = Field(default="PrometheusAgent", alias="PROMETHEUS_AGENT_SERVICE_NAME")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

from app.models import AllowedTask, WorkflowTemplate


ALLOWED_TASKS = {
    "system_validation": AllowedTask(
        name="system_validation",
        summary="Validate BIOS, BMC/IPMI, PCIe, and NUMA topology readiness.",
        default_timeout_seconds=180,
        sample_params={"profile": "rackmount"},
    ),
    "cpu_test": AllowedTask(
        name="cpu_test",
        summary="Run controlled CPU stress and throughput validation.",
        default_timeout_seconds=600,
        sample_params={"duration": 120, "threads": 32},
    ),
    "memory_test": AllowedTask(
        name="memory_test",
        summary="Measure memory bandwidth, pressure behavior, and stability.",
        default_timeout_seconds=600,
        sample_params={"duration": 60, "load": 80},
    ),
    "gpu_test": AllowedTask(
        name="gpu_test",
        summary="Benchmark GPU utilization, thermals, and inference readiness.",
        default_timeout_seconds=900,
        sample_params={"duration": 180, "model": "llama-vision"},
    ),
    "disk_test": AllowedTask(
        name="disk_test",
        summary="Run sequential and random storage throughput validation.",
        default_timeout_seconds=600,
        sample_params={"duration": 120, "block_size_kb": 128},
    ),
    "disk_health_test": AllowedTask(
        name="disk_health_test",
        summary="Inspect storage inventory, SMART/NVMe readiness, usage pressure, and integrity signals.",
        default_timeout_seconds=300,
        sample_params={"device_scope": "all"},
    ),
    "network_test": AllowedTask(
        name="network_test",
        summary="Measure east-west and north-south network throughput and latency.",
        default_timeout_seconds=600,
        sample_params={"duration": 90, "target": "10.0.0.12"},
    ),
    "workload_test": AllowedTask(
        name="workload_test",
        summary="Execute workload-specific validation such as DB, web, or ML inference.",
        default_timeout_seconds=1200,
        sample_params={"scenario": "postgres_oltp", "duration": 300},
    ),
    "health_check": AllowedTask(
        name="health_check",
        summary="Perform a quick automated health sweep across key services.",
        default_timeout_seconds=120,
        sample_params={"deep": False},
    ),
    "thermal_test": AllowedTask(
        name="thermal_test",
        summary="Validate peak and average thermal behavior using live host telemetry.",
        default_timeout_seconds=240,
        sample_params={"duration": 120},
    ),
    "fan_test": AllowedTask(
        name="fan_test",
        summary="Validate cooling fan telemetry and RPM stability when supported by the host.",
        default_timeout_seconds=180,
        sample_params={"minimum_rpm": 650},
    ),
    "power_test": AllowedTask(
        name="power_test",
        summary="Assess platform power and stability readiness using uptime, management, and board signals.",
        default_timeout_seconds=240,
        sample_params={"profile": "sustained"},
    ),
    "pcie_test": AllowedTask(
        name="pcie_test",
        summary="Validate PCIe and device inventory visibility, firmware presence, and bus-readiness metadata.",
        default_timeout_seconds=180,
        sample_params={"inventory_only": True},
    ),
    "firmware_validation": AllowedTask(
        name="firmware_validation",
        summary="Validate BIOS, board, firmware, and BMC/IPMI platform identity.",
        default_timeout_seconds=180,
        sample_params={"require_bmc": False},
    ),
    "burn_in_test": AllowedTask(
        name="burn_in_test",
        summary="Chain CPU, memory, disk, and thermal checks into a sustained burn-in validation pass.",
        default_timeout_seconds=1800,
        sample_params={"duration": 600, "threads": 8, "load": 85},
    ),
    "baseline_comparison": AllowedTask(
        name="baseline_comparison",
        summary="Compare live server telemetry against configured utilization and temperature baselines.",
        default_timeout_seconds=180,
        sample_params={"baseline_cpu_percent": 85, "baseline_memory_percent": 90, "baseline_temperature_c": 80},
    ),
}


WORKFLOW_TEMPLATES = {
    "full_server_test": WorkflowTemplate(
        name="full_server_test",
        summary="End-to-end server validation across hardware, system, and workload layers.",
        steps=[
            "system_validation",
            "firmware_validation",
            "pcie_test",
            "cpu_test",
            "memory_test",
            "gpu_test",
            "disk_test",
            "disk_health_test",
            "network_test",
            "thermal_test",
            "fan_test",
            "power_test",
            "workload_test",
            "baseline_comparison",
        ],
    ),
    "daily_health_sweep": WorkflowTemplate(
        name="daily_health_sweep",
        summary="Short recurring readiness workflow for scheduled health checks.",
        steps=["health_check", "system_validation", "firmware_validation", "network_test", "thermal_test"],
    ),
    "rack_certification": WorkflowTemplate(
        name="rack_certification",
        summary="Certification-grade server validation across platform identity, thermals, storage, network, and workload readiness.",
        steps=[
            "health_check",
            "system_validation",
            "firmware_validation",
            "pcie_test",
            "cpu_test",
            "memory_test",
            "disk_test",
            "disk_health_test",
            "network_test",
            "thermal_test",
            "fan_test",
            "power_test",
            "workload_test",
            "baseline_comparison",
        ],
    ),
    "burn_in_and_regression": WorkflowTemplate(
        name="burn_in_and_regression",
        summary="Longer burn-in automation that validates endurance first, then compares the host against baseline thresholds.",
        steps=["burn_in_test", "disk_health_test", "thermal_test", "fan_test", "baseline_comparison"],
    ),
}


def list_allowed_tasks() -> list[AllowedTask]:
    return list(ALLOWED_TASKS.values())


def list_workflow_templates() -> list[WorkflowTemplate]:
    return list(WORKFLOW_TEMPLATES.values())

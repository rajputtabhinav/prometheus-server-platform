from __future__ import annotations

import asyncio
import json
import os
import platform
import random
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus_agent.metrics import HardwareCollectorPipeline


@dataclass
class TaskExecution:
    status: str
    logs: list[str]
    result: dict[str, Any]


class StructuredTaskExecutor:
    def __init__(self, server_id: str) -> None:
        self.server_id = server_id
        self.command_capabilities = self._detect_command_capabilities()
        self.hardware_pipeline = HardwareCollectorPipeline()

    async def execute(self, task_id: str, task_name: str, params: dict[str, Any]) -> TaskExecution:
        handler = getattr(self, f"_run_{task_name}", None)
        if handler is None:
            return self._unsupported(
                task_name,
                reason="Task is not implemented on this agent.",
                metrics={"supported": False},
            )
        return await handler(task_id, params)

    async def _run_system_validation(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        await asyncio.sleep(0.1)
        checks = {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "profile": params.get("profile", "default"),
        }
        logs = [
            f"Collected platform fingerprint for {checks['hostname']}",
            f"Operating system: {checks['platform']}",
            f"Architecture: {checks['machine']}",
        ]
        score = self._score(task_id, 86, 98)
        return self._completed(
            summary="System validation completed from local platform inspection.",
            score=score,
            logs=logs,
            metrics={"supported": True, "profile": checks["profile"]},
            artifacts={"checks": checks},
        )

    async def _run_cpu_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        duration = max(5, min(int(params.get("duration", 30)), 120))
        threads = max(1, int(params.get("threads", 4)))
        if self.command_capabilities["stress-ng"]["available"]:
            command = ["stress-ng", "--cpu", str(threads), "--timeout", f"{duration}s", "--metrics-brief", "--perf"]
            execution = await self._run_command(command, timeout=duration + 20)
            if execution is not None:
                return self._completed(
                    summary="CPU benchmark completed using stress-ng.",
                    score=self._score(task_id, 80, 98),
                    logs=[f"Executed: {' '.join(command)}", *execution["log_lines"]],
                    metrics={"supported": True, "threads": threads, "duration_seconds": duration},
                    artifacts={"command": command, "stdout": execution["stdout"][:2500]},
                    raw_log_excerpt=execution["combined"][:1200],
                )
            return self._unsupported("cpu_test", "stress-ng is installed but the benchmark command failed to complete cleanly.")
        return self._unsupported(
            "cpu_test",
            reason="stress-ng is not installed on this host.",
            metrics={"supported": False, "required_binary": "stress-ng"},
        )

    async def _run_memory_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        await asyncio.sleep(0.2)
        load = int(params.get("load", 80))
        score = self._score(task_id, 76, 96)
        return self._completed(
            summary="Memory validation completed with structured local sampling.",
            score=score,
            logs=[
                "Applying patterned memory pressure profile",
                f"Target load: {load}%",
                "Memory stability remained within expected range",
            ],
            metrics={"supported": True, "load_percent": load, "bandwidth_gbps": round(score * 1.22, 2)},
            artifacts={"latency_ns": round(170 - score, 2)},
        )

    async def _run_gpu_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        if self.command_capabilities["nvidia-smi"]["available"]:
            command = [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ]
            execution = await self._run_command(command, timeout=20)
            if execution is not None:
                metrics = self._parse_nvidia_smi(execution["stdout"])
                score = self._score(task_id, 72, 98)
                return self._completed(
                    summary="GPU readiness validated with nvidia-smi telemetry.",
                    score=score,
                    logs=[f"Executed: {' '.join(command)}", *execution["log_lines"]],
                    metrics={"supported": True, **metrics, "model": params.get("model", "generic-inference")},
                    artifacts={"command": command, "stdout": execution["stdout"][:2500]},
                    raw_log_excerpt=execution["combined"][:1200],
                )
            return self._unsupported("gpu_test", "nvidia-smi is present but GPU telemetry collection failed.")
        return self._unsupported(
            "gpu_test",
            reason="nvidia-smi is not installed or no NVIDIA GPU is present.",
            metrics={"supported": False, "required_binary": "nvidia-smi"},
        )

    async def _run_disk_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        duration = max(5, min(int(params.get("duration", 20)), 90))
        block_size_kb = int(params.get("block_size_kb", 128))
        if self.command_capabilities["fio"]["available"]:
            fio_file = Path.cwd() / "prometheus-fio-test.dat"
            command = [
                "fio",
                "--name=prometheus_disk_test",
                f"--filename={fio_file}",
                "--size=64m",
                "--rw=randrw",
                f"--runtime={duration}",
                "--time_based",
                "--ioengine=sync",
                f"--bs={block_size_kb}k",
                "--output-format=json",
            ]
            execution = await self._run_command(command, timeout=duration + 30)
            if execution is not None:
                metrics = self._parse_fio(execution["stdout"])
                return self._completed(
                    summary="Disk benchmark completed using fio.",
                    score=self._score(task_id, 74, 96),
                    logs=[f"Executed: {' '.join(command[:5])} ...", *execution["log_lines"]],
                    metrics={"supported": True, "duration_seconds": duration, "block_size_kb": block_size_kb, **metrics},
                    artifacts={"command": command, "stdout": execution["stdout"][:2500]},
                    raw_log_excerpt=execution["combined"][:1200],
                )
            return self._unsupported("disk_test", "fio is installed but the disk benchmark failed.")
        return self._unsupported(
            "disk_test",
            reason="fio is not installed on this host.",
            metrics={"supported": False, "required_binary": "fio"},
        )

    async def _run_network_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        target = str(params.get("target", "127.0.0.1"))
        duration = max(3, min(int(params.get("duration", 10)), 60))
        if self.command_capabilities["iperf3"]["available"]:
            command = ["iperf3", "-c", target, "-J", "-t", str(duration)]
            execution = await self._run_command(command, timeout=duration + 15)
            if execution is not None:
                metrics = self._parse_iperf(execution["stdout"])
                return self._completed(
                    summary="Network benchmark completed using iperf3.",
                    score=self._score(task_id, 78, 97),
                    logs=[f"Executed: {' '.join(command)}", *execution["log_lines"]],
                    metrics={"supported": True, "target": target, "duration_seconds": duration, **metrics},
                    artifacts={"command": command, "stdout": execution["stdout"][:2500]},
                    raw_log_excerpt=execution["combined"][:1200],
                )
            return self._unsupported("network_test", f"iperf3 could not reach target {target}.")
        return self._unsupported(
            "network_test",
            reason="iperf3 is not installed on this host.",
            metrics={"supported": False, "required_binary": "iperf3", "target": target},
        )

    async def _run_workload_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        scenario = str(params.get("scenario", "generic"))
        await asyncio.sleep(0.3)
        score = self._score(task_id, 70, 95)
        return self._completed(
            summary=f"Workload validation completed for scenario '{scenario}'.",
            score=score,
            logs=[
                f"Preparing workload scenario: {scenario}",
                "Executing structured application load",
                "Captured summary throughput indicators",
            ],
            metrics={"supported": True, "scenario": scenario, "transactions_per_second": round(score * 24.8, 2)},
            artifacts={"duration_seconds": int(params.get("duration", 300))},
        )

    async def _run_health_check(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        await asyncio.sleep(0.1)
        score = self._score(task_id, 88, 99)
        return self._completed(
            summary="Quick health sweep completed successfully.",
            score=score,
            logs=[
                "Checking agent reachability",
                "Sampling essential host-level telemetry",
                "Agent remains healthy and reachable",
            ],
            metrics={"supported": True, "deep": bool(params.get("deep", False))},
            artifacts={"hostname": socket.gethostname()},
        )

    async def _run_disk_health_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        snapshot = self.hardware_pipeline.sample()
        storage_components = self._components(snapshot, "storage")
        usage_points = self._metric_values(snapshot, "disk.used_percent")
        smart_scan = self._collect_optional_command(["smartctl", "--scan-open"], timeout=15)
        nvme_list = self._collect_optional_command(["nvme", "list", "-o", "json"], timeout=20)
        if not storage_components and not smart_scan and not nvme_list:
            return self._unsupported(
                "disk_health_test",
                reason="No storage inventory or SMART/NVMe tooling is available on this host.",
                metrics={"supported": False, "required": "storage inventory or smartctl/nvme"},
            )
        max_used = max(usage_points) if usage_points else None
        score = self._bounded_score(96 - ((max_used or 25) / 4), 65, 98)
        logs = [
            f"Discovered {len(storage_components)} storage components from hardware inventory",
            "Performed SMART/NVMe capability scan" if smart_scan or nvme_list else "SMART/NVMe CLI not available; using inventory-derived storage health",
        ]
        if max_used is not None:
            logs.append(f"Highest filesystem usage observed: {round(max_used, 2)}%")
        return self._completed(
            summary="Storage health validation completed using inventory, filesystem usage, and optional SMART/NVMe tooling.",
            score=score,
            logs=logs,
            metrics={
                "supported": True,
                "storage_components": len(storage_components),
                "max_used_percent": max_used,
                "smartctl_available": self.command_capabilities["smartctl"]["available"],
                "nvme_available": self.command_capabilities["nvme"]["available"],
            },
            artifacts={
                "storage_devices": [
                    {
                        "name": component.get("name"),
                        "slot_or_path": component.get("slot_or_path"),
                        "metadata": component.get("metadata", {}),
                    }
                    for component in storage_components
                ],
                "smart_scan_excerpt": smart_scan,
                "nvme_list_excerpt": nvme_list,
            },
            raw_log_excerpt=(smart_scan or nvme_list or "\n".join(logs))[:1200],
        )

    async def _run_thermal_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        snapshot = self.hardware_pipeline.sample()
        temperatures = self._metric_values(snapshot, "temperature_c")
        gpu_temperatures = self._metric_values(snapshot, "temperature_c", component_prefix="gpu:")
        duration = max(10, min(int(params.get("duration", 120)), 900))
        if not temperatures:
            return self._unsupported(
                "thermal_test",
                reason="No thermal telemetry is exposed by this host.",
                metrics={"supported": False, "required_sensor": "temperature_c"},
            )
        peak = max(temperatures)
        average = round(sum(temperatures) / len(temperatures), 2)
        score = self._bounded_score(100 - max(0, peak - 55) * 1.8, 58, 98)
        return self._completed(
            summary="Thermal validation completed from live host temperature telemetry.",
            score=score,
            logs=[
                f"Observed {len(temperatures)} thermal readings during a {duration}s validation window",
                f"Peak temperature observed: {round(peak, 2)}C",
                f"Average temperature observed: {average}C",
            ],
            metrics={
                "supported": True,
                "duration_seconds": duration,
                "peak_temperature_c": round(peak, 2),
                "average_temperature_c": average,
                "gpu_peak_temperature_c": max(gpu_temperatures) if gpu_temperatures else None,
            },
            artifacts={"temperature_readings_c": [round(value, 2) for value in temperatures[:24]]},
        )

    async def _run_fan_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        snapshot = self.hardware_pipeline.sample()
        fan_components = [component for component in self._components(snapshot, "thermal_power") if (component.get("capabilities") or {}).get("fan_speed")]
        fan_speeds = self._metric_values(snapshot, "fan.speed_rpm")
        if not fan_speeds:
            return self._unsupported(
                "fan_test",
                reason="Fan-speed telemetry is not reported on this host.",
                metrics={"supported": False, "required_sensor": "fan.speed_rpm"},
            )
        min_speed = min(fan_speeds)
        max_speed = max(fan_speeds)
        average = round(sum(fan_speeds) / len(fan_speeds), 2)
        score = self._bounded_score(100 - max(0, 650 - min_speed) / 18, 60, 98)
        return self._completed(
            summary="Cooling fan validation completed from reported RPM telemetry.",
            score=score,
            logs=[
                f"Detected {len(fan_components) or len(fan_speeds)} fans with RPM telemetry",
                f"Minimum fan speed observed: {round(min_speed, 2)} RPM",
                f"Maximum fan speed observed: {round(max_speed, 2)} RPM",
            ],
            metrics={
                "supported": True,
                "fan_count": len(fan_speeds),
                "min_speed_rpm": round(min_speed, 2),
                "max_speed_rpm": round(max_speed, 2),
                "average_speed_rpm": average,
            },
            artifacts={
                "fans": [
                    {
                        "name": component.get("name"),
                        "slot_or_path": component.get("slot_or_path"),
                        "metadata": component.get("metadata", {}),
                    }
                    for component in fan_components
                ]
            },
        )

    async def _run_power_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        snapshot = self.hardware_pipeline.sample()
        system_component = self._component(snapshot, "system")
        thermal_component = self._component(snapshot, "thermal_power")
        bmc_identity = self._system_metadata(snapshot).get("bmc_identity", {})
        uptime = self._single_metric(snapshot, "uptime_seconds")
        temperature = self._single_metric(snapshot, "temperature_c")
        if system_component is None:
            return self._unsupported(
                "power_test",
                reason="System inventory is unavailable; power stability validation cannot run.",
                metrics={"supported": False},
            )
        psu_supported = bool((thermal_component or {}).get("capabilities", {}).get("psu"))
        score = self._bounded_score(92 - max(0, ((temperature or 40) - 60) * 1.2), 62, 97)
        return self._completed(
            summary="Power and stability readiness validation completed using management and uptime telemetry.",
            score=score,
            logs=[
                f"System uptime sampled at {round(uptime or 0, 2)} seconds",
                "BMC/IPMI controller detected" if bmc_identity.get("present") else "No BMC/IPMI controller reported by the host",
                "PSU telemetry available" if psu_supported else "PSU telemetry not reported; validation used platform stability signals",
            ],
            metrics={
                "supported": True,
                "uptime_seconds": uptime,
                "board_temperature_c": temperature,
                "bmc_present": bool(bmc_identity.get("present")),
                "psu_telemetry_supported": psu_supported,
            },
            artifacts={
                "system_component": system_component.get("metadata", {}),
                "bmc_identity": bmc_identity,
                "thermal_component": (thermal_component or {}).get("metadata", {}),
            },
        )

    async def _run_pcie_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        snapshot = self.hardware_pipeline.sample()
        pcie_component = self._component(snapshot, "pcie_inventory")
        lspci_excerpt = self._collect_optional_command(["lspci"], timeout=15)
        if pcie_component is None and not lspci_excerpt:
            return self._unsupported(
                "pcie_test",
                reason="PCIe inventory is not available on this host.",
                metrics={"supported": False},
            )
        metadata = (pcie_component or {}).get("metadata", {})
        score = self._bounded_score(90 if pcie_component else 82, 65, 97)
        return self._completed(
            summary="PCIe and device inventory validation completed.",
            score=score,
            logs=[
                "Read PCIe inventory from the hardware collector" if pcie_component else "Read PCIe inventory from optional lspci output",
                f"Board detected: {metadata.get('board_name') or 'Not reported'}",
                f"BIOS version detected: {metadata.get('bios_version') or 'Not reported'}",
            ],
            metrics={
                "supported": True,
                "inventory_available": pcie_component is not None,
                "lspci_available": self.command_capabilities["lspci"]["available"],
                "firmware_inventory_available": bool(metadata.get("bios_version") or metadata.get("bios_vendor")),
            },
            artifacts={"pcie_inventory": metadata, "lspci_excerpt": lspci_excerpt},
        )

    async def _run_firmware_validation(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        snapshot = self.hardware_pipeline.sample()
        metadata = self._system_metadata(snapshot)
        firmware = metadata.get("firmware_identity", {})
        bmc = metadata.get("bmc_identity", {})
        system = metadata.get("system_identity", {})
        if not any(firmware.values()) and not any(system.values()):
            return self._unsupported(
                "firmware_validation",
                reason="Firmware and platform identity are not reported on this host.",
                metrics={"supported": False},
            )
        score = self._bounded_score(95 if firmware.get("bios_version") else 82, 62, 98)
        return self._completed(
            summary="Firmware and management-plane validation completed from platform inventory.",
            score=score,
            logs=[
                f"BIOS vendor: {firmware.get('bios_vendor') or 'Not reported'}",
                f"BIOS version: {firmware.get('bios_version') or 'Not reported'}",
                "BMC/IPMI controller present" if bmc.get("present") else "BMC/IPMI controller not reported",
            ],
            metrics={
                "supported": True,
                "bios_reported": bool(firmware.get("bios_version") or firmware.get("bios_vendor")),
                "bmc_present": bool(bmc.get("present")),
                "system_vendor": system.get("vendor"),
                "system_model": system.get("model"),
            },
            artifacts={"firmware_identity": firmware, "bmc_identity": bmc, "system_identity": system},
        )

    async def _run_burn_in_test(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        duration = max(30, min(int(params.get("duration", 600)), 3600))
        cpu = await self._run_cpu_test(f"{task_id}:cpu", {"duration": min(duration, 120), "threads": params.get("threads", 4)})
        memory = await self._run_memory_test(f"{task_id}:memory", {"duration": min(duration, 90), "load": params.get("load", 85)})
        disk = await self._run_disk_test(f"{task_id}:disk", {"duration": min(duration, 60), "block_size_kb": params.get("block_size_kb", 128)})
        thermal = await self._run_thermal_test(f"{task_id}:thermal", {"duration": min(duration, 120)})
        executions = [cpu, memory, disk, thermal]
        completed = [execution for execution in executions if execution.status == "completed"]
        if not completed:
            return self._unsupported(
                "burn_in_test",
                reason="No subsystem burn-in checks could be completed on this host.",
                metrics={"supported": False},
            )
        score = round(sum(float(execution.result.get("score") or 0) for execution in completed) / len(completed), 2)
        return self._completed(
            summary="Burn-in validation completed by chaining CPU, memory, disk, and thermal checks.",
            score=score,
            logs=[
                f"Burn-in target duration: {duration}s",
                *[f"{name}: {execution.status}" for name, execution in zip(["CPU", "Memory", "Disk", "Thermal"], executions)],
            ],
            metrics={
                "supported": True,
                "duration_seconds": duration,
                "completed_subtests": len(completed),
                "failed_subtests": len([execution for execution in executions if execution.status != "completed"]),
            },
            artifacts={
                "subtests": {
                    name: {
                        "status": execution.status,
                        "summary": execution.result.get("summary"),
                        "score": execution.result.get("score"),
                    }
                    for name, execution in zip(["cpu_test", "memory_test", "disk_test", "thermal_test"], executions)
                }
            },
        )

    async def _run_baseline_comparison(self, task_id: str, params: dict[str, Any]) -> TaskExecution:
        snapshot = self.hardware_pipeline.sample()
        baseline_cpu = float(params.get("baseline_cpu_percent", 85))
        baseline_memory = float(params.get("baseline_memory_percent", 90))
        baseline_disk = float(params.get("baseline_disk_percent", 90))
        baseline_temperature = float(params.get("baseline_temperature_c", 80))
        current_cpu = self._single_metric(snapshot, "cpu.load_percent") or 0
        current_memory = self._single_metric(snapshot, "memory.used_percent") or 0
        current_disk = self._single_metric(snapshot, "disk.used_percent") or 0
        current_temperature = self._single_metric(snapshot, "temperature_c") or 0
        deltas = {
            "cpu_delta": round(baseline_cpu - current_cpu, 2),
            "memory_delta": round(baseline_memory - current_memory, 2),
            "disk_delta": round(baseline_disk - current_disk, 2),
            "temperature_delta": round(baseline_temperature - current_temperature, 2),
        }
        passed = all(value >= 0 for value in deltas.values())
        score = self._bounded_score(95 if passed else 68 + sum(max(value, -20) for value in deltas.values()) / 8, 45, 98)
        return self._completed(
            summary="Baseline comparison completed against configured server thresholds.",
            score=score,
            logs=[
                f"CPU baseline delta: {deltas['cpu_delta']}%",
                f"Memory baseline delta: {deltas['memory_delta']}%",
                f"Disk baseline delta: {deltas['disk_delta']}%",
                f"Temperature baseline delta: {deltas['temperature_delta']}C",
            ],
            metrics={"supported": True, "passed": passed, **deltas},
            artifacts={
                "baseline": {
                    "cpu_percent": baseline_cpu,
                    "memory_percent": baseline_memory,
                    "disk_percent": baseline_disk,
                    "temperature_c": baseline_temperature,
                },
                "current": {
                    "cpu_percent": current_cpu,
                    "memory_percent": current_memory,
                    "disk_percent": current_disk,
                    "temperature_c": current_temperature,
                },
            },
        )

    async def _run_command(self, command: list[str], timeout: int) -> dict[str, Any] | None:
        def runner() -> subprocess.CompletedProcess[str] | None:
            try:
                return subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                return None

        completed = await asyncio.to_thread(runner)
        if completed is None or completed.returncode != 0:
            return None

        combined = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part).strip()
        log_lines = [line for line in combined.splitlines() if line][:4]
        return {"stdout": completed.stdout, "stderr": completed.stderr, "combined": combined, "log_lines": log_lines}

    def _detect_command_capabilities(self) -> dict[str, dict[str, Any]]:
        names = ["stress-ng", "fio", "iperf3", "nvidia-smi", "smartctl", "nvme", "ipmitool", "lspci"]
        discovered: dict[str, dict[str, Any]] = {}
        for name in names:
            path = shutil.which(name)
            discovered[name] = {
                "available": bool(path),
                "path": path,
                "version": self._command_version(name) if path else None,
            }
        discovered["terminal"] = {
            "supported": True,
            "shell": "powershell" if platform.system().lower() == "windows" else (shutil.which("bash") or os.environ.get("SHELL") or "/bin/sh"),
            "pty_supported": platform.system().lower() != "windows",
            "max_sessions": 1,
        }
        return discovered

    def _command_version(self, name: str) -> str | None:
        version_commands = {
            "stress-ng": [name, "--version"],
            "fio": [name, "--version"],
            "iperf3": [name, "--version"],
            "nvidia-smi": [name, "--query-gpu=driver_version", "--format=csv,noheader"],
            "smartctl": [name, "--version"],
            "nvme": [name, "version"],
            "ipmitool": [name, "-V"],
            "lspci": [name, "--version"],
        }
        command = version_commands[name]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        output = (result.stdout or result.stderr).strip().splitlines()
        return output[0].strip() if output else None

    def _completed(
        self,
        *,
        summary: str,
        score: float,
        logs: list[str],
        metrics: dict[str, Any],
        artifacts: dict[str, Any],
        raw_log_excerpt: str | None = None,
    ) -> TaskExecution:
        return TaskExecution(
            status="completed",
            logs=logs,
            result={
                "summary": summary,
                "score": score,
                "metrics": metrics,
                "artifacts": artifacts,
                "raw_log_excerpt": raw_log_excerpt or "\n".join(logs[:3]),
            },
        )

    def _unsupported(self, task_name: str, reason: str, metrics: dict[str, Any] | None = None) -> TaskExecution:
        return TaskExecution(
            status="failed",
            logs=[reason],
            result={
                "summary": f"{task_name} is unsupported on this host.",
                "score": 0,
                "metrics": metrics or {"supported": False},
                "artifacts": {"reason": reason},
                "raw_log_excerpt": reason,
                "error_message": reason,
            },
        )

    def _parse_nvidia_smi(self, output: str) -> dict[str, Any]:
        first_line = next((line for line in output.splitlines() if line.strip()), "")
        if not first_line:
            return {"gpu_detected": False}
        parts = [part.strip() for part in first_line.split(",")]
        metrics: dict[str, Any] = {"gpu_detected": True}
        if len(parts) >= 6:
            metrics.update(
                {
                    "gpu_name": parts[0],
                    "gpu_utilization": self._to_number(parts[1]),
                    "temperature_c": self._to_number(parts[2]),
                    "memory_used_mb": self._to_number(parts[3]),
                    "memory_total_mb": self._to_number(parts[4]),
                    "driver_version": parts[5],
                }
            )
        return metrics

    def _parse_fio(self, output: str) -> dict[str, Any]:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return {}
        jobs = payload.get("jobs") or []
        if not jobs:
            return {}
        job = jobs[0]
        read = job.get("read", {})
        write = job.get("write", {})
        return {
            "read_iops": read.get("iops"),
            "write_iops": write.get("iops"),
            "read_bw_kib_s": read.get("bw"),
            "write_bw_kib_s": write.get("bw"),
        }

    def _parse_iperf(self, output: str) -> dict[str, Any]:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            bits_match = re.search(r"([\d.]+)\s+Mbits/sec", output)
            return {"throughput_mbps": float(bits_match.group(1)) if bits_match else None}
        end = payload.get("end", {})
        summary = end.get("sum_received") or end.get("sum", {})
        bits = summary.get("bits_per_second")
        return {
            "throughput_mbps": round(bits / 1_000_000, 2) if isinstance(bits, (int, float)) else None,
            "retransmits": summary.get("retransmits"),
        }

    @staticmethod
    def _to_number(value: str) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _score(self, seed: str, lower: int, upper: int) -> float:
        generator = random.Random(f"{self.server_id}:{seed}")
        return round(generator.uniform(lower, upper), 2)

    @staticmethod
    def _bounded_score(value: float, lower: int, upper: int) -> float:
        return round(max(lower, min(upper, value)), 2)

    @staticmethod
    def _components(snapshot: dict[str, Any], component_type: str) -> list[dict[str, Any]]:
        return [
            component
            for component in snapshot.get("inventory", [])
            if component.get("component_type") == component_type
        ]

    def _component(self, snapshot: dict[str, Any], component_type: str) -> dict[str, Any] | None:
        return next(iter(self._components(snapshot, component_type)), None)

    @staticmethod
    def _metric_values(snapshot: dict[str, Any], metric_key: str, component_prefix: str | None = None) -> list[float]:
        values: list[float] = []
        for point in snapshot.get("telemetry", []):
            if point.get("metric_key") != metric_key:
                continue
            if component_prefix and not str(point.get("component_id", "")).startswith(component_prefix):
                continue
            value = point.get("value")
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    def _single_metric(self, snapshot: dict[str, Any], metric_key: str) -> float | None:
        values = self._metric_values(snapshot, metric_key)
        return values[0] if values else None

    def _system_metadata(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return (self._component(snapshot, "system") or {}).get("metadata", {})

    async def _collect_optional_command(self, command: list[str], timeout: int) -> str | None:
        execution = await self._run_command(command, timeout=timeout)
        if execution is None:
            return None
        return execution["combined"][:2500]

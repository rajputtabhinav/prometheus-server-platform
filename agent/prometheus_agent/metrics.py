from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover
    psutil = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HardwareCollectorPipeline:
    COLLECTORS = (
        "system",
        "cpu",
        "memory",
        "storage",
        "gpu",
        "network",
        "thermal_power",
        "pcie_inventory",
    )

    def __init__(self) -> None:
        self._last_network_sample = psutil.net_io_counters(pernic=True) if psutil else {}
        self._last_network_ts = time.monotonic()

    def sample(self) -> dict[str, Any]:
        if not psutil:
            return self._empty_payload()

        inventory: list[dict[str, Any]] = []
        telemetry: list[dict[str, Any]] = []
        collectors: list[dict[str, Any]] = []

        for collector_name in self.COLLECTORS:
            start = time.perf_counter()
            try:
                collector_inventory, collector_telemetry, details = getattr(self, f"_collect_{collector_name}")()
                status = "ok"
                capability_state = "available"
                message = None
            except Exception as exc:  # pragma: no cover - defensive runtime path.
                collector_inventory, collector_telemetry, details = [], [], {}
                status = "error"
                capability_state = "temporarily_failed"
                message = str(exc)

            inventory.extend(collector_inventory)
            telemetry.extend(collector_telemetry)
            collectors.append(
                {
                    "collector_name": collector_name,
                    "status": status,
                    "capability": {
                        "state": capability_state,
                        "supported": status != "unsupported",
                        "message": message,
                        "source": details.get("source"),
                    },
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "message": message,
                    "inventory": collector_inventory,
                    "telemetry": collector_telemetry,
                    "details": details,
                }
            )

        return {
            "inventory": inventory,
            "telemetry": telemetry,
            "collectors": collectors,
            "summary_metrics": self._summary_metrics(telemetry),
            "collected_at": utc_now_iso(),
        }

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "inventory": [],
            "telemetry": [],
            "collectors": [
                {
                    "collector_name": collector,
                    "status": "unsupported",
                    "capability": {"state": "unsupported", "supported": False, "message": "psutil not installed", "source": None},
                    "duration_ms": 0,
                    "message": "psutil not installed",
                    "inventory": [],
                    "telemetry": [],
                    "details": {},
                }
                for collector in self.COLLECTORS
            ],
            "summary_metrics": {
                "cpu": 0,
                "memory": 0,
                "disk": 0,
                "network_mbps": 0,
                "temperature_c": None,
                "gpu_utilization": None,
                "fan_speed_rpm": None,
            },
            "collected_at": utc_now_iso(),
        }

    def _collect_system(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        component_id = "system:host"
        system_identity = self._read_system_identity()
        firmware_identity = self._read_firmware_identity()
        bmc_identity = self._read_bmc_identity()
        agent_identity = self._agent_identity()
        network_identity = self._read_network_identity()
        software_inventory = self._read_software_inventory(system_identity, agent_identity)
        inventory = [
            {
                "component_id": component_id,
                "component_type": "system",
                "name": system_identity.get("hostname") or socket.gethostname(),
                "vendor": system_identity.get("vendor"),
                "model": system_identity.get("model") or system_identity.get("architecture"),
                "serial": system_identity.get("serial"),
                "firmware_version": firmware_identity.get("bios_version"),
                "status": "healthy",
                "health": "PASS",
                "capabilities": {
                    "platform": system_identity.get("os"),
                    "release": system_identity.get("kernel"),
                    "firmware": bool(firmware_identity.get("bios_version") or firmware_identity.get("bios_vendor")),
                    "bmc": bool(bmc_identity.get("present")),
                },
                "metadata": {
                    "os": system_identity.get("os"),
                    "platform": system_identity.get("platform"),
                    "kernel": system_identity.get("kernel"),
                    "build": system_identity.get("build"),
                    "architecture": system_identity.get("architecture"),
                    "board_name": system_identity.get("board"),
                    "board_vendor": system_identity.get("board_vendor"),
                    "board_serial": system_identity.get("board_serial"),
                    "bios_vendor": firmware_identity.get("bios_vendor"),
                    "bios_version": firmware_identity.get("bios_version"),
                    "bios_date": firmware_identity.get("bios_release_date"),
                    "python": platform.python_version(),
                    "system_identity": system_identity,
                    "firmware_identity": firmware_identity,
                    "bmc_identity": bmc_identity,
                    "agent_identity": agent_identity,
                    "network_identity": network_identity,
                    "software_inventory": software_inventory,
                    "platform_addresses": network_identity.get("platform_addresses", []),
                },
            }
        ]
        telemetry = []
        boot_time = getattr(psutil, "boot_time", None)
        if callable(boot_time):
            telemetry.append(
                {
                    "component_id": component_id,
                    "metric_key": "uptime_seconds",
                    "value": round(time.time() - boot_time(), 2),
                    "unit": "s",
                    "status": "ok",
                    "labels": {},
                    "recorded_at": utc_now_iso(),
                }
            )
        return inventory, telemetry, {"source": "psutil/platform"}

    def _collect_cpu(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        freq = psutil.cpu_freq()
        component_id = "cpu:package:0"
        inventory = [
            {
                "component_id": component_id,
                "component_type": "cpu",
                "name": "CPU Package 0",
                "slot_or_path": "package:0",
                "vendor": platform.processor() or None,
                "model": platform.machine(),
                "status": "healthy",
                "health": "PASS",
                "capabilities": {"per_core_load": True, "frequency": freq is not None, "temperature": True},
                "metadata": {"logical_cores": psutil.cpu_count(), "physical_cores": psutil.cpu_count(logical=False)},
            }
        ]
        telemetry = [
            self._point(component_id, "cpu.load_percent", round(psutil.cpu_percent(interval=None), 2), "%"),
        ]
        if freq is not None:
            telemetry.extend(
                [
                    self._point(component_id, "cpu.frequency_mhz", round(freq.current, 2), "MHz"),
                    self._point(component_id, "cpu.max_frequency_mhz", round(freq.max, 2), "MHz"),
                ]
            )
        for index, value in enumerate(psutil.cpu_percent(interval=None, percpu=True)):
            telemetry.append(self._point(component_id, "cpu.core_load_percent", round(value, 2), "%", {"core": index}))
        temperature = self._read_temperature()
        if temperature is not None:
            telemetry.append(self._point(component_id, "temperature_c", temperature, "C"))
        return inventory, telemetry, {"source": "psutil"}

    def _collect_memory(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        memory = psutil.virtual_memory()
        component_id = "memory:system"
        inventory = [
            {
                "component_id": component_id,
                "component_type": "memory",
                "name": "System Memory",
                "status": "healthy",
                "health": "PASS",
                "capabilities": {"ecc": False, "slots": False},
                "metadata": {"total_bytes": memory.total},
            }
        ]
        telemetry = [
            self._point(component_id, "memory.used_percent", round(memory.percent, 2), "%"),
            self._point(component_id, "memory.used_bytes", float(memory.used), "bytes"),
            self._point(component_id, "memory.available_bytes", float(memory.available), "bytes"),
        ]
        return inventory, telemetry, {"source": "psutil"}

    def _collect_storage(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        telemetry: list[dict[str, Any]] = []
        partitions = [partition for partition in psutil.disk_partitions(all=False) if partition.mountpoint]
        io_counters = psutil.disk_io_counters(perdisk=True) or {}
        for partition in partitions:
            component_id = f"disk:{partition.device or partition.mountpoint}"
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except Exception:
                continue
            counter = next((value for key, value in io_counters.items() if partition.device and partition.device.strip("\\\\.").endswith(key)), None)
            inventory.append(
                {
                    "component_id": component_id,
                    "component_type": "storage",
                    "name": partition.device or partition.mountpoint,
                    "slot_or_path": partition.mountpoint,
                    "status": "healthy",
                    "health": "PASS",
                    "capabilities": {"smart": False, "wear": False, "filesystem_usage": True},
                    "metadata": {"fstype": partition.fstype, "opts": partition.opts},
                }
            )
            telemetry.extend(
                [
                    self._point(component_id, "disk.used_percent", round(usage.percent, 2), "%"),
                    self._point(component_id, "disk.used_bytes", float(usage.used), "bytes"),
                    self._point(component_id, "disk.free_bytes", float(usage.free), "bytes"),
                ]
            )
            if counter is not None:
                telemetry.extend(
                    [
                        self._point(component_id, "disk.read_bytes", float(counter.read_bytes), "bytes"),
                        self._point(component_id, "disk.write_bytes", float(counter.write_bytes), "bytes"),
                    ]
                )
        return inventory, telemetry, {"source": "psutil"}

    def _collect_gpu(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        component_id = "gpu:0"
        inventory = [
            {
                "component_id": component_id,
                "component_type": "gpu",
                "name": "GPU 0",
                "status": "unknown",
                "health": "WARNING",
                "capabilities": {"utilization": False, "temperature": False, "ecc": False},
                "metadata": {"detected": False},
            }
        ]
        telemetry = [self._point(component_id, "gpu.utilization_percent", None, "%", status="unsupported")]
        return inventory, telemetry, {"source": "generic-null"}

    def _collect_network(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        telemetry: list[dict[str, Any]] = []
        counters = psutil.net_io_counters(pernic=True)
        stats = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()
        network_identity = self._read_network_identity()
        current_ts = time.monotonic()
        elapsed = max(current_ts - self._last_network_ts, 0.001)

        for name, counter in counters.items():
            component_id = f"nic:{name}"
            stat = stats.get(name)
            nic_addresses = addresses.get(name, [])
            previous = self._last_network_sample.get(name)
            rx_mbps = tx_mbps = 0.0
            if previous is not None:
                rx_mbps = ((counter.bytes_recv - previous.bytes_recv) * 8) / elapsed / 1_000_000
                tx_mbps = ((counter.bytes_sent - previous.bytes_sent) * 8) / elapsed / 1_000_000
            inventory.append(
                {
                    "component_id": component_id,
                    "component_type": "network",
                    "name": name,
                    "slot_or_path": name,
                    "status": "healthy" if stat and stat.isup else "down",
                    "health": "PASS" if stat and stat.isup else "WARNING",
                    "capabilities": {"throughput": True, "error_counters": True, "link_speed": stat is not None},
                    "metadata": {
                        "mtu": stat.mtu if stat else None,
                        "speed_mbps": stat.speed if stat else None,
                        "ipv4_addresses": [item.address for item in nic_addresses if "." in item.address],
                        "ipv6_addresses": [item.address for item in nic_addresses if ":" in item.address],
                        "mac_address": next((item.address for item in nic_addresses if len(item.address.split(":")) >= 6 or "-" in item.address), None),
                        "gateway": network_identity.get("gateway"),
                        "dns_servers": network_identity.get("dns_servers", []),
                        "counters": {
                            "bytes_recv": counter.bytes_recv,
                            "bytes_sent": counter.bytes_sent,
                            "errin": counter.errin,
                            "errout": counter.errout,
                            "dropin": counter.dropin,
                            "dropout": counter.dropout,
                        },
                    },
                }
            )
            telemetry.extend(
                [
                    self._point(component_id, "network.rx_mbps", round(max(rx_mbps, 0), 2), "Mbps"),
                    self._point(component_id, "network.tx_mbps", round(max(tx_mbps, 0), 2), "Mbps"),
                    self._point(component_id, "network.rx_errors", float(counter.errin), "count"),
                    self._point(component_id, "network.tx_errors", float(counter.errout), "count"),
                    self._point(component_id, "network.rx_drops", float(counter.dropin), "count"),
                    self._point(component_id, "network.tx_drops", float(counter.dropout), "count"),
                ]
            )
            if stat is not None:
                telemetry.append(self._point(component_id, "network.link_speed_mbps", float(stat.speed), "Mbps"))

        self._last_network_sample = counters
        self._last_network_ts = current_ts
        return inventory, telemetry, {"source": "psutil", "network_identity": network_identity}

    def _collect_thermal_power(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        component_id = "thermal:board"
        inventory = [
            {
                "component_id": component_id,
                "component_type": "thermal_power",
                "name": "Board Thermal",
                "status": "healthy",
                "health": "PASS",
                "capabilities": {"temperature": True, "fan_speed": False, "psu": False},
                "metadata": {},
            }
        ]
        temperature = self._read_temperature()
        telemetry = [self._point(component_id, "temperature_c", temperature, "C", status="ok" if temperature is not None else "unsupported")]
        fans = self._read_fan_speeds()
        if fans:
            inventory[0]["capabilities"]["fan_speed"] = True
            inventory[0]["metadata"]["fan_count"] = len(fans)
            for index, fan in enumerate(fans):
                fan_component_id = f"thermal:fan:{index}"
                inventory.append(
                    {
                        "component_id": fan_component_id,
                        "component_type": "thermal_power",
                        "name": fan["name"],
                        "slot_or_path": fan["location"],
                        "status": "healthy" if fan["speed_rpm"] is not None else "unknown",
                        "health": "PASS" if fan["speed_rpm"] is not None else "WARNING",
                        "capabilities": {"temperature": False, "fan_speed": True, "psu": False},
                        "metadata": {"source": fan["source"]},
                    }
                )
                telemetry.append(
                    self._point(
                        fan_component_id,
                        "fan.speed_rpm",
                        fan["speed_rpm"],
                        "RPM",
                        status="ok" if fan["speed_rpm"] is not None else "unsupported",
                    )
                )
        else:
            telemetry.append(self._point(component_id, "fan.speed_rpm", None, "RPM", status="unsupported"))
        return inventory, telemetry, {"source": "psutil.sensors_temperatures", "fans_detected": len(fans)}

    def _collect_pcie_inventory(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        component_id = "pcie:inventory"
        system_identity = self._read_system_identity()
        firmware_identity = self._read_firmware_identity()
        inventory = [
            {
                "component_id": component_id,
                "component_type": "pcie_inventory",
                "name": "PCIe Inventory",
                "status": "healthy",
                "health": "PASS",
                "capabilities": {"pcie_links": False, "firmware_inventory": True},
                "metadata": {
                    "platform": platform.platform(),
                    "board_name": system_identity.get("board"),
                    "board_vendor": system_identity.get("board_vendor"),
                    "board_serial": system_identity.get("board_serial"),
                    "bios_vendor": firmware_identity.get("bios_vendor"),
                    "bios_version": firmware_identity.get("bios_version"),
                },
            }
        ]
        return inventory, [], {"source": "platform"}

    def _summary_metrics(self, telemetry: list[dict[str, Any]]) -> dict[str, Any]:
        value_map = {entry["metric_key"]: entry.get("value") for entry in telemetry}
        disk_percent = next((entry.get("value") for entry in telemetry if entry["metric_key"] == "disk.used_percent"), 0)
        network_mbps = sum(
            float(entry.get("value") or 0)
            for entry in telemetry
            if entry["metric_key"] in {"network.rx_mbps", "network.tx_mbps"}
        )
        return {
            "cpu": float(value_map.get("cpu.load_percent") or 0),
            "memory": float(value_map.get("memory.used_percent") or 0),
            "disk": float(disk_percent or 0),
            "network_mbps": round(network_mbps, 2),
            "temperature_c": value_map.get("temperature_c"),
            "gpu_utilization": value_map.get("gpu.utilization_percent"),
            "fan_speed_rpm": value_map.get("fan.speed_rpm"),
        }

    @staticmethod
    def _read_temperature() -> float | None:
        if not hasattr(psutil, "sensors_temperatures"):
            return None
        try:
            readings = psutil.sensors_temperatures()
        except Exception:
            return None
        for entries in readings.values():
            if entries:
                return round(entries[0].current, 2)
        return None

    @staticmethod
    def _read_fan_speeds() -> list[dict[str, Any]]:
        if not hasattr(psutil, "sensors_fans"):
            return []
        try:
            readings = psutil.sensors_fans()
        except Exception:
            return []
        fans: list[dict[str, Any]] = []
        for source, entries in (readings or {}).items():
            for index, entry in enumerate(entries):
                speed = getattr(entry, "current", None)
                label = getattr(entry, "label", None) or f"Fan {index + 1}"
                fans.append(
                    {
                        "name": label,
                        "location": f"{source}:{index}",
                        "speed_rpm": round(float(speed), 2) if speed is not None else None,
                        "source": source,
                    }
                )
        return fans

    def _read_system_identity(self) -> dict[str, Any]:
        identity = {
            "os": platform.system() or None,
            "platform": platform.platform() or None,
            "hostname": socket.gethostname(),
            "architecture": platform.machine() or None,
            "kernel": platform.release() or None,
            "build": platform.version() or None,
            "vendor": None,
            "model": None,
            "serial": None,
            "board": None,
            "board_vendor": None,
            "board_serial": None,
        }
        if os.name == "nt":
            identity.update(self._read_windows_identity())
        else:
            identity.update(self._read_linux_identity())
        return identity

    def _read_firmware_identity(self) -> dict[str, Any]:
        if os.name == "nt":
            return self._read_windows_firmware()
        return self._read_linux_firmware()

    def _read_bmc_identity(self) -> dict[str, Any]:
        if os.name == "nt":
            return {
                "present": False,
                "address": None,
                "source": "not_detected",
            }
        if Path("/dev/ipmi0").exists():
            return {
                "present": True,
                "address": self._read_linux_bmc_address(),
                "source": "ipmi-device",
            }
        return {"present": False, "address": None, "source": "not_detected"}

    def _agent_identity(self) -> dict[str, Any]:
        try:
            version = importlib_metadata.version("prometheus-agent")
        except Exception:
            version = "0.1.0"
        executable = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
        return {
            "version": version,
            "runtime": "native" if getattr(sys, "frozen", False) else "python",
            "executable": str(executable),
            "platform": platform.platform(),
        }

    def _read_network_identity(self) -> dict[str, Any]:
        interfaces: list[dict[str, Any]] = []
        primary_ip = None
        primary_mac = None
        gateway = None
        dns_servers = self._read_dns_servers()
        if psutil:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            counters = psutil.net_io_counters(pernic=True)
            for name, entries in addrs.items():
                stat = stats.get(name)
                counter = counters.get(name)
                ipv4_addresses = [item.address for item in entries if "." in item.address]
                ipv6_addresses = [item.address for item in entries if ":" in item.address]
                mac_address = next((item.address for item in entries if len(item.address.split(":")) >= 6 or "-" in item.address), None)
                if primary_ip is None and ipv4_addresses:
                    primary_ip = ipv4_addresses[0]
                    primary_mac = mac_address
                interfaces.append(
                    {
                        "name": name,
                        "ipv4_addresses": ipv4_addresses,
                        "ipv6_addresses": ipv6_addresses,
                        "mac_address": mac_address,
                        "link_state": "up" if stat and stat.isup else "down",
                        "speed_mbps": stat.speed if stat else None,
                        "mtu": stat.mtu if stat else None,
                        "gateway": None,
                        "dns_servers": dns_servers,
                        "counters": {
                            "bytes_recv": counter.bytes_recv if counter else None,
                            "bytes_sent": counter.bytes_sent if counter else None,
                            "errin": counter.errin if counter else None,
                            "errout": counter.errout if counter else None,
                            "dropin": counter.dropin if counter else None,
                            "dropout": counter.dropout if counter else None,
                        },
                    }
                )
        gateway = self._read_default_gateway()
        for item in interfaces:
            item["gateway"] = gateway
        fqdn = socket.getfqdn()
        return {
            "primary_ip": primary_ip,
            "primary_mac": primary_mac,
            "gateway": gateway,
            "dns_servers": dns_servers,
            "hostname": socket.gethostname(),
            "fqdn": fqdn if fqdn and fqdn != socket.gethostname() else None,
            "interfaces": interfaces,
            "platform_addresses": [address for item in interfaces for address in [*item["ipv4_addresses"], *item["ipv6_addresses"]]],
        }

    def _read_software_inventory(self, system_identity: dict[str, Any], agent_identity: dict[str, Any]) -> dict[str, Any]:
        return {
            "os_edition": platform.platform(),
            "os_build": system_identity.get("build"),
            "kernel_version": system_identity.get("kernel"),
            "python_version": platform.python_version(),
            "runtime": agent_identity.get("runtime"),
            "driver_versions": {},
        }

    def _read_default_gateway(self) -> str | None:
        if os.name == "nt":
            payload = self._run_powershell_json(
                "(Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.DefaultIPGateway } | Select-Object -First 1 DefaultIPGateway | ConvertTo-Json -Compress)"
            ) or {}
            gateways = payload.get("DefaultIPGateway") if isinstance(payload.get("DefaultIPGateway"), list) else []
            return next((value for value in gateways if isinstance(value, str) and value), None)
        try:
            output = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, check=True, timeout=5).stdout.strip()
        except Exception:
            return None
        parts = output.split()
        if "via" in parts:
            index = parts.index("via")
            if index + 1 < len(parts):
                return parts[index + 1]
        return None

    def _read_dns_servers(self) -> list[str]:
        if os.name == "nt":
            payload = self._run_powershell_json(
                "(Get-DnsClientServerAddress -AddressFamily IPv4 | Select-Object -ExpandProperty ServerAddresses | ConvertTo-Json -Compress)"
            )
            if isinstance(payload, list):
                return [str(value) for value in payload if value]
            return []
        resolv = Path("/etc/resolv.conf")
        try:
            lines = resolv.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        return [line.split()[1] for line in lines if line.startswith("nameserver ") and len(line.split()) > 1]

    def _read_linux_bmc_address(self) -> str | None:
        try:
            output = subprocess.run(["ipmitool", "lan", "print", "1"], capture_output=True, text=True, check=True, timeout=5).stdout
        except Exception:
            return None
        for line in output.splitlines():
            normalized = line.strip()
            if normalized.lower().startswith("ip address") and ":" in normalized:
                value = normalized.split(":", 1)[1].strip()
                if value and value.lower() != "source":
                    return value
        return None

    def _read_windows_identity(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            "(Get-CimInstance Win32_ComputerSystemProduct | Select-Object Vendor,Name,IdentifyingNumber | ConvertTo-Json -Compress)"
        ) or {}
        board = self._run_powershell_json(
            "(Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product,SerialNumber | ConvertTo-Json -Compress)"
        ) or {}
        return {
            "vendor": payload.get("Vendor"),
            "model": payload.get("Name"),
            "serial": payload.get("IdentifyingNumber"),
            "board": board.get("Product"),
            "board_vendor": board.get("Manufacturer"),
            "board_serial": board.get("SerialNumber"),
        }

    def _read_windows_firmware(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            "(Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate,Version | ConvertTo-Json -Compress)"
        ) or {}
        return {
            "bios_vendor": payload.get("Manufacturer"),
            "bios_version": payload.get("SMBIOSBIOSVersion") or payload.get("Version"),
            "bios_release_date": payload.get("ReleaseDate"),
        }

    def _read_linux_identity(self) -> dict[str, Any]:
        return {
            "vendor": self._read_dmi_value("sys_vendor"),
            "model": self._read_dmi_value("product_name"),
            "serial": self._read_dmi_value("product_serial"),
            "board": self._read_dmi_value("board_name"),
            "board_vendor": self._read_dmi_value("board_vendor"),
            "board_serial": self._read_dmi_value("board_serial"),
        }

    def _read_linux_firmware(self) -> dict[str, Any]:
        return {
            "bios_vendor": self._read_dmi_value("bios_vendor"),
            "bios_version": self._read_dmi_value("bios_version"),
            "bios_release_date": self._read_dmi_value("bios_date"),
        }

    @staticmethod
    def _read_dmi_value(name: str) -> str | None:
        path = Path("/sys/class/dmi/id") / name
        try:
            value = path.read_text(encoding="utf-8").strip()
        except Exception:
            return None
        return value or None

    @staticmethod
    def _run_powershell_json(script: str) -> Any:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        except Exception:
            return None
        output = result.stdout.strip()
        if not output:
            return None
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return None
        return parsed

    @staticmethod
    def _point(component_id: str, metric_key: str, value: float | None, unit: str | None, labels: dict[str, Any] | None = None, status: str = "ok") -> dict[str, Any]:
        return {
            "component_id": component_id,
            "metric_key": metric_key,
            "value": value,
            "unit": unit,
            "status": status if value is not None else status,
            "labels": labels or {},
            "recorded_at": utc_now_iso(),
        }


class MetricsSampler:
    def __init__(self) -> None:
        self.pipeline = HardwareCollectorPipeline()

    def sample(self) -> dict[str, Any]:
        return self.pipeline.sample()["summary_metrics"]

    def sample_hardware(self) -> dict[str, Any]:
        return self.pipeline.sample()

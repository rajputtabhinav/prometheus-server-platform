from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException, status

from app.core.config import settings
from app.models import utc_now
from app.models import AgentInstallCommandResponse, AgentReleaseArtifact, AgentReleaseManifest, AgentTargetOS


class AgentInstallService:
    VERSION = "0.2.0"
    WINDOWS_FILENAME = "prometheus-agent-windows-x64.exe"
    LINUX_FILENAME = "prometheus-agent-linux-x64"
    BUILD_REQUIREMENTS = [
        "pyinstaller",
        "httpx>=0.28.1",
        "psutil>=7.0.0",
        "pydantic-settings>=2.8.0",
    ]

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    @property
    def backend_root(self) -> Path:
        return self.repo_root / "backend"

    @property
    def agent_project_root(self) -> Path:
        return self.repo_root / "agent"

    @property
    def agent_entrypoint(self) -> Path:
        return self.agent_project_root / "prometheus_agent" / "main.py"

    @property
    def release_root_path(self) -> Path:
        configured = Path(settings.release_root)
        if configured.is_absolute():
            return configured
        return (self.backend_root / configured).resolve()

    @property
    def host_target_os(self) -> AgentTargetOS | None:
        if sys.platform.startswith("win"):
            return AgentTargetOS.WINDOWS
        if sys.platform.startswith("linux"):
            return AgentTargetOS.LINUX
        return None

    def public_base_url(self, request_base_url: str | None = None) -> str:
        if settings.public_base_url:
            return settings.public_base_url.rstrip("/")
        if request_base_url:
            return request_base_url.rstrip("/")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Public base URL is not configured.")

    def artifact_filename(self, target_os: AgentTargetOS, arch: str = "x64") -> str:
        return self.ensure_release_artifact(target_os, arch).name

    def artifact_path(self, target_os: AgentTargetOS, arch: str = "x64") -> Path:
        target_dir = self.release_root_path / f"{target_os.value}-{arch}"
        return target_dir / self.artifact_name(target_os, arch)

    def artifact_name(self, target_os: AgentTargetOS, arch: str = "x64") -> str:
        if arch != "x64":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported agent architecture: {arch}")
        if target_os == AgentTargetOS.WINDOWS:
            return self.WINDOWS_FILENAME
        return self.LINUX_FILENAME

    def package_format(self, target_os: AgentTargetOS) -> str:
        if target_os == AgentTargetOS.WINDOWS:
            return "native-exe"
        return "native-elf"

    def checksum(self, file_path: Path) -> str | None:
        if not file_path.exists():
            return None
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def ensure_release_artifact(self, target_os: AgentTargetOS, arch: str = "x64") -> Path:
        artifact_path = self.artifact_path(target_os, arch)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if artifact_path.exists() and not self._artifact_is_stale(artifact_path):
            return artifact_path

        try:
            self._build_native_artifact(target_os, arch, artifact_path)
        except HTTPException:
            raise
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            detail = stderr or f"Unable to build {target_os.value} native agent artifact."
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unable to build {target_os.value} native agent artifact: {exc}",
            ) from exc

        if not artifact_path.exists():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unable to produce {target_os.value} native agent artifact.",
            )
        return artifact_path

    def release_manifest(self, public_base_url: str, published_at=None) -> AgentReleaseManifest:
        artifacts: list[AgentReleaseArtifact] = []
        for target_os in (AgentTargetOS.WINDOWS, AgentTargetOS.LINUX):
            try:
                path = self.ensure_release_artifact(target_os)
                filename = path.name
                base_download = f"{public_base_url}/api/v1/agents/releases/download/{target_os.value}/x64/{filename}"
                checksum_url = f"{base_download}.sha256"
                artifacts.append(
                    AgentReleaseArtifact(
                        target_os=target_os,
                        arch="x64",
                        package_format=self.package_format(target_os),
                        available=True,
                        filename=filename,
                        download_url=base_download,
                        checksum_url=checksum_url,
                        sha256=self.checksum(path),
                        size_bytes=path.stat().st_size if path.exists() else None,
                    )
                )
            except HTTPException as exc:
                artifacts.append(
                    AgentReleaseArtifact(
                        target_os=target_os,
                        arch="x64",
                        package_format=self.package_format(target_os),
                        available=False,
                        build_error=str(exc.detail),
                    )
                )
        return AgentReleaseManifest(version=self.VERSION, published_at=published_at or utc_now(), artifacts=artifacts)

    def command_response(self, enrollment, target_os: AgentTargetOS, public_base_url: str) -> AgentInstallCommandResponse:
        artifact_path = self.ensure_release_artifact(target_os)
        filename = artifact_path.name
        download_url = f"{public_base_url}/api/v1/agents/releases/download/{target_os.value}/x64/{filename}"
        checksum_url = f"{download_url}.sha256"
        query = urlencode({"connection_code": enrollment.connection_code})
        script_url = f"{public_base_url}/api/v1/agents/install/{target_os.value}?{query}"
        if target_os == AgentTargetOS.WINDOWS:
            command = f'powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing \'{script_url}\' | iex"'
        else:
            command = f"curl -fsSL '{script_url}' | sh"
        return AgentInstallCommandResponse(
            enrollment=enrollment,
            target_os=target_os,
            package_format=self.package_format(target_os),
            command=command,
            script_url=script_url,
            download_url=download_url,
            checksum_url=checksum_url,
            service_name=settings.agent_service_name,
        )

    def bootstrap_script(self, target_os: AgentTargetOS, public_base_url: str, connection_code: str) -> str:
        artifact_path = self.ensure_release_artifact(target_os)
        filename = artifact_path.name
        binary_url = f"{public_base_url}/api/v1/agents/releases/download/{target_os.value}/x64/{filename}"
        if target_os == AgentTargetOS.WINDOWS:
            return f"""
$ErrorActionPreference = 'Stop'
$taskName = '{settings.agent_service_name}'
$installDir = Join-Path $env:LOCALAPPDATA 'PrometheusAgent'
$binDir = Join-Path $installDir 'bin'
$binaryPath = Join-Path $binDir '{filename}'
$credentialsPath = Join-Path $installDir 'credentials.json'
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Get-Process | Where-Object {{ $_.Path -eq $binaryPath }} | Stop-Process -Force -ErrorAction SilentlyContinue
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {{
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false | Out-Null
}}
Start-Sleep -Milliseconds 600
Invoke-WebRequest -UseBasicParsing -Uri '{binary_url}' -OutFile $binaryPath
$taskAction = New-ScheduledTaskAction -Execute $binaryPath -Argument ('--controller-url {public_base_url} --connection-code {connection_code} --credentials-path ' + '\"' + $credentialsPath + '\"')
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Description 'Prometheus Agent startup task' | Out-Null
Start-Process -FilePath $binaryPath -ArgumentList @(
  '--controller-url', '{public_base_url}',
  '--connection-code', '{connection_code}',
  '--credentials-path', $credentialsPath
) -WindowStyle Hidden | Out-Null
try {{
  Start-ScheduledTask -TaskName $taskName
}} catch {{
}}
Write-Host 'Prometheus agent installed and registered as a native Windows startup task for the current user.'
""".strip()
        return f"""
#!/usr/bin/env sh
set -eu
SERVICE_NAME="{settings.agent_service_name}"
INSTALL_DIR="/opt/prometheus-agent/bin"
BINARY_PATH="$INSTALL_DIR/{filename}"
CREDENTIALS_DIR="/etc/prometheus-agent"
CREDENTIALS_PATH="$CREDENTIALS_DIR/credentials.json"
mkdir -p "$INSTALL_DIR" "$CREDENTIALS_DIR"
curl -fsSL "{binary_url}" -o "$BINARY_PATH"
chmod +x "$BINARY_PATH"
cat > /etc/systemd/system/${{SERVICE_NAME}}.service <<UNIT
[Unit]
Description=Prometheus Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/prometheus-agent/bin/{filename} --controller-url {public_base_url} --connection-code {connection_code} --credentials-path $CREDENTIALS_PATH
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
echo "Prometheus agent installed and started as native Linux service."
""".strip()

    def _artifact_is_stale(self, artifact_path: Path) -> bool:
        try:
            artifact_mtime = artifact_path.stat().st_mtime
        except FileNotFoundError:
            return True
        return artifact_mtime < self._latest_agent_source_mtime()

    def _latest_agent_source_mtime(self) -> float:
        latest = self.agent_project_root.joinpath("pyproject.toml").stat().st_mtime
        for path in self.agent_project_root.rglob("*.py"):
            latest = max(latest, path.stat().st_mtime)
        return latest

    def _build_native_artifact(self, target_os: AgentTargetOS, arch: str, artifact_path: Path) -> None:
        if target_os == AgentTargetOS.WINDOWS:
            self._build_windows_native(arch, artifact_path)
            return
        self._build_linux_native(arch, artifact_path)

    def _build_windows_native(self, arch: str, artifact_path: Path) -> None:
        if arch != "x64":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported agent architecture: {arch}")
        if self.host_target_os != AgentTargetOS.WINDOWS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Windows native agent builds must run on a Windows builder host.",
            )

        build_root = self.release_root_path / "_native-build" / "windows-x64"
        venv_python = self._ensure_builder_venv(build_root)
        dist_dir = build_root / "dist"
        work_dir = build_root / "work"
        spec_dir = build_root / "spec"
        if dist_dir.exists():
            shutil.rmtree(dist_dir, ignore_errors=True)
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        if spec_dir.exists():
            shutil.rmtree(spec_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        spec_dir.mkdir(parents=True, exist_ok=True)
        self._clean_python_build_artifacts()

        self._run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            cwd=self.agent_project_root,
        )
        self._run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", *self.BUILD_REQUIREMENTS],
            cwd=self.agent_project_root,
        )
        self._run(
            [
                str(venv_python),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--name",
                "prometheus-agent",
                "--distpath",
                str(dist_dir),
                "--workpath",
                str(work_dir),
                "--specpath",
                str(spec_dir),
                "--paths",
                str(self.agent_project_root),
                str(self.agent_entrypoint),
            ],
            cwd=self.agent_project_root,
        )
        built = dist_dir / "prometheus-agent.exe"
        if not built.exists():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PyInstaller did not produce a Windows executable.")
        shutil.copy2(built, artifact_path)

    def _build_linux_native(self, arch: str, artifact_path: Path) -> None:
        if arch != "x64":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported agent architecture: {arch}")
        if self.host_target_os == AgentTargetOS.LINUX:
            self._build_linux_native_locally(artifact_path)
            return
        if self._docker_ready():
            self._build_linux_native_with_docker(artifact_path)
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Linux native agent build requires a Linux builder host or a running Docker daemon.",
        )

    def _build_linux_native_locally(self, artifact_path: Path) -> None:
        build_root = self.release_root_path / "_native-build" / "linux-x64"
        venv_python = self._ensure_builder_venv(build_root)
        dist_dir = build_root / "dist"
        work_dir = build_root / "work"
        spec_dir = build_root / "spec"
        if dist_dir.exists():
            shutil.rmtree(dist_dir, ignore_errors=True)
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        if spec_dir.exists():
            shutil.rmtree(spec_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        spec_dir.mkdir(parents=True, exist_ok=True)
        self._clean_python_build_artifacts()

        self._run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip", *self.BUILD_REQUIREMENTS],
            cwd=self.agent_project_root,
        )
        self._run(
            [
                str(venv_python),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--name",
                "prometheus-agent",
                "--distpath",
                str(dist_dir),
                "--workpath",
                str(work_dir),
                "--specpath",
                str(spec_dir),
                "--paths",
                str(self.agent_project_root),
                str(self.agent_entrypoint),
            ],
            cwd=self.agent_project_root,
        )
        built = dist_dir / "prometheus-agent"
        if not built.exists():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PyInstaller did not produce a Linux executable.")
        shutil.copy2(built, artifact_path)

    def _build_linux_native_with_docker(self, artifact_path: Path) -> None:
        build_root = self.release_root_path / "_native-build" / "linux-x64-docker"
        dist_dir = build_root / "dist"
        if dist_dir.exists():
            shutil.rmtree(dist_dir, ignore_errors=True)
        dist_dir.mkdir(parents=True, exist_ok=True)
        docker_script = """
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y --no-install-recommends binutils >/dev/null
python -m pip install --upgrade pip >/dev/null
pip install pyinstaller >/dev/null
pip install /src >/dev/null
pyinstaller --noconfirm --clean --onefile --name prometheus-agent --distpath /out --workpath /tmp/pyi-work --specpath /tmp/pyi-spec --paths /src /src/prometheus_agent/main.py >/dev/null
"""
        self._run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{self.agent_project_root.resolve()}:/src",
                "-v",
                f"{dist_dir.resolve()}:/out",
                "python:3.11-slim",
                "bash",
                "-lc",
                docker_script,
            ],
            cwd=self.repo_root,
        )
        built = dist_dir / "prometheus-agent"
        if not built.exists():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Docker did not produce a Linux executable.")
        shutil.copy2(built, artifact_path)

    def _ensure_builder_venv(self, build_root: Path) -> Path:
        venv_dir = build_root / "venv"
        scripts_dir = "Scripts" if self.host_target_os == AgentTargetOS.WINDOWS else "bin"
        python_name = "python.exe" if self.host_target_os == AgentTargetOS.WINDOWS else "python"
        venv_python = venv_dir / scripts_dir / python_name
        site_packages = venv_dir / ("Lib\\site-packages" if self.host_target_os == AgentTargetOS.WINDOWS else "lib")
        invalid_distribution = False
        if site_packages.exists():
          invalid_distribution = any(path.name.startswith("~") for path in site_packages.rglob("*"))
        if invalid_distribution and venv_dir.exists():
            shutil.rmtree(venv_dir, ignore_errors=True)
            venv_python = venv_dir / scripts_dir / python_name
        if not venv_python.exists():
            build_root.mkdir(parents=True, exist_ok=True)
            if venv_dir.exists():
                shutil.rmtree(venv_dir, ignore_errors=True)
            try:
                self._run([sys.executable, "-m", "venv", str(venv_dir)], cwd=self.repo_root)
            except subprocess.CalledProcessError:
                return Path(sys.executable)
        try:
            self._run([str(venv_python), "-m", "pip", "--version"], cwd=self.repo_root)
        except subprocess.CalledProcessError:
            return Path(sys.executable)
        return venv_python

    def _clean_python_build_artifacts(self) -> None:
        for path in (
            self.agent_project_root / "build",
            self.agent_project_root / "dist",
        ):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        for path in self.agent_project_root.glob("*.egg-info"):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def _docker_ready(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Os}}"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        return bool(result.stdout.strip())

    def _run(self, command: list[str], cwd: Path) -> None:
        subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )


agent_install_service = AgentInstallService()

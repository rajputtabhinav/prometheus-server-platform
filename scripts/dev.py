from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
NPM = "npm.cmd" if os.name == "nt" else "npm"


def find_available_port(preferred_port: int) -> int:
    port = preferred_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1


def stream_output(prefix: str, process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[{prefix}] {line.rstrip()}")


def spawn_process(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    threading.Thread(target=stream_output, args=(name, process), daemon=True).start()
    return process


def terminate_processes(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()

    deadline = time.time() + 6
    while time.time() < deadline:
        if all(process.poll() is not None for process in processes):
            return
        time.sleep(0.2)

    for process in processes:
        if process.poll() is None:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the Prometheus local development stack.")
    parser.add_argument("--with-agent", action="store_true", help="Also start the local Python agent.")
    args = parser.parse_args()

    if shutil.which(NPM) is None:
        print("npm was not found in PATH.")
        return 1

    backend_port = find_available_port(8000)
    frontend_port = find_available_port(5173)

    backend_env = os.environ.copy()
    backend_env.setdefault("PROMETHEUS_SEED_DEMO_DATA", "false")
    backend_env["PROMETHEUS_CORS_ORIGINS"] = (
        f"http://127.0.0.1:{frontend_port},http://localhost:{frontend_port}"
    )

    frontend_env = os.environ.copy()
    frontend_env["VITE_API_BASE_URL"] = f"http://127.0.0.1:{backend_port}"

    processes = [
        spawn_process(
            "backend",
            [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
            ROOT / "backend",
            backend_env,
        ),
        spawn_process(
            "frontend",
            [NPM, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
            ROOT / "frontend",
            frontend_env,
        ),
    ]

    if args.with_agent:
        agent_env = os.environ.copy()
        agent_env["PROMETHEUS_CONTROLLER_URL"] = f"http://127.0.0.1:{backend_port}"
        agent_env.setdefault("PROMETHEUS_AGENT_NAME", "local-console")
        agent_env.setdefault("PROMETHEUS_AGENT_GROUP", "local-lab")
        agent_env.setdefault("PROMETHEUS_AGENT_TAGS", "local,windows")
        processes.insert(
            1,
            spawn_process(
                "agent",
                [PYTHON, "-m", "prometheus_agent.main"],
                ROOT / "agent",
                agent_env,
            ),
        )

    def handle_signal(signum: int, frame) -> None:  # type: ignore[no-untyped-def]
        print(f"Stopping Prometheus dev stack (signal {signum})...")
        terminate_processes(processes)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    print("Prometheus dev stack started.")
    print(f"Frontend: http://127.0.0.1:{frontend_port}")
    print(f"Backend:  http://127.0.0.1:{backend_port}")
    if args.with_agent:
        print("Agent:    enabled")

    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    print(f"Process exited early with code {code}: {process.args}")
                    terminate_processes(processes)
                    return code
            time.sleep(0.5)
    finally:
        terminate_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())

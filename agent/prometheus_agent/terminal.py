from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import pty
except ImportError:  # pragma: no cover - Windows agents do not expose pty.
    pty = None  # type: ignore[assignment]


@dataclass
class _ShellSession:
    session_id: str
    shell_type: str
    process: subprocess.Popen[bytes]
    is_pty: bool
    master_fd: int | None = None
    output: deque[str] = field(default_factory=deque)
    closed: bool = False
    error_message: str | None = None


class AgentTerminalManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _ShellSession] = {}
        self._lock = threading.Lock()

    @property
    def capability(self) -> dict[str, Any]:
        system = platform.system().lower()
        return {
            "supported": True,
            "shell": "powershell" if system == "windows" else (os.environ.get("SHELL") or "/bin/bash"),
            "pty_supported": system != "windows",
            "max_sessions": 1,
        }

    def apply_commands(self, commands: list[dict[str, Any]]) -> None:
        for command in commands:
            action = str(command.get("action") or "")
            session_id = str(command.get("session_id") or "")
            if not session_id:
                continue
            if action == "open":
                self._open_session(session_id, command)
            elif action == "input":
                self._write_session(session_id, str(command.get("data") or ""))
            elif action == "resize":
                self._resize_session(session_id, command.get("cols"), command.get("rows"))
            elif action == "close":
                self._close_session(session_id)

    def collect_updates(self) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        stale: list[str] = []
        with self._lock:
            items = list(self._sessions.items())
        for session_id, session in items:
            chunks: list[str] = []
            while session.output:
                chunks.append(session.output.popleft())
            process_closed = session.process.poll() is not None
            if process_closed and not session.closed:
                session.closed = True
                if not session.error_message and session.process.returncode not in (0, None):
                    session.error_message = f"Shell exited with code {session.process.returncode}."
            if chunks or session.closed or session.error_message:
                updates.append(
                    {
                        "session_id": session_id,
                        "outputs": chunks,
                        "shell_type": session.shell_type,
                        "closed": session.closed,
                        "error_message": session.error_message,
                    }
                )
            if session.closed:
                stale.append(session_id)
        for session_id in stale:
            with self._lock:
                self._sessions.pop(session_id, None)
        return updates

    def _reader(self, session: _ShellSession) -> None:
        try:
            if session.is_pty and session.master_fd is not None:
                while not session.closed:
                    try:
                        chunk = os.read(session.master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    session.output.append(chunk.decode(errors="ignore"))
            else:
                assert session.process.stdout is not None
                while not session.closed:
                    chunk = session.process.stdout.read1(4096)
                    if not chunk:
                        break
                    session.output.append(chunk.decode(errors="ignore"))
        except Exception as exc:
            session.error_message = str(exc)
        finally:
            session.closed = True

    def _open_session(self, session_id: str, command: dict[str, Any]) -> None:
        if session_id in self._sessions:
            return
        system = platform.system().lower()
        shell_preference = str(command.get("shell_type") or "").strip()
        if system == "windows":
            shell = shell_preference or shutil.which("powershell") or "powershell"
            process = subprocess.Popen(
                [shell, "-NoLogo"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(Path.home()),
            )
            session = _ShellSession(session_id=session_id, shell_type="powershell", process=process, is_pty=False)
        else:
            shell = shell_preference or os.environ.get("SHELL") or "/bin/bash"
            if pty is None:
                raise RuntimeError("PTY support is unavailable on this host.")
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                [shell, "-i"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(Path.home()),
                close_fds=True,
                start_new_session=True,
            )
            os.close(slave_fd)
            session = _ShellSession(
                session_id=session_id,
                shell_type=Path(shell).name,
                process=process,
                is_pty=True,
                master_fd=master_fd,
            )
        thread = threading.Thread(target=self._reader, args=(session,), daemon=True)
        thread.start()
        self._sessions[session_id] = session
        session.output.append("Prometheus terminal connected.\n")

    def _write_session(self, session_id: str, data: str) -> None:
        session = self._sessions.get(session_id)
        if not session or session.closed or not data:
            return
        encoded = data.encode()
        try:
            if session.is_pty and session.master_fd is not None:
                os.write(session.master_fd, encoded)
            elif session.process.stdin is not None:
                session.process.stdin.write(encoded)
                session.process.stdin.flush()
        except Exception as exc:
            session.error_message = str(exc)
            session.closed = True

    def _resize_session(self, session_id: str, cols: Any, rows: Any) -> None:
        session = self._sessions.get(session_id)
        if not session or not session.is_pty or session.master_fd is None:
            return
        try:
            import fcntl
            import struct
            import termios

            size = struct.pack("HHHH", int(rows or 32), int(cols or 120), 0, 0)
            fcntl.ioctl(session.master_fd, termios.TIOCSWINSZ, size)
        except Exception:
            return

    def _close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        session.closed = True
        try:
            session.process.terminate()
        except Exception:
            pass
        if session.master_fd is not None:
            try:
                os.close(session.master_fd)
            except OSError:
                pass

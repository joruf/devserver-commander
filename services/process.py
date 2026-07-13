"""Manage the lifecycle of a single project's server process."""

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from models import ServerProject
from services.port_info import describe_port_usage
from services.ports import is_port_open
from services.stats import pid_for_port

LOG_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "devserver-commander" / "logs"


def log_path_for(project: ServerProject) -> Path:
    """Return the log file path used for a given project's output."""
    safe_name = "".join(character if character.isalnum() or character in "-_." else "_" for character in project.name)
    return LOG_DIR / f"{safe_name}.log"


def format_launch_command(command: str, env: Optional[Dict[str, str]] = None) -> str:
    """
    Format the shell-style command shown to the user, including environment variables.

    :param command: Executable command with arguments
    :param env: Optional extra environment variables for the process
    :return: Full launch command as it is executed
    """
    if not env:
        return command
    prefix = " ".join(f"{key}={value}" for key, value in env.items())
    return f"{prefix} {command}"


def kill_by_port(port: int) -> bool:
    """Best-effort kill of whatever process is listening on the given port."""
    try:
        result = subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


class ServerProcess:
    """Tracks a single running (or stopped) managed server process."""

    def __init__(self, project: ServerProject) -> None:
        self.project = project
        self._popen: Optional[subprocess.Popen] = None
        self._unmanaged = False

    @property
    def unmanaged(self) -> bool:
        return self._unmanaged

    def is_running(self) -> bool:
        """Return True if this project's server currently appears to be running."""
        if self._popen is not None:
            if self._popen.poll() is None:
                return True
            self._popen = None
            return False
        if self.project.port is not None and is_port_open(self.project.port):
            self._unmanaged = True
            return True
        return False

    @property
    def pid(self) -> Optional[int]:
        return self._popen.pid if self._popen is not None else None

    def resolve_pid(self) -> Optional[int]:
        """
        Return the best-known PID for this project's server process.

        :return: Managed process PID, port owner PID, or None when stopped
        """
        if self._popen is not None and self._popen.poll() is None:
            return self._popen.pid

        if self.project.port is not None and is_port_open(self.project.port):
            return pid_for_port(self.project.port)

        return None

    def _owns_configured_port(self) -> bool:
        """
        Return True when the configured port is owned by this managed process.

        :return: True if the tracked process or its child owns the configured port
        """
        if self.project.port is None:
            return False

        if self._popen is not None and self._popen.poll() is None:
            return True

        pid = pid_for_port(self.project.port)
        if pid is None:
            return False

        if self._popen is not None and self._popen.pid == pid:
            return True

        return False

    def start(self) -> None:
        """Launch the project's command as a background process."""
        if self._popen is not None and self._popen.poll() is None:
            raise RuntimeError(f"'{self.project.name}' is already running.")

        if self.project.port is not None:
            port_message = describe_port_usage(self.project.port)
            if port_message is not None and not self._owns_configured_port():
                raise RuntimeError(port_message)

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = log_path_for(self.project)
        env = dict(os.environ)
        env.update(self.project.build_env())

        command = self.project.build_command()
        args = shlex.split(command)
        launch_command = format_launch_command(command, self.project.build_env())

        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(f"\n--- starting: {launch_command}  (cwd={self.project.directory}) ---\n")

        log_handle = open(log_file, "a", encoding="utf-8")
        try:
            self._popen = subprocess.Popen(
                args,
                cwd=self.project.directory,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        self._unmanaged = False

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the server: terminate the tracked process group, or kill by port."""
        if self._popen is not None and self._popen.poll() is None:
            pgid = os.getpgid(self._popen.pid)
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._popen.poll() is not None:
                    break
                time.sleep(0.1)
            else:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self._popen = None
            return

        if self.project.port is not None and is_port_open(self.project.port):
            kill_by_port(self.project.port)
        self._unmanaged = False

    def restart(self) -> None:
        """Stop then start the server again."""
        if self.is_running():
            self.stop()
            time.sleep(0.3)
        self.start()

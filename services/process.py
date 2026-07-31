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


def describe_exit(exit_code: Optional[int]) -> str:
    """
    Describe a process exit status in words for logs and notifications.

    :param exit_code: Return code from Popen.poll(); negative values mean a signal
    :return: Human-readable description of how the process ended
    """
    if exit_code is None:
        return "ended for an unknown reason"
    if exit_code == 0:
        return "ended with exit code 0"
    if exit_code < 0:
        signal_number = -exit_code
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            return f"was killed by signal {signal_number}"
        return f"was killed by {signal_name} ({signal_number})"
    return f"ended with exit code {exit_code}"


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
        self._stop_requested = False
        self._unexpected_exit: Optional[int] = None
        self._started_at: Optional[float] = None

    @property
    def unmanaged(self) -> bool:
        return self._unmanaged

    def is_running(self) -> bool:
        """Return True if this project's server currently appears to be running."""
        if self._popen is not None:
            if self._popen.poll() is None:
                return True
            self._reap_finished_process()
            return False
        if self.project.port is not None and is_port_open(self.project.port):
            self._unmanaged = True
            return True
        return False

    def _reap_finished_process(self) -> None:
        """
        Clear the finished process and remember terminations nobody asked for.

        :return: None
        """
        exit_code = self._popen.poll() if self._popen is not None else None
        self._popen = None
        self._started_at = None

        if self._stop_requested:
            self._stop_requested = False
            return

        self._unexpected_exit = exit_code
        self.append_log_note(f"exited unexpectedly: {describe_exit(exit_code)}")

    def take_unexpected_exit(self) -> Optional[int]:
        """
        Consume the exit status of a termination that was not requested.

        Each unexpected exit is reported exactly once, so callers can poll this
        without re-acting on an exit they already handled.

        :return: Exit status of the crashed process, or None when nothing crashed
        """
        exit_code, self._unexpected_exit = self._unexpected_exit, None
        return exit_code

    @property
    def uptime_seconds(self) -> Optional[float]:
        """
        Return how long the managed process has been running.

        :return: Uptime in seconds, or None when no managed process is tracked
        """
        if self._started_at is None:
            return None
        return time.monotonic() - self._started_at

    def append_log_note(self, note: str) -> None:
        """
        Append an application-generated line to this project's log file.

        :param note: Message written between the process output
        :return: None
        """
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(log_path_for(self.project), "a", encoding="utf-8") as handle:
                handle.write(f"--- {note} ---\n")
        except OSError:
            pass

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
        self._stop_requested = False
        self._unexpected_exit = None
        self._started_at = time.monotonic()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the server: terminate the tracked process group, or kill by port."""
        self._stop_requested = True
        self._unexpected_exit = None

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
            self._started_at = None
            self._stop_requested = False
            return

        if self.project.port is not None and is_port_open(self.project.port):
            kill_by_port(self.project.port)
        self._unmanaged = False
        self._stop_requested = False

    def restart(self) -> None:
        """Stop then start the server again."""
        if self.is_running():
            self.stop()
            time.sleep(0.3)
        self.start()

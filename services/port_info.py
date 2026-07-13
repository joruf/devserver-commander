"""Helpers for describing processes that occupy TCP ports."""

from typing import Optional

from services.ports import is_port_open
from services.stats import pid_for_port


def process_name_for_pid(pid: int) -> Optional[str]:
    """
    Return a short process name for the given PID.

    :param pid: Process ID
    :return: Process name or None when unavailable
    """
    try:
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as handle:
            name = handle.read().strip()
            if name:
                return name
    except OSError:
        pass

    try:
        with open(f"/proc/{pid}/cmdline", "r", encoding="utf-8", errors="replace") as handle:
            cmdline = handle.read().replace("\x00", " ").strip()
            if cmdline:
                return cmdline.split(" ", 1)[0]
    except OSError:
        pass

    return None


def describe_port_usage(port: int) -> Optional[str]:
    """
    Describe what is currently listening on the given TCP port.

    :param port: TCP port number
    :return: Human-readable description or None when the port is free
    """
    if not is_port_open(port):
        return None

    pid = pid_for_port(port)
    if pid is None:
        return f"Port {port} is already in use by another process."

    process_name = process_name_for_pid(pid)
    if process_name:
        return f"Port {port} is already in use by PID {pid} ({process_name})."

    return f"Port {port} is already in use by PID {pid}."

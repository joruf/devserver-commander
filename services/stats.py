"""CPU and memory usage helpers for managed server processes."""

import os
import re
import subprocess
import time
from typing import Dict, Optional, Tuple

_CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
_CPU_COUNT = os.cpu_count() or 1
_PREVIOUS_CPU_SAMPLES: Dict[int, Tuple[int, float]] = {}


def _parse_process_total_time(stat_line: str) -> Optional[int]:
    """
    Parse ``utime + stime`` from one ``/proc/<pid>/stat`` line.

    The second field (process name) is wrapped in parentheses and may contain
    spaces. A naive ``split()`` can shift field indices and produce wrong CPU
    values, so parsing starts after the closing parenthesis.

    :param stat_line: Raw line from ``/proc/<pid>/stat``
    :return: Sum of ``utime`` and ``stime`` clock ticks, or None on parse error
    """
    stat_line = stat_line.strip()
    closing_paren = stat_line.rfind(")")
    if closing_paren < 0:
        return None

    remainder = stat_line[closing_paren + 1 :].strip()
    fields = remainder.split()
    if len(fields) < 15:
        return None

    try:
        utime = int(fields[11])
        stime = int(fields[12])
    except ValueError:
        return None

    return utime + stime


def pid_for_port(port: int) -> Optional[int]:
    """
    Return the PID listening on the given TCP port, if any.

    :param port: TCP port number
    :return: Process ID or None when nothing is listening
    """
    try:
        result = subprocess.run(
            ["fuser", "-n", "tcp", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None

    for match in re.finditer(r"\b(\d+)\b", result.stdout):
        pid = int(match.group(1))
        if pid != port:
            return pid

    return None


def _read_process_times(pid: int) -> Optional[int]:
    """
    Read the combined user and system CPU time for a process.

    :param pid: Process ID
    :return: Total CPU time in clock ticks, or None when unavailable
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            stat_line = handle.read()
    except OSError:
        return None

    return _parse_process_total_time(stat_line)


def _read_memory_bytes(pid: int) -> Optional[int]:
    """
    Read resident set size for a process.

    :param pid: Process ID
    :return: Memory usage in bytes, or None when unavailable
    """
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except (OSError, ValueError):
        return None

    return None


def format_memory_bytes(memory_bytes: Optional[int]) -> str:
    """
    Format a byte count for display in the server list.

    :param memory_bytes: Resident memory in bytes
    :return: Human-readable memory label
    """
    if memory_bytes is None:
        return "-"

    if memory_bytes >= 1024 * 1024:
        return f"{memory_bytes / (1024 * 1024):.1f} MB"

    if memory_bytes >= 1024:
        return f"{memory_bytes / 1024:.0f} KB"

    return f"{memory_bytes} B"


def get_process_stats(pid: int) -> Tuple[Optional[float], Optional[int]]:
    """
    Return CPU usage percentage and resident memory for a process.

    CPU percentage is calculated from the delta since the previous sample for
    the same PID. The first sample returns None for CPU.

    :param pid: Process ID
    :return: Tuple of (cpu_percent, memory_bytes)
    """
    total_time = _read_process_times(pid)
    memory_bytes = _read_memory_bytes(pid)
    if total_time is None:
        _PREVIOUS_CPU_SAMPLES.pop(pid, None)
        return None, memory_bytes

    now = time.monotonic()
    previous = _PREVIOUS_CPU_SAMPLES.get(pid)
    _PREVIOUS_CPU_SAMPLES[pid] = (total_time, now)

    if previous is None:
        return None, memory_bytes

    previous_time, previous_monotonic = previous
    elapsed = now - previous_monotonic
    if elapsed <= 0:
        return None, memory_bytes

    cpu_delta = total_time - previous_time
    cpu_percent = (cpu_delta / (_CLOCK_TICKS * elapsed * _CPU_COUNT)) * 100.0
    return max(0.0, cpu_percent), memory_bytes


def format_cpu_percent(cpu_percent: Optional[float]) -> str:
    """
    Format CPU usage for display in the server list.

    :param cpu_percent: CPU usage percentage
    :return: Human-readable CPU label
    """
    if cpu_percent is None:
        return "-"

    return f"{cpu_percent:.1f}%"

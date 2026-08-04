"""Discover TCP ports currently listening on the local machine."""

import os
import pwd
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROCESS_PATTERN = re.compile(r'\(\("([^"]+)",pid=(\d+)')

PROC_NET_TCP_FILES = ("/proc/net/tcp", "/proc/net/tcp6")
TCP_STATE_LISTEN = "0A"


@dataclass(frozen=True)
class ScannedPort:
    """A single TCP port found listening on the machine.

    :param port: TCP port number
    :param address: Local address the socket is bound to (e.g. ``127.0.0.1``)
    :param pid: Owning process ID, or None when it could not be determined
    :param process_name: Owning process name, or None when it could not be determined
    """

    port: int
    address: str
    pid: Optional[int]
    process_name: Optional[str]


def _parse_local_address(field: str) -> Optional[Tuple[str, int]]:
    """
    Split an ``ss`` local-address field into address and port.

    Handles bracketed IPv6 addresses (``[::1]:4321``) as well as plain
    IPv4/hostname forms (``127.0.0.1:4321``, ``127.0.0.53%lo:53``).

    :param field: Raw local-address field from ``ss`` output
    :return: Tuple of (address, port) or None when the field is malformed
    """
    if field.startswith("["):
        closing = field.find("]")
        if closing == -1:
            return None
        address = field[1:closing]
        port_part = field[closing + 2 :]
    else:
        if ":" not in field:
            return None
        address, port_part = field.rsplit(":", 1)

    try:
        port = int(port_part)
    except ValueError:
        return None

    return address, port


def _parse_ss_line(line: str) -> Optional[ScannedPort]:
    """
    Parse one line of ``ss -H -tlnp`` output into a ScannedPort.

    :param line: Raw output line
    :return: Parsed port entry, or None for non-listening/malformed lines
    """
    parts = line.split(None, 5)
    if len(parts) < 5 or parts[0] != "LISTEN":
        return None

    parsed_address = _parse_local_address(parts[3])
    if parsed_address is None:
        return None
    address, port = parsed_address

    process_field = parts[5] if len(parts) > 5 else ""
    match = _PROCESS_PATTERN.search(process_field)
    pid = int(match.group(2)) if match else None
    process_name = match.group(1) if match else None

    return ScannedPort(port=port, address=address, pid=pid, process_name=process_name)


def scan_listening_ports() -> List[ScannedPort]:
    """
    Scan for TCP ports currently listening on the machine.

    Uses ``ss -H -tlnp`` to list listening sockets together with the owning
    process. Ports reported on multiple addresses (e.g. IPv4 and IPv6) are
    de-duplicated, keeping the first entry seen.

    :return: Scanned ports sorted by port number, or an empty list when
        ``ss`` is unavailable
    """
    try:
        result = subprocess.run(
            ["ss", "-H", "-tlnp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    if result.returncode != 0:
        return []

    ports: Dict[int, ScannedPort] = {}
    for line in result.stdout.splitlines():
        parsed = _parse_ss_line(line)
        if parsed is None or parsed.port in ports:
            continue
        ports[parsed.port] = parsed

    return sorted(ports.values(), key=lambda item: item.port)


def parse_proc_net_listen_uids(text: str) -> Dict[int, int]:
    """
    Extract the owning user id of every listening socket in ``/proc/net/tcp``.

    :param text: Contents of ``/proc/net/tcp`` or ``/proc/net/tcp6``
    :return: Mapping of TCP port to owning user id
    """
    owners: Dict[int, int] = {}

    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8 or fields[3] != TCP_STATE_LISTEN:
            continue

        _address, separator, hex_port = fields[1].rpartition(":")
        if not separator:
            continue

        try:
            port = int(hex_port, 16)
            uid = int(fields[7])
        except ValueError:
            continue

        owners.setdefault(port, uid)

    return owners


def socket_owner_for_port(port: int) -> Optional[str]:
    """
    Return the user account owning a listening socket.

    ``ss -p`` only reveals process details for sockets of the calling user, so a
    database listening as its own system user shows up without a process name.
    Reading the owner from ``/proc/net/tcp`` explains why, without needing root.

    :param port: TCP port number
    :return: User name, the numeric uid as text when it has no name, or None
    """
    for path in PROC_NET_TCP_FILES:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        uid = parse_proc_net_listen_uids(text).get(port)
        if uid is None:
            continue

        try:
            return pwd.getpwuid(uid).pw_name
        except KeyError:
            return str(uid)

    return None


def read_process_cwd(pid: int) -> Optional[str]:
    """
    Return the current working directory of a running process.

    :param pid: Process ID
    :return: Absolute working directory path, or None when unavailable
    """
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def read_process_command_line(pid: int) -> List[str]:
    """
    Return the argument list a running process was launched with.

    :param pid: Process ID
    :return: Command-line arguments, or an empty list when unavailable
    """
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        return []

    return [part for part in raw.decode("utf-8", errors="replace").split("\x00") if part]


def suggest_command_for_port(pid: int, port: int) -> str:
    """
    Build a best-effort start command for a process, with the port replaced
    by the ``{port}`` placeholder used by managed server commands.

    :param pid: Process ID
    :param port: Port the process is listening on
    :return: Reconstructed command line, or an empty string when unavailable
    """
    parts = read_process_command_line(pid)
    if not parts:
        return ""

    port_token = str(port)
    substituted = [
        "{port}" if part == port_token else re.sub(rf"={port_token}$", "={port}", part)
        for part in parts
    ]
    return shlex.join(substituted)

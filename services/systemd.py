"""Query and control systemd units for services that projects depend on.

This module deliberately exposes only ``start``, ``stop`` and ``restart``.
Enabling or disabling a unit at boot stays with systemd, so the application
never competes with it over a second source of truth.
"""

import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

SHOW_PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "MainPID",
)

ALLOWED_ACTIONS = ("start", "stop", "restart")

QUERY_TIMEOUT_SECONDS = 5.0
ACTION_TIMEOUT_SECONDS = 180.0

_AUTHENTICATION_HINTS = (
    "interactive authentication required",
    "access denied",
    "authentication is required",
    "not authorized",
    "permission denied",
)


@dataclass(frozen=True)
class UnitStatus:
    """Runtime state of a single systemd unit.

    :param unit: Unit name as resolved by systemd (aliases followed)
    :param load_state: ``loaded``, ``not-found``, ``masked``, ...
    :param active_state: ``active``, ``inactive``, ``failed``, ``activating``, ...
    :param sub_state: Unit-type specific sub state, e.g. ``running``
    :param enabled_state: ``enabled``, ``disabled``, ``static``, ...
    :param main_pid: PID of the unit's main process, or None when not running
    """

    unit: str
    load_state: str = "unknown"
    active_state: str = "unknown"
    sub_state: str = ""
    enabled_state: str = "unknown"
    main_pid: Optional[int] = None

    @property
    def exists(self) -> bool:
        """Return True when systemd knows a unit file for this name."""
        return self.load_state not in ("not-found", "unknown", "")

    @property
    def is_masked(self) -> bool:
        """Return True when the unit is masked and cannot be started."""
        return self.load_state == "masked"

    @property
    def is_running(self) -> bool:
        """Return True when the unit is currently active."""
        return self.active_state == "active"

    @property
    def is_failed(self) -> bool:
        """Return True when the unit failed."""
        return self.active_state == "failed"

    @property
    def is_transitioning(self) -> bool:
        """Return True while the unit is starting up or shutting down."""
        return self.active_state in ("activating", "deactivating", "reloading")

    @property
    def is_enabled_at_boot(self) -> Optional[bool]:
        """
        Report whether systemd starts this unit at boot.

        :return: True/False for enabled/disabled, None when not applicable
        """
        if self.enabled_state in ("enabled", "enabled-runtime"):
            return True
        if self.enabled_state in ("disabled", "masked", "masked-runtime"):
            return False
        return None

    def status_label(self) -> str:
        """
        Build a short runtime status label for the server list.

        :return: Human-readable status text
        """
        if not self.exists:
            return "Not installed"
        if self.is_masked:
            return "Masked"
        if self.active_state == "activating":
            return "Starting..."
        if self.active_state == "deactivating":
            return "Stopping..."
        if self.is_failed:
            return "Failed"
        if self.is_running:
            return "Running"
        return "Stopped"


def systemctl_available() -> bool:
    """
    Check whether ``systemctl`` can be used on this machine.

    :return: True when the systemctl binary is on PATH
    """
    return shutil.which("systemctl") is not None


def parse_show_output(text: str) -> Dict[str, str]:
    """
    Parse ``systemctl show`` output into a property mapping.

    :param text: Raw ``KEY=value`` lines as printed by systemctl
    :return: Mapping of property name to raw value
    """
    properties: Dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        properties[key.strip()] = value.strip()
    return properties


def build_unit_status(unit: str, properties: Dict[str, str]) -> UnitStatus:
    """
    Turn parsed systemctl properties into a UnitStatus.

    :param unit: Unit name that was queried
    :param properties: Property mapping from :func:`parse_show_output`
    :return: Parsed unit status
    """
    main_pid: Optional[int] = None
    raw_pid = properties.get("MainPID", "0")
    try:
        parsed_pid = int(raw_pid)
    except ValueError:
        parsed_pid = 0
    if parsed_pid > 0:
        main_pid = parsed_pid

    return UnitStatus(
        unit=properties.get("Id") or unit,
        load_state=properties.get("LoadState", "unknown"),
        active_state=properties.get("ActiveState", "unknown"),
        sub_state=properties.get("SubState", ""),
        enabled_state=properties.get("UnitFileState", "unknown"),
        main_pid=main_pid,
    )


def unit_status(unit: str) -> UnitStatus:
    """
    Read the current state of a systemd unit.

    :param unit: Unit name, e.g. ``mariadb.service``
    :return: Unit status; a non-existent unit reports ``exists == False``
    """
    if not systemctl_available():
        return UnitStatus(unit=unit, load_state="not-found")

    command = ["systemctl", "show", unit, "--no-pager"]
    command += [f"--property={name}" for name in SHOW_PROPERTIES]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=QUERY_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return UnitStatus(unit=unit, load_state="not-found")

    return build_unit_status(unit, parse_show_output(result.stdout))


def needs_authentication(message: str) -> bool:
    """
    Detect whether a failed systemctl call was rejected for missing privileges.

    :param message: Combined stdout/stderr of the failed call
    :return: True when the call should be retried with elevated privileges
    """
    lowered = message.lower()
    return any(hint in lowered for hint in _AUTHENTICATION_HINTS)


def _run_action(command: list, timeout: float) -> Tuple[bool, str]:
    """
    Run one systemctl invocation and capture its output.

    :param command: Full argument list to execute
    :param timeout: Timeout in seconds
    :return: Tuple of success flag and combined output
    """
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"'{' '.join(command)}' did not finish within {int(timeout)} seconds."
    except OSError as exc:
        return False, str(exc)

    output = (result.stdout or "").strip()
    return result.returncode == 0, output


def run_unit_action(action: str, unit: str, timeout: float = ACTION_TIMEOUT_SECONDS) -> Tuple[bool, str]:
    """
    Start, stop, or restart a systemd unit, asking for authorization if needed.

    The plain ``systemctl`` call is tried first so systemd's own polkit
    integration can prompt through the desktop's authentication agent. Only
    when that call is rejected for missing privileges is ``pkexec`` used as a
    fallback. Nothing is ever elevated permanently.

    This call blocks while the user authenticates, so run it off the UI thread.

    :param action: One of ``start``, ``stop``, ``restart``
    :param unit: Unit name to act on
    :param timeout: Timeout in seconds for each attempt
    :return: Tuple of success flag and error message (empty on success)
    :raises ValueError: When an unsupported action is requested
    """
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported systemd action: {action}")

    if not systemctl_available():
        return False, "systemctl is not available on this system."

    succeeded, output = _run_action(["systemctl", action, unit], timeout)
    if succeeded:
        return True, ""

    if not needs_authentication(output):
        return False, output or f"systemctl {action} {unit} failed."

    if shutil.which("pkexec") is None:
        return False, (
            "Authorization is required to "
            f"{action} '{unit}', but no polkit agent (pkexec) was found."
        )

    succeeded, fallback_output = _run_action(["pkexec", "systemctl", action, unit], timeout)
    if succeeded:
        return True, ""

    return False, fallback_output or output or f"systemctl {action} {unit} failed."


class ServiceMonitor:
    """Caches unit lookups so one refresh cycle triggers one systemctl call.

    The server list is rebuilt from several places within the same tick, and
    each rebuild asks for every service's state. Without caching that spawns a
    subprocess per row per read.
    """

    def __init__(self, ttl_seconds: float = 1.0) -> None:
        """
        :param ttl_seconds: How long a cached unit status stays valid
        """
        self._ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[float, UnitStatus]] = {}

    def status(self, unit: str) -> UnitStatus:
        """
        Return the unit status, reusing a recent lookup when possible.

        :param unit: Unit name to query
        :return: Cached or freshly read unit status
        """
        cached = self._cache.get(unit)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._ttl_seconds:
            return cached[1]

        status = unit_status(unit)
        self._cache[unit] = (now, status)
        return status

    def invalidate(self, unit: Optional[str] = None) -> None:
        """
        Drop cached state so the next read hits systemd again.

        :param unit: Unit to invalidate, or None to clear the whole cache
        """
        if unit is None:
            self._cache.clear()
            return
        self._cache.pop(unit, None)

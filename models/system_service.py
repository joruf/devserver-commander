"""Data model for a systemd-managed service a project depends on."""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SystemService:
    """A database or cache service managed by systemd, not by this application.

    Unlike :class:`~models.server_project.ServerProject`, a service is never
    launched as a child process. It is started and stopped through ``systemctl``,
    and its boot behavior stays under systemd's control.

    :param name: Display name shown in the server list, e.g. ``MariaDB``
    :param unit: systemd unit name, e.g. ``mariadb.service``
    :param port: TCP port the service listens on, or None when unknown
    :param data_directory: Directory holding the service's data files. Purely
        informational: it is never used as a working directory.
    """

    name: str
    unit: str
    port: Optional[int] = None
    data_directory: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict suitable for JSON storage."""
        return {
            "name": self.name,
            "unit": self.unit,
            "port": self.port,
            "data_directory": self.data_directory,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemService":
        """
        Build a SystemService from a dict previously produced by to_dict().

        :param data: Raw mapping read from the configuration file
        :return: Parsed service entry
        :raises KeyError: When a required key is missing
        :raises ValueError: When the unit name is empty
        """
        unit = str(data["unit"]).strip()
        if not unit:
            raise ValueError("A service entry needs a systemd unit name.")

        port_value = data.get("port")
        return cls(
            name=str(data["name"]),
            unit=unit,
            port=int(port_value) if port_value not in (None, "") else None,
            data_directory=str(data.get("data_directory") or ""),
        )

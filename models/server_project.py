"""Data model for a managed development server project."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ServerProject:
    """A single project entry: where it lives and how to start its server."""

    name: str
    directory: str
    command: str
    port: Optional[int] = None
    env: Dict[str, str] = field(default_factory=dict)
    autostart: bool = False

    def build_command(self) -> str:
        """Return the command with the {port} placeholder substituted."""
        if self.port is not None:
            return self.command.replace("{port}", str(self.port))
        return self.command

    def build_env(self) -> Dict[str, str]:
        """Return environment variables with {port} placeholders substituted."""
        if self.port is None:
            return dict(self.env)

        return {
            key: value.replace("{port}", str(self.port))
            for key, value in self.env.items()
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict suitable for JSON storage."""
        return {
            "name": self.name,
            "directory": self.directory,
            "command": self.command,
            "port": self.port,
            "env": dict(self.env),
            "autostart": self.autostart,
        }

    def runtime_config_differs(self, other: "ServerProject") -> bool:
        """
        Check whether applying another project would require restarting the server.

        :param other: Updated project configuration
        :return: True when command, paths, port, env, or name changed
        """
        return (
            self.name != other.name
            or self.directory != other.directory
            or self.command != other.command
            or self.port != other.port
            or self.env != other.env
        )

    @staticmethod
    def _parse_autostart(value: Any) -> bool:
        """
        Parse an autostart value from JSON or form input.

        :param value: Raw autostart value
        :return: Parsed boolean
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServerProject":
        """Build a ServerProject from a dict previously produced by to_dict()."""
        return cls(
            name=str(data["name"]),
            directory=str(data["directory"]),
            command=str(data["command"]),
            port=int(data["port"]) if data.get("port") not in (None, "") else None,
            env=dict(data.get("env") or {}),
            autostart=cls._parse_autostart(data.get("autostart", False)),
        )

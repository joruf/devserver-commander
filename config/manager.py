"""Load and save the DevServer Commander server configuration."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import ServerProject, SystemService
from paths import CONFIG_FILE
from services.dev_tools import default_command_for_tool
from services.service_catalog import is_catalog_unit


def default_projects() -> List[ServerProject]:
    """Seed data used when no configuration file exists yet."""
    docs = str(Path.home() / "Documents")
    if not Path(docs).is_dir() and (Path.home() / "Dokumente").is_dir():
        docs = str(Path.home() / "Dokumente")

    common_env = {"XDEBUG_SESSION": "1"}
    return [
        ServerProject(
            name="PM-Tool MVC",
            directory=f"{docs}/pmtool",
            command="/usr/bin/php8.2 -S localhost:{port} -t public/ public/router.php",
            port=8001,
            env={**common_env, "PHP_CLI_SERVER_WORKERS": "6"},
        ),
        ServerProject(
            name="ServiceReports MVC",
            directory=f"{docs}/servicereports",
            command="/usr/bin/php8.2 -S localhost:{port} -t public/",
            port=8002,
            env=dict(common_env),
        ),
        ServerProject(
            name="PM-Tool Legacy",
            directory=f"{docs}/pmtool-legacy",
            command="/usr/bin/php8.2 -S localhost:{port} -t html/",
            port=8003,
            env=dict(common_env),
        ),
        ServerProject(
            name="ServiceReports Legacy",
            directory=f"{docs}/servicereports-legacy",
            command="/usr/bin/php8.2 -S localhost:{port} -t html/",
            port=8004,
            env=dict(common_env),
        ),
        ServerProject(
            name="MailHog",
            directory=docs,
            command=default_command_for_tool("mailhog"),
            port=8025,
            env={},
        ),
    ]


class ConfigManager:
    """Reads and writes the JSON server list, seeding defaults on first run."""

    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self.path = path

    def _read_raw(self) -> Dict[str, Any]:
        """
        Read the raw configuration mapping from disk.

        :return: Parsed JSON object, or an empty mapping when unreadable
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return raw if isinstance(raw, dict) else {}

    def load(self) -> List[ServerProject]:
        """Load servers from disk, seeding defaults if no config exists yet."""
        if not self.path.is_file():
            projects = default_projects()
            self.save(projects)
            return projects

        projects: List[ServerProject] = []
        for entry in self._read_raw().get("servers", []):
            try:
                projects.append(ServerProject.from_dict(entry))
            except (KeyError, ValueError, TypeError):
                continue
        return projects

    def load_services(self) -> List[SystemService]:
        """
        Load the systemd services stored alongside the server list.

        Entries outside the curated catalog are dropped, so a hand-edited
        configuration file cannot turn this application into a systemd front end.

        :return: Configured services that are part of the catalog
        """
        services: List[SystemService] = []
        for entry in self._read_raw().get("services", []):
            try:
                service = SystemService.from_dict(entry)
            except (KeyError, ValueError, TypeError):
                continue
            if is_catalog_unit(service.unit):
                services.append(service)
        return services

    def save(
        self,
        projects: List[ServerProject],
        services: Optional[List[SystemService]] = None,
    ) -> None:
        """
        Persist the given servers, creating the config file if needed.

        :param projects: Server entries to write
        :param services: Service entries to write; when omitted, the services
            already on disk are preserved so server-only saves cannot drop them
        """
        if services is None:
            services = self.load_services() if self.path.is_file() else []

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "servers": [project.to_dict() for project in projects],
            "services": [service.to_dict() for service in services],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

"""Load and save the DevServer Commander server configuration."""

import json
from pathlib import Path
from typing import List

from models import ServerProject
from paths import CONFIG_FILE
from services.dev_tools import default_command_for_tool


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

    def load(self) -> List[ServerProject]:
        """Load servers from disk, seeding defaults if no config exists yet."""
        if not self.path.is_file():
            projects = default_projects()
            self.save(projects)
            return projects

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        projects: List[ServerProject] = []
        for entry in raw.get("servers", []):
            try:
                projects.append(ServerProject.from_dict(entry))
            except (KeyError, ValueError, TypeError):
                continue
        return projects

    def save(self, projects: List[ServerProject]) -> None:
        """Persist the given servers, creating the config file if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"servers": [project.to_dict() for project in projects]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

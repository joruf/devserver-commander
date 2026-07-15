"""Automatic project detection and validation for the Add Project dialog."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from config.validation import validate_server_setup
from services.node import build_node_command
from services.php import build_php_builtin_command, default_php_binary


@dataclass(frozen=True)
class ProjectDetectionResult:
    """
    Result of a successful project layout detection.

    :param server_type: One of ``php``, ``node``, or ``custom``
    :param directory: Working directory to store in the project config
    :param suggested_name: Suggested project name derived from the path
    :param suggested_port: Suggested port for the detected project type
    :param detected_layout: Human-readable label of the detected layout
    :param docroot: Document root value for the PHP ``-t`` option
    :param router: Optional router script path, relative to ``directory``
    :param node_mode: Node run mode key (``npm``, ``npx``, ``node``)
    :param node_target: Node command target (script, args, or entry file)
    :param use_port_env: Whether Node should use ``PORT={port}`` env
    :param command: Stored command for custom server types
    :param validation_error: Validation error text or None when valid
    """

    server_type: str
    directory: str
    suggested_name: str
    suggested_port: Optional[int]
    detected_layout: str
    docroot: str = "public/"
    router: str = ""
    node_mode: str = "npm"
    node_target: str = "dev"
    use_port_env: bool = True
    command: str = ""
    validation_error: Optional[str] = None


def _suggest_name(path: Path) -> str:
    """
    Build a readable project name from a filesystem path.

    :param path: Path chosen as project root
    :return: Suggested project name
    """
    token = path.name.strip()
    if not token:
        return "Project"

    spaced = re.sub(r"[-_]+", " ", token).strip()
    if not spaced:
        return token
    return spaced.title()


def _read_package_scripts(root: Path) -> Dict[str, str]:
    """
    Read npm scripts from package.json.

    :param root: Candidate project root
    :return: Script mapping or empty dict when unavailable
    """
    package_json = root / "package.json"
    if not package_json.is_file():
        return {}

    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    scripts = payload.get("scripts", {})
    if not isinstance(scripts, dict):
        return {}

    return {
        str(key): str(value)
        for key, value in scripts.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _validate_detection(result: ProjectDetectionResult) -> Optional[str]:
    """
    Validate a detected configuration using existing server validators.

    :param result: Detected project configuration
    :return: Validation error or None
    """
    if result.server_type == "php":
        php_binary = default_php_binary()
        command = build_php_builtin_command(
            php_binary,
            result.docroot,
            result.router,
        )
        return validate_server_setup(
            server_type="php",
            directory=result.directory,
            command=command,
            php_binary=php_binary,
            docroot=result.docroot,
            router=result.router,
        )

    if result.server_type == "node":
        command = build_node_command(result.node_mode, result.node_target)
        return validate_server_setup(
            server_type="node",
            directory=result.directory,
            command=command,
            node_mode=result.node_mode,
            node_target=result.node_target,
        )

    command = result.command.strip()
    if not command:
        return "Detected custom command is empty."
    return validate_server_setup(
        server_type="custom",
        directory=result.directory,
        command=command,
    )


def _result_with_validation(result: ProjectDetectionResult) -> ProjectDetectionResult:
    """
    Attach a validation outcome to a detection result.

    :param result: Detected settings
    :return: Result with ``validation_error`` populated when invalid
    """
    return ProjectDetectionResult(
        server_type=result.server_type,
        directory=result.directory,
        suggested_name=result.suggested_name,
        suggested_port=result.suggested_port,
        detected_layout=result.detected_layout,
        docroot=result.docroot,
        router=result.router,
        node_mode=result.node_mode,
        node_target=result.node_target,
        use_port_env=result.use_port_env,
        command=result.command,
        validation_error=_validate_detection(result),
    )


def detect_project_settings(main_path: str) -> Optional[ProjectDetectionResult]:
    """
    Detect common project layouts from a chosen main path.

    Detection order:
    1. PHP layouts (Joomla/public/web/www/html/root index.php)
    2. Node.js layouts (package.json scripts or direct entry file)
    3. Python/Django layouts
    4. Static site fallback (Python HTTP server)

    :param main_path: User-selected project main path
    :return: Detection result or None when no known layout matches
    """
    root = Path(main_path).expanduser()
    if not root.is_dir():
        return None

    suggested_name = _suggest_name(root)

    joomla_dir = root / "joomla"
    if joomla_dir.is_dir():
        return _result_with_validation(
            ProjectDetectionResult(
                server_type="php",
                directory=str(joomla_dir),
                suggested_name=suggested_name,
                suggested_port=8001,
                detected_layout="Joomla subfolder",
                docroot="/",
            )
        )

    for docroot_dir in ("public", "web", "www", "html"):
        candidate = root / docroot_dir
        if not candidate.is_dir():
            continue

        router = ""
        router_php = candidate / "router.php"
        front_controller = candidate / "index.php"
        if router_php.is_file():
            router = f"{docroot_dir}/router.php"
        elif front_controller.is_file():
            router = f"{docroot_dir}/index.php"

        return _result_with_validation(
            ProjectDetectionResult(
                server_type="php",
                directory=str(root),
                suggested_name=suggested_name,
                suggested_port=8001,
                detected_layout=f"{docroot_dir}/ webroot",
                docroot=f"{docroot_dir}/",
                router=router,
            )
        )

    if (root / "index.php").is_file():
        return _result_with_validation(
            ProjectDetectionResult(
                server_type="php",
                directory=str(root),
                suggested_name=suggested_name,
                suggested_port=8001,
                detected_layout="Root index.php",
                docroot="/",
            )
        )

    scripts = _read_package_scripts(root)
    if scripts:
        preferred_scripts = ("dev", "start", "serve", "preview")
        selected_script = next((name for name in preferred_scripts if name in scripts), None)
        if selected_script is None:
            selected_script = sorted(scripts.keys())[0]

        script_value = scripts.get(selected_script, "")
        suggested_port = 3000
        if "vite" in script_value or selected_script == "preview":
            suggested_port = 5173
        elif selected_script == "start":
            suggested_port = 3000

        return _result_with_validation(
            ProjectDetectionResult(
                server_type="node",
                directory=str(root),
                suggested_name=suggested_name,
                suggested_port=suggested_port,
                detected_layout=f"Node package.json script '{selected_script}'",
                node_mode="npm",
                node_target=selected_script,
                use_port_env=True,
            )
        )

    for entry_file in ("server.js", "app.js", "index.js"):
        if not (root / entry_file).is_file():
            continue

        return _result_with_validation(
            ProjectDetectionResult(
                server_type="node",
                directory=str(root),
                suggested_name=suggested_name,
                suggested_port=3000,
                detected_layout=f"Node entry file '{entry_file}'",
                node_mode="node",
                node_target=entry_file,
                use_port_env=True,
            )
        )

    if (root / "manage.py").is_file():
        return _result_with_validation(
            ProjectDetectionResult(
                server_type="custom",
                directory=str(root),
                suggested_name=suggested_name,
                suggested_port=8000,
                detected_layout="Django manage.py",
                command="python3 manage.py runserver localhost:{port}",
            )
        )

    if (root / "index.html").is_file():
        return _result_with_validation(
            ProjectDetectionResult(
                server_type="custom",
                directory=str(root),
                suggested_name=suggested_name,
                suggested_port=8080,
                detected_layout="Static site",
                command="python3 -m http.server {port}",
            )
        )

    return None

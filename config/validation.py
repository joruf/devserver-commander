"""Validation helpers for server configuration."""

import json
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from models import ServerProject
from services.php import build_php_builtin_command, is_working_directory_docroot

PLACEHOLDER_PORT = "65535"
_NAME_SUFFIX_PATTERN = re.compile(r"^(?P<base>.+?)(?P<num>\d+)$")


def _split_name_suffix(name: str) -> tuple[str, Optional[int]]:
    """
    Split a project name into a base label and an optional numeric suffix.

    :param name: Project name to parse
    :return: Base name and optional trailing number
    """
    match = _NAME_SUFFIX_PATTERN.match(name)
    if not match:
        return name, None
    return match.group("base"), int(match.group("num"))


def _numbered_variant_suffix(base: str, name: str) -> Optional[int]:
    """
    Return the numeric suffix of a numbered project name variant.

    :param base: Shared project name base
    :param name: Existing project name to inspect
    :return: Numeric suffix or None when the name is not a numbered variant
    """
    if not name.startswith(base) or name == base:
        return None

    suffix = name[len(base):]
    if suffix.isdigit():
        return int(suffix)
    return None


def make_unique_project_name(
    projects: List[ServerProject],
    desired_name: str,
    exclude_name: Optional[str] = None,
) -> str:
    """
    Return a project name that does not conflict with existing projects.

    When the desired name already exists, append or increment a trailing number.
    If the desired name already ends with a number, that number is incremented.
    Otherwise the highest existing suffix for the same base name is incremented.

    :param projects: Existing server projects to check against
    :param desired_name: Requested project name
    :param exclude_name: Optional project name to ignore (used while editing)
    :return: Unique project name
    """
    desired_name = desired_name.strip()
    existing = {
        project.name
        for project in projects
        if exclude_name is None or project.name != exclude_name
    }
    if desired_name not in existing:
        return desired_name

    base, input_suffix = _split_name_suffix(desired_name)
    if input_suffix is not None:
        candidate = input_suffix + 1
    else:
        used_suffixes = [
            suffix
            for name in existing
            if (suffix := _numbered_variant_suffix(base, name)) is not None
        ]
        candidate = max(used_suffixes, default=1) + 1

    while True:
        candidate_name = f"{base}{candidate}"
        if candidate_name not in existing:
            return candidate_name
        candidate += 1


def find_name_owner(
    projects: List[ServerProject],
    name: str,
    exclude_name: Optional[str] = None,
) -> Optional[str]:
    """
    Return the name of a project that already uses the given project name.

    :param projects: Existing server projects to check against
    :param name: Project name to look up
    :param exclude_name: Optional project name to ignore (used while editing)
    :return: Conflicting project name or None
    """
    for project in projects:
        if project.name != name:
            continue
        if exclude_name and project.name == exclude_name:
            continue
        return project.name
    return None


def find_port_owner(
    projects: List[ServerProject],
    port: int,
    exclude_name: Optional[str] = None,
) -> Optional[str]:
    """
    Return the name of the project that already uses the given port.

    :param projects: Existing server projects to check against
    :param port: Port number to look up
    :param exclude_name: Optional project name to ignore (used while editing)
    :return: Conflicting project name or None
    """
    for project in projects:
        if project.port != port:
            continue
        if exclude_name and project.name == exclude_name:
            continue
        return project.name
    return None


def make_unique_project_port(
    projects: List[ServerProject],
    desired_port: int,
    exclude_name: Optional[str] = None,
) -> int:
    """
    Return a port number that is not used by another project.

    When the desired port already exists, the next higher unused port is used.

    :param projects: Existing server projects to check against
    :param desired_port: Requested port number
    :param exclude_name: Optional project name to ignore (used while editing)
    :return: Unique port number, or a value above 65535 when none is available
    """
    existing_ports = {
        project.port
        for project in projects
        if project.port is not None and (exclude_name is None or project.name != exclude_name)
    }
    if desired_port not in existing_ports:
        return desired_port

    candidate = desired_port + 1
    while candidate <= 65535 and candidate in existing_ports:
        candidate += 1
    return candidate


def _resolve_docroot_path(project_directory: str, docroot: str) -> Path:
    """
    Resolve the PHP document root relative to the project directory.

    :param project_directory: Server working directory
    :param docroot: Document root path or empty string for the working directory
    :return: Absolute document root path
    """
    project_path = Path(project_directory).expanduser()
    if is_working_directory_docroot(docroot):
        return project_path
    return project_path / docroot.strip()


def _resolve_project_path(project_directory: str, relative_path: str) -> Path:
    return Path(project_directory).expanduser() / relative_path.strip()


def validate_directory_exists(project_directory: str) -> Optional[str]:
    """
    Validate that the working directory exists.

    :param project_directory: Server working directory
    :return: Error message or None when valid
    """
    path = Path(project_directory).expanduser()
    if not path.is_dir():
        return f"Working directory does not exist:\n{path}"
    return None


def validate_docroot_exists(project_directory: str, docroot: str) -> Optional[str]:
    """
    Validate that the document root exists relative to the project directory.

    :param project_directory: Server working directory
    :param docroot: Document root path, e.g. ``public/``; empty uses the working directory
    :return: Error message or None when valid
    """
    path = _resolve_docroot_path(project_directory, docroot)
    if not path.is_dir():
        return f"Document root does not exist:\n{path}"
    return None


def validate_router_exists(project_directory: str, router: str) -> Optional[str]:
    """
    Validate that the router script exists relative to the project directory.

    :param project_directory: Server working directory
    :param router: Router script path, e.g. ``public/index.php``
    :return: Error message or None when valid or empty
    """
    router = router.strip()
    if not router:
        return None

    path = _resolve_project_path(project_directory, router)
    if not path.is_file():
        return f"Router script does not exist:\n{path}"
    return None


def _resolve_executable_path(executable: str, project_directory: str) -> Path:
    token = executable.strip()
    if token.startswith("./") or token.startswith("../"):
        return (_resolve_project_path(project_directory, token)).resolve()

    path = Path(token).expanduser()
    if path.is_absolute() or "/" in token:
        return path

    found = shutil.which(token)
    if found:
        return Path(found)

    return path


def validate_executable(executable: str, project_directory: str) -> Optional[str]:
    """
    Validate that a command executable exists and can be executed.

    :param executable: Executable path or command name
    :param project_directory: Server working directory for relative paths
    :return: Error message or None when valid
    """
    path = _resolve_executable_path(executable, project_directory)

    if "/" in executable or executable.startswith("."):
        if not path.is_file():
            return f"Executable not found:\n{path}"
        if not os.access(path, os.X_OK):
            return f"File is not executable:\n{path}"
        return None

    if not shutil.which(executable):
        return f"Command not found on PATH:\n{executable}"

    return None


def _split_command(command: str) -> tuple[Optional[List[str]], Optional[str]]:
    normalized = command.replace("{port}", PLACEHOLDER_PORT)
    try:
        return shlex.split(normalized), None
    except ValueError as exc:
        return None, f"Invalid command syntax:\n{exc}"


def _validate_script_file(project_directory: str, script_path: str) -> Optional[str]:
    token = script_path.strip()
    if not token or token.startswith("-"):
        return None

    if Path(token).is_absolute():
        path = Path(token).expanduser()
    else:
        path = _resolve_project_path(project_directory, token)

    if not path.is_file():
        return f"Script file not found:\n{path}"
    return None


def validate_npm_script(project_directory: str, script_name: str) -> Optional[str]:
    """
    Validate that an npm script exists in the project package.json.

    :param project_directory: Server working directory
    :param script_name: npm script name
    :return: Error message or None when valid
    """
    script_name = script_name.strip()
    if not script_name:
        return "npm script name must not be empty."

    package_json = Path(project_directory).expanduser() / "package.json"
    if not package_json.is_file():
        return f"package.json not found in:\n{package_json.parent}"

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"package.json could not be read:\n{package_json}"

    scripts = data.get("scripts", {})
    if script_name not in scripts:
        available = ", ".join(sorted(scripts.keys())) if scripts else "(none)"
        return (
            f"npm script '{script_name}' was not found in package.json.\n"
            f"Available scripts: {available}"
        )

    return None


def validate_php_command_matches_form(
    command: str,
    php_binary: str,
    docroot: str,
    router: str,
    php_options: str = "",
) -> Optional[str]:
    """
    Validate that a stored PHP command matches the form values.

    :param command: Stored launch command
    :param php_binary: Selected PHP binary path
    :param docroot: Document root path from the form
    :param router: Optional router script path
    :param php_options: Additional PHP CLI options before ``-S``
    :return: Error message or None when valid
    """
    expected = build_php_builtin_command(php_binary, docroot, router, php_options)
    normalized_command = command.replace("{port}", PLACEHOLDER_PORT)
    normalized_expected = expected.replace("{port}", PLACEHOLDER_PORT)
    if normalized_command != normalized_expected:
        return (
            "The generated PHP command does not match the form fields.\n\n"
            f"Expected:\n{normalized_expected}\n\n"
            f"Configured:\n{normalized_command}"
        )
    return None


def validate_php_setup(
    project_directory: str,
    php_binary: str,
    docroot: str,
    router: str,
) -> Optional[str]:
    """
    Validate PHP built-in server configuration.

    :param project_directory: Server working directory
    :param php_binary: Selected PHP binary path
    :param docroot: Document root path
    :param router: Optional router script path
    :return: Error message or None when valid
    """
    error = validate_executable(php_binary, project_directory)
    if error:
        return f"PHP binary is invalid.\n\n{error}"

    error = validate_docroot_exists(project_directory, docroot)
    if error:
        return error

    error = validate_router_exists(project_directory, router)
    if error:
        return error

    return None


def validate_node_setup(
    project_directory: str,
    node_mode: str,
    node_target: str,
    command: str,
) -> Optional[str]:
    """
    Validate Node.js server configuration.

    :param project_directory: Server working directory
    :param node_mode: One of ``npm``, ``npx``, or ``node``
    :param node_target: npm script, npx arguments, or node entry file
    :param command: Stored launch command
    :return: Error message or None when valid
    """
    node_target = node_target.strip()
    if not node_target:
        return "Script / command must not be empty."

    parts, error = _split_command(command)
    if error:
        return error
    if not parts:
        return "Command must not be empty."

    if node_mode == "npm":
        error = validate_executable("npm", project_directory)
        if error:
            return f"npm is not available.\n\n{error}"

        script_name = node_target.split(" ", 1)[0]
        return validate_npm_script(project_directory, script_name)

    if node_mode == "npx":
        error = validate_executable("npx", project_directory)
        if error:
            return f"npx is not available.\n\n{error}"
        return None

    error = validate_executable("node", project_directory)
    if error:
        return f"node is not available.\n\n{error}"

    return _validate_script_file(project_directory, node_target)


def validate_launch_command(project_directory: str, command: str) -> Optional[str]:
    """
    Validate a stored custom launch command.

    :param project_directory: Server working directory
    :param command: Stored launch command
    :return: Error message or None when valid
    """
    parts, error = _split_command(command)
    if error:
        return error
    if not parts:
        return "Command must not be empty."

    executable = parts[0]
    error = validate_executable(executable, project_directory)
    if error:
        return error

    if executable in {"npm", "npx"}:
        return validate_node_setup(
            project_directory,
            executable,
            " ".join(parts[2:]) if executable == "npm" and len(parts) >= 3 and parts[1] == "run" else " ".join(parts[1:]),
            command,
        )

    if executable == "node" and len(parts) >= 2:
        return _validate_script_file(project_directory, parts[1])

    if len(parts) >= 3 and parts[1] == "-m":
        return None

    if len(parts) >= 2 and not parts[1].startswith("-"):
        token = parts[1]
        if re.search(r"\.(js|py|rb|pl|sh)$", token):
            return _validate_script_file(project_directory, token)

    return None


def validate_server_setup(
    server_type: str,
    directory: str,
    command: str,
    php_binary: str = "",
    docroot: str = "",
    router: str = "",
    php_options: str = "",
    node_mode: str = "",
    node_target: str = "",
) -> Optional[str]:
    """
    Validate a server configuration before it is saved.

    :param server_type: One of ``php``, ``node``, or ``custom``
    :param directory: Server working directory
    :param command: Stored launch command
    :param php_binary: Selected PHP binary for PHP servers
    :param docroot: PHP document root
    :param router: Optional PHP router script
    :param php_options: Additional PHP CLI options before ``-S``
    :param node_mode: Node.js run mode key
    :param node_target: Node.js script or command target
    :return: Error message or None when valid
    """
    error = validate_directory_exists(directory)
    if error:
        return error

    if server_type == "php":
        error = validate_php_setup(directory, php_binary, docroot, router)
        if error:
            return error
        return validate_php_command_matches_form(command, php_binary, docroot, router, php_options)

    if server_type == "node":
        return validate_node_setup(directory, node_mode, node_target, command)

    return validate_launch_command(directory, command)

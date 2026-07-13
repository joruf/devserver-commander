"""Detect installed PHP CLI binaries and help install additional versions."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

PHP_BIN_DIRS = (Path("/usr/bin"), Path("/usr/local/bin"))
PHP_VERSION_PATTERN = re.compile(r"^php(\d+\.\d+)$")
PHP_COMMAND_PATTERN = re.compile(
    r"^(?P<binary>(?:/usr/bin/|/usr/local/bin/)?php(?:\d+\.\d+)?)\s+-S\s+",
    re.IGNORECASE,
)
DEFAULT_DOCROOT = "public/"
WORKING_DIRECTORY_DOCROOT = "/"


def is_working_directory_docroot(docroot: str) -> bool:
    """
    Return whether the document root refers to the project working directory.

    :param docroot: Document root value from the form or command
    :return: True when the working directory should be used
    """
    return docroot.strip() in {"", ".", "./", WORKING_DIRECTORY_DOCROOT}


def format_docroot_for_display(docroot: str) -> str:
    """
    Format a document root value for the project dialog input field.

    :param docroot: Document root value from a stored command or form field
    :return: Display value for the document root entry
    """
    if is_working_directory_docroot(docroot):
        return WORKING_DIRECTORY_DOCROOT
    return docroot


def _php_version_sort_key(label: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)", label)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def _read_php_version(binary: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            [str(binary), "-r", "echo PHP_VERSION;"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _normalize_docroot(docroot: str) -> str:
    """
    Normalize a document root for the PHP built-in server ``-t`` argument.

    :param docroot: Document root value from the form
    :return: Value used in the generated PHP command
    """
    if is_working_directory_docroot(docroot):
        return "."
    docroot = docroot.strip()
    if not docroot.endswith("/"):
        docroot += "/"
    return docroot


def detect_php_versions() -> List[Tuple[str, str]]:
    """Detect installed PHP CLI binaries on the system."""
    found: dict[str, str] = {}

    for bin_dir in PHP_BIN_DIRS:
        if not bin_dir.is_dir():
            continue
        for candidate in sorted(bin_dir.glob("php*")):
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            name = candidate.name
            binary = str(candidate.resolve())
            if name == "php":
                version = _read_php_version(candidate) or "default"
                label = f"php ({version})"
            elif PHP_VERSION_PATTERN.match(name):
                label = name.replace("php", "")
            else:
                continue
            if binary not in found.values():
                found[label] = binary

    return sorted(found.items(), key=lambda item: _php_version_sort_key(item[0]), reverse=True)


def default_php_binary(versions: Optional[List[Tuple[str, str]]] = None) -> str:
    """Return the preferred PHP binary path."""
    version_list = versions if versions is not None else detect_php_versions()
    if version_list:
        return version_list[0][1]

    default_php = shutil.which("php")
    if default_php:
        return default_php
    return "/usr/bin/php"


def build_php_builtin_command(
    binary: str,
    docroot: str = DEFAULT_DOCROOT,
    router: str = "",
) -> str:
    """Build a PHP built-in server start command for the given binary."""
    docroot = _normalize_docroot(docroot)
    command = f"{binary} -S localhost:{{port}} -t {docroot}"
    router = router.strip()
    if router:
        command += f" {router}"
    return command


def is_php_builtin_command(command: str) -> bool:
    """Return whether the given command looks like a PHP built-in server command."""
    return PHP_COMMAND_PATTERN.match(command.strip()) is not None


def extract_php_binary_from_command(command: str) -> Optional[str]:
    """Extract the PHP binary from a built-in server command, if present."""
    match = PHP_COMMAND_PATTERN.match(command.strip())
    if not match:
        return None
    return match.group("binary")


def extract_docroot_from_command(command: str) -> str:
    """Extract the document root from a PHP built-in server command."""
    match = re.search(r"-t\s+(\S+)", command)
    if not match:
        return DEFAULT_DOCROOT
    docroot = match.group(1)
    if docroot in {".", "./"}:
        return WORKING_DIRECTORY_DOCROOT
    if docroot == WORKING_DIRECTORY_DOCROOT:
        return WORKING_DIRECTORY_DOCROOT
    return docroot


def extract_router_from_command(command: str) -> str:
    """Extract the optional router script from a PHP built-in server command."""
    match = re.search(r"-t\s+\S+\s+(\S+)", command.strip())
    if not match:
        return ""
    return match.group(1)


def replace_php_binary_in_command(command: str, binary: str) -> str:
    """Replace the PHP binary at the start of a built-in server command."""
    command = command.strip()
    if PHP_COMMAND_PATTERN.match(command):
        return PHP_COMMAND_PATTERN.sub(f"{binary} -S ", command, count=1)
    return build_php_builtin_command(
        binary,
        extract_docroot_from_command(command),
        extract_router_from_command(command),
    )


def install_php_version(version: str) -> Tuple[bool, str]:
    """Start a terminal session that installs the requested PHP CLI package."""
    version = version.strip()
    if not re.fullmatch(r"\d+\.\d+", version):
        return False, "Version must look like 8.4."

    package = f"php{version}-cli"
    shell_command = (
        f"sudo apt update && sudo apt install -y {package}; "
        'echo; echo "Finished. You can close this window."; read -r -p "Press Enter..." _'
    )

    launchers = [
        ["x-terminal-emulator", "-e", "bash", "-lc", shell_command],
        ["gnome-terminal", "--", "bash", "-lc", shell_command],
        ["xfce4-terminal", "-e", "bash", "-lc", shell_command],
        ["konsole", "-e", "bash", "-lc", shell_command],
        ["xterm", "-e", "bash", "-lc", shell_command],
    ]

    for launcher in launchers:
        if shutil.which(launcher[0]) is None:
            continue
        try:
            subprocess.Popen(launcher)
            return True, f"Started installation of {package} in a terminal window."
        except OSError as exc:
            return False, f"Could not open a terminal: {exc}"

    return False, "No terminal emulator found to run the installation."

"""Detect installed PHP CLI binaries and help install additional versions."""

import os
import re
import shutil
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

PHP_BIN_DIRS = (Path("/usr/bin"), Path("/usr/local/bin"))
PHP_VERSION_PATTERN = re.compile(r"^php(\d+\.\d+)$")
PHP_BINARY_PATTERN = re.compile(r"^php(?:\d+(?:\.\d+)?)?$", re.IGNORECASE)
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
    php_options: str = "",
) -> str:
    """Build a PHP built-in server start command for the given binary."""
    docroot = _normalize_docroot(docroot)
    php_options = php_options.strip()
    command = binary.strip()
    if php_options:
        command += f" {php_options}"
    command += f" -S localhost:{{port}} -t {docroot}"
    router = router.strip()
    if router:
        command += f" {router}"
    return command


def _split_php_command(command: str) -> Optional[List[str]]:
    try:
        return shlex.split(command.strip())
    except ValueError:
        return None


def _is_php_binary_token(token: str) -> bool:
    binary_name = Path(token).name
    return PHP_BINARY_PATTERN.fullmatch(binary_name) is not None


def _php_command_parts(command: str) -> Optional[List[str]]:
    parts = _split_php_command(command)
    if not parts:
        return None
    if not _is_php_binary_token(parts[0]):
        return None
    if "-S" not in parts:
        return None
    return parts


def is_php_builtin_command(command: str) -> bool:
    """Return whether the given command looks like a PHP built-in server command."""
    return _php_command_parts(command) is not None


def extract_php_binary_from_command(command: str) -> Optional[str]:
    """Extract the PHP binary from a built-in server command, if present."""
    parts = _php_command_parts(command)
    if parts is None:
        return None
    return parts[0]


def extract_php_options_from_command(command: str) -> str:
    """Extract additional PHP CLI options placed before ``-S``."""
    parts = _php_command_parts(command)
    if parts is None:
        return ""

    server_index = parts.index("-S")
    option_parts = parts[1:server_index]
    if not option_parts:
        return ""

    return " ".join(shlex.quote(part) if " " in part else part for part in option_parts)


def split_known_php_ini_options(
    php_options: str,
    known_keys: List[str],
) -> Tuple[dict[str, str], str]:
    """
    Split known ``-d key=value`` options from the remaining free-form options.

    :param php_options: Full additional PHP options string
    :param known_keys: INI keys that should be extracted into dedicated fields
    :return: Tuple of (extracted key/value map, remaining options string)
    """
    extracted: dict[str, str] = {}
    remaining: List[str] = []
    tokens = _split_php_command(f"php {php_options}") or ["php"]
    option_tokens = tokens[1:]
    known_key_set = set(known_keys)

    index = 0
    while index < len(option_tokens):
        token = option_tokens[index]
        ini_argument = ""
        consumed = 1
        if token == "-d" and index + 1 < len(option_tokens):
            ini_argument = option_tokens[index + 1]
            consumed = 2
        elif token.startswith("-d") and len(token) > 2:
            ini_argument = token[2:]

        if ini_argument and "=" in ini_argument:
            key, value = ini_argument.split("=", 1)
            if key in known_key_set and key not in extracted:
                extracted[key] = value
                index += consumed
                continue

        remaining.append(token)
        index += 1

    remaining_options = " ".join(shlex.quote(part) if " " in part else part for part in remaining)
    return extracted, remaining_options


def build_php_ini_options(
    ini_values: dict[str, str],
    extra_options: str = "",
) -> str:
    """
    Build a combined PHP options string from dedicated INI fields and extras.

    :param ini_values: Mapping of PHP INI keys to values (without ``-d`` prefix)
    :param extra_options: Optional additional free-form PHP options
    :return: Combined options string used before ``-S``
    """
    option_parts: List[str] = []
    for key in sorted(ini_values.keys()):
        value = ini_values[key].strip()
        if not value:
            continue
        option_parts.extend(["-d", f"{key}={value}"])

    extra = extra_options.strip()
    if extra:
        parsed_extra = _split_php_command(f"php {extra}") or ["php"]
        option_parts.extend(parsed_extra[1:])

    return " ".join(shlex.quote(part) if " " in part else part for part in option_parts)


def extract_docroot_from_command(command: str) -> str:
    """Extract the document root from a PHP built-in server command."""
    parts = _php_command_parts(command)
    if parts is None:
        return DEFAULT_DOCROOT

    try:
        docroot = parts[parts.index("-t") + 1]
    except (ValueError, IndexError):
        return DEFAULT_DOCROOT

    if docroot in {".", "./"}:
        return WORKING_DIRECTORY_DOCROOT
    if docroot == WORKING_DIRECTORY_DOCROOT:
        return WORKING_DIRECTORY_DOCROOT
    return docroot


def extract_router_from_command(command: str) -> str:
    """Extract the optional router script from a PHP built-in server command."""
    parts = _php_command_parts(command)
    if parts is None:
        return ""

    try:
        docroot_index = parts.index("-t")
    except ValueError:
        return ""

    router_index = docroot_index + 2
    if router_index >= len(parts):
        return ""
    return parts[router_index]


def replace_php_binary_in_command(command: str, binary: str) -> str:
    """Replace the PHP binary at the start of a built-in server command."""
    parts = _php_command_parts(command)
    if parts is not None:
        parts[0] = binary
        return " ".join(shlex.quote(part) if " " in part else part for part in parts)
    return build_php_builtin_command(
        binary,
        extract_docroot_from_command(command),
        extract_router_from_command(command),
        extract_php_options_from_command(command),
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

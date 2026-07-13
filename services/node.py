"""Detect installed Node.js binaries and build Node.js start commands."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

NODE_BIN_DIRS = (Path("/usr/bin"), Path("/usr/local/bin"))
NODE_VERSION_PATTERN = re.compile(r"^node(\d+)?$")
NODE_NPM_PATTERN = re.compile(r"^npm run (?P<script>\S+)(?: (?P<args>.*))?$")
NODE_NPX_PATTERN = re.compile(r"^npx (?P<args>.+)$")
NODE_DIRECT_PATTERN = re.compile(r"^node (?P<script>.+)$")

NODE_MODES = {
    "npm run": "npm",
    "npx": "npx",
    "node": "node",
}


def _node_version_sort_key(label: str) -> Tuple[int, ...]:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", label)
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _read_node_version(binary: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def detect_node_versions() -> List[Tuple[str, str]]:
    """
    Detect installed Node.js binaries on the system.

    :return: List of (label, binary_path) tuples sorted by version descending
    """
    found: dict[str, str] = {}

    for bin_dir in NODE_BIN_DIRS:
        if not bin_dir.is_dir():
            continue
        for candidate in sorted(bin_dir.glob("node*")):
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            name = candidate.name
            binary = str(candidate.resolve())
            if name == "node":
                version = _read_node_version(candidate) or "default"
                label = f"node ({version})"
            elif NODE_VERSION_PATTERN.match(name):
                label = name
            else:
                continue
            if binary not in found.values():
                found[label] = binary

    default_node = shutil.which("node")
    if default_node and default_node not in found.values():
        version = _read_node_version(Path(default_node)) or "default"
        found.setdefault(f"node ({version})", default_node)

    return sorted(found.items(), key=lambda item: _node_version_sort_key(item[0]), reverse=True)


def default_node_binary(versions: Optional[List[Tuple[str, str]]] = None) -> str:
    """
    Return the preferred Node.js binary path.

    :param versions: Optional pre-detected version list
    :return: Path to a Node.js binary
    """
    version_list = versions if versions is not None else detect_node_versions()
    if version_list:
        return version_list[0][1]

    default_node = shutil.which("node")
    if default_node:
        return default_node
    return "/usr/bin/node"


def build_node_command(mode: str, target: str) -> str:
    """
    Build a stored Node.js start command for the selected run mode.

    :param mode: One of ``npm``, ``npx``, or ``node``
    :param target: npm script name, npx arguments, or node script path
    :return: Shell command with optional ``{port}`` placeholder
    """
    target = target.strip()
    if mode == "npm":
        return f"npm run {target}".strip()
    if mode == "npx":
        return f"npx {target}".strip()
    return f"node {target}".strip()


def is_node_command(command: str) -> bool:
    """
    Return whether the given command looks like a managed Node.js command.

    :param command: Stored start command
    :return: True for npm, npx, or node launch commands
    """
    command = command.strip()
    return (
        NODE_NPM_PATTERN.match(command) is not None
        or NODE_NPX_PATTERN.match(command) is not None
        or NODE_DIRECT_PATTERN.match(command) is not None
    )


def extract_node_mode(command: str) -> str:
    """
    Extract the Node.js run mode from a stored command.

    :param command: Stored start command
    :return: Mode key used by ``NODE_MODES`` values
    """
    command = command.strip()
    if NODE_NPM_PATTERN.match(command):
        return "npm"
    if NODE_NPX_PATTERN.match(command):
        return "npx"
    return "node"


def extract_node_mode_label(command: str) -> str:
    """
    Return the UI label for the Node.js run mode of a stored command.

    :param command: Stored start command
    :return: Human-readable mode label
    """
    mode = extract_node_mode(command)
    for label, key in NODE_MODES.items():
        if key == mode:
            return label
    return "npm run"


def extract_node_target(command: str) -> str:
    """
    Extract the npm script, npx arguments, or node script from a command.

    :param command: Stored start command
    :return: Mode-specific command target
    """
    command = command.strip()
    npm_match = NODE_NPM_PATTERN.match(command)
    if npm_match:
        script = npm_match.group("script")
        args = (npm_match.group("args") or "").strip()
        return f"{script} {args}".strip()

    npx_match = NODE_NPX_PATTERN.match(command)
    if npx_match:
        return npx_match.group("args").strip()

    node_match = NODE_DIRECT_PATTERN.match(command)
    if node_match:
        return node_match.group("script").strip()

    return ""


def default_node_env(use_port_env: bool) -> dict[str, str]:
    """
    Build default environment variables for a Node.js server.

    :param use_port_env: Whether to inject ``PORT={port}`` for runtime substitution
    :return: Environment variable mapping
    """
    if not use_port_env:
        return {}
    return {"PORT": "{port}"}

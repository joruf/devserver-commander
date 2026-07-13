"""Download and manage optional development tool binaries."""

import io
import os
import platform
import shlex
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from paths import TOOLS_DIR

MAILHOG_VERSION = "v1.0.1"
MAILPIT_VERSION = "v1.30.2"


@dataclass(frozen=True)
class DevTool:
    """Metadata for a downloadable development tool."""

    tool_id: str
    display_name: str
    binary_name: str
    default_port: int


DEV_TOOLS: Dict[str, DevTool] = {
    "mailhog": DevTool(
        tool_id="mailhog",
        display_name="MailHog",
        binary_name="mailhog",
        default_port=8025,
    ),
    "mailpit": DevTool(
        tool_id="mailpit",
        display_name="Mailpit",
        binary_name="mailpit",
        default_port=8025,
    ),
}

PRESET_DEV_TOOLS = {
    "MailHog": "mailhog",
    "Mailpit": "mailpit",
}


def _linux_arch() -> str:
    """
    Map the current machine architecture to release asset names.

    :return: Architecture key such as ``amd64`` or ``arm64``
    """
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    if machine.startswith("arm"):
        return "arm"
    return machine


def dev_tool_binary_path(tool_id: str) -> Path:
    """
    Return the install location for a development tool binary.

    :param tool_id: Tool identifier
    :return: Absolute path where the binary should be stored
    """
    tool = DEV_TOOLS[tool_id]
    return TOOLS_DIR / tool.binary_name


def default_command_for_tool(tool_id: str) -> str:
    """
    Return the stored start command for a managed development tool.

    :param tool_id: Tool identifier
    :return: Absolute command path
    """
    return str(dev_tool_binary_path(tool_id))


def is_dev_tool_installed(tool_id: str) -> bool:
    """
    Check whether a development tool binary exists and is executable.

    :param tool_id: Tool identifier
    :return: True when the tool is installed
    """
    path = dev_tool_binary_path(tool_id)
    return path.is_file() and os.access(path, os.X_OK)


def dev_tool_status_text(tool_id: str) -> str:
    """
    Return a short install status label for the UI.

    :param tool_id: Tool identifier
    :return: Human-readable status text
    """
    tool = DEV_TOOLS[tool_id]
    if is_dev_tool_installed(tool_id):
        return f"{tool.display_name} is installed."
    return f"{tool.display_name} is not installed."


def dev_tool_id_for_preset(label: str) -> Optional[str]:
    """
    Resolve a template label to a managed development tool id.

    :param label: Template label from the project dialog
    :return: Tool id or None
    """
    return PRESET_DEV_TOOLS.get(label)


def identify_dev_tool_from_command(command: str) -> Optional[str]:
    """
    Detect whether a stored command refers to a managed development tool.

    :param command: Stored start command
    :return: Tool id or None
    """
    command = command.strip()
    if not command:
        return None

    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if not parts:
        return None

    executable = Path(parts[0]).expanduser()
    resolved = executable.resolve() if executable.exists() else executable
    name = resolved.name.lower()

    for tool_id, tool in DEV_TOOLS.items():
        if name == tool.binary_name:
            return tool_id
        if resolved == dev_tool_binary_path(tool_id):
            return tool_id

    found = shutil.which(parts[0])
    if found:
        found_name = Path(found).name.lower()
        for tool_id, tool in DEV_TOOLS.items():
            if found_name == tool.binary_name:
                return tool_id

    return None


def _mailhog_download_url(arch: str) -> Optional[str]:
    if arch == "amd64":
        asset = "MailHog_linux_amd64"
    elif arch == "arm":
        asset = "MailHog_linux_armv6"
    else:
        return None

    return f"https://github.com/mailhog/MailHog/releases/download/{MAILHOG_VERSION}/{asset}"


def _mailpit_download_url(arch: str) -> Optional[str]:
    asset_map = {
        "amd64": "mailpit-linux-amd64.tar.gz",
        "arm64": "mailpit-linux-arm64.tar.gz",
        "arm": "mailpit-linux-arm.tar.gz",
        "386": "mailpit-linux-386.tar.gz",
    }
    asset = asset_map.get(arch)
    if asset is None:
        return None

    return f"https://github.com/axllent/mailpit/releases/download/{MAILPIT_VERSION}/{asset}"


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DevServer-Commander"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def _write_executable(path: Path, data: bytes) -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755)


def _install_mailhog(arch: str) -> Tuple[bool, str]:
    url = _mailhog_download_url(arch)
    if url is None:
        return (
            False,
            "MailHog does not provide a binary for this CPU architecture.\n"
            "Use Mailpit instead.",
        )

    destination = dev_tool_binary_path("mailhog")
    try:
        data = _download_bytes(url)
    except (OSError, urllib.error.URLError) as exc:
        return False, f"Could not download MailHog:\n{exc}"

    try:
        _write_executable(destination, data)
    except OSError as exc:
        return False, f"Could not install MailHog:\n{exc}"

    return True, f"MailHog installed to:\n{destination}"


def _install_mailpit(arch: str) -> Tuple[bool, str]:
    url = _mailpit_download_url(arch)
    if url is None:
        return False, f"Mailpit does not provide a binary for architecture '{arch}'."

    destination = dev_tool_binary_path("mailpit")
    try:
        archive_data = _download_bytes(url)
    except (OSError, urllib.error.URLError) as exc:
        return False, f"Could not download Mailpit:\n{exc}"

    try:
        with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as archive:
            member = archive.getmember("mailpit")
            extracted = archive.extractfile(member)
            if extracted is None:
                return False, "Mailpit archive did not contain an executable."
            _write_executable(destination, extracted.read())
    except (OSError, tarfile.TarError, KeyError) as exc:
        return False, f"Could not install Mailpit:\n{exc}"

    return True, f"Mailpit installed to:\n{destination}"


def install_dev_tool(tool_id: str) -> Tuple[bool, str]:
    """
    Download and install a managed development tool for the current system.

    :param tool_id: Tool identifier
    :return: Tuple of success flag and user-facing message
    """
    if tool_id not in DEV_TOOLS:
        return False, f"Unknown development tool: {tool_id}"

    if platform.system().lower() != "linux":
        return False, "Automatic installation is only supported on Linux."

    if is_dev_tool_installed(tool_id):
        path = dev_tool_binary_path(tool_id)
        return True, f"{DEV_TOOLS[tool_id].display_name} is already installed:\n{path}"

    arch = _linux_arch()
    if tool_id == "mailhog":
        return _install_mailhog(arch)
    if tool_id == "mailpit":
        return _install_mailpit(arch)

    return False, f"Installation is not implemented for '{tool_id}'."

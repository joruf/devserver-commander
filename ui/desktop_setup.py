"""Desktop entry helpers: desktop shortcut creation and login autostart."""

import shlex
import stat
from pathlib import Path
from typing import Sequence

from tkinter import messagebox

from paths import (
    AUTOSTART_FILE,
    DESKTOP_FILENAME,
    DESKTOP_TEMPLATE,
    ICON_FILE,
    INIT_FILE,
    MAIN_SCRIPT,
)
from services.cli_args import TRAY_ARGUMENT

AUTOSTART_KEYS = ("X-GNOME-Autostart-enabled=", "Hidden=")


def mark_initialization_done() -> None:
    """Create the marker file so the first-run prompt is not shown again."""
    try:
        INIT_FILE.touch()
    except OSError:
        pass


def user_desktop_dir() -> Path:
    """Return the user's desktop directory."""
    config = Path.home() / ".config" / "user-dirs.dirs"
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("XDG_DESKTOP_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
                if value.startswith("$HOME/"):
                    return Path.home() / value[len("$HOME/") :]
                if value == "$HOME":
                    return Path.home()
                return Path(value).expanduser()

    for name in ("Desktop", "Schreibtisch"):
        desktop = Path.home() / name
        if desktop.is_dir():
            return desktop

    return Path.home() / "Desktop"


def build_exec_line(exec_args: Sequence[str] = ()) -> str:
    """
    Build the ``Exec=`` line for a desktop entry.

    :param exec_args: Extra command-line arguments appended to the launch command
    :return: Complete Exec line without a trailing newline
    """
    command = ["python3", str(MAIN_SCRIPT), *exec_args]
    return "Exec=" + " ".join(shlex.quote(part) for part in command)


def build_desktop_entry_content(exec_args: Sequence[str] = ()) -> str:
    """
    Build the .desktop file contents from the template with the correct Exec path.

    :param exec_args: Extra command-line arguments appended to the launch command
    :return: Contents of a complete .desktop file
    """
    exec_line = f"{build_exec_line(exec_args)}\n"
    icon_line = f"Icon={ICON_FILE}\n" if ICON_FILE.is_file() else "Icon=utilities-terminal\n"
    if not DESKTOP_TEMPLATE.is_file():
        return (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=DevServer Commander\n"
            "Comment=Start, stop and restart local development servers\n"
            f"{icon_line.rstrip()}\n"
            f"{exec_line.rstrip()}\n"
            "Terminal=false\n"
            "Categories=Utility;Development;\n"
            "StartupNotify=false\n"
        )

    lines: list[str] = []
    for line in DESKTOP_TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.startswith("Exec="):
            lines.append(exec_line.rstrip())
        elif line.startswith("Icon="):
            lines.append(icon_line.rstrip())
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def install_desktop_shortcut() -> tuple[bool, Path | None]:
    """Install the desktop shortcut on the user's desktop."""
    try:
        desktop_dir = user_desktop_dir()
        desktop_dir.mkdir(parents=True, exist_ok=True)
        shortcut_path = desktop_dir / DESKTOP_FILENAME
        shortcut_path.write_text(build_desktop_entry_content(), encoding="utf-8")
        shortcut_path.chmod(
            shortcut_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return True, shortcut_path
    except OSError:
        return False, None


def build_autostart_entry_content() -> str:
    """
    Build the login autostart entry, which launches the app into the system tray only.

    :return: Contents of the autostart .desktop file
    """
    lines = [
        line
        for line in build_desktop_entry_content(exec_args=(TRAY_ARGUMENT,)).splitlines()
        if not line.startswith(AUTOSTART_KEYS)
    ]
    lines.append("X-GNOME-Autostart-enabled=true")
    lines.append("Hidden=false")
    return "\n".join(lines) + "\n"


def is_login_autostart_enabled() -> bool:
    """
    Check whether the application starts automatically on login.

    :return: True when the autostart entry exists
    """
    return AUTOSTART_FILE.is_file()


def enable_login_autostart() -> bool:
    """
    Install the autostart entry so the app starts into the tray on login.

    :return: True when the entry was written
    """
    try:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(build_autostart_entry_content(), encoding="utf-8")
        AUTOSTART_FILE.chmod(
            AUTOSTART_FILE.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return True
    except OSError:
        return False


def disable_login_autostart() -> bool:
    """
    Remove the autostart entry so the app no longer starts on login.

    :return: True when no autostart entry remains
    """
    try:
        AUTOSTART_FILE.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def set_login_autostart(enabled: bool) -> bool:
    """
    Enable or disable the login autostart entry.

    :param enabled: True to install the entry, False to remove it
    :return: True when the requested state was applied
    """
    return enable_login_autostart() if enabled else disable_login_autostart()


def maybe_prompt_desktop_setup(parent=None) -> None:
    """Ask once on first run whether to create a desktop shortcut."""
    if INIT_FILE.exists():
        return

    answer = messagebox.askyesno(
        "Desktop Shortcut",
        "Would you like to create a desktop shortcut for DevServer Commander?",
        parent=parent,
    )

    if answer:
        success, _ = install_desktop_shortcut()
        if not success:
            messagebox.showerror(
                "Desktop Shortcut",
                "Could not create the desktop shortcut.",
                parent=parent,
            )

    mark_initialization_done()

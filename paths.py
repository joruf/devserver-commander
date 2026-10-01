"""Shared filesystem paths for DevServer Commander."""

import os
import platform
import shutil
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

#: ``True`` inside the single-file executable that ``build-exe.py`` produces.
IS_FROZEN = bool(getattr(sys, "frozen", False))


def _project_root() -> Path:
    """
    Return the directory that holds ``run.py`` and the ``resources`` folder.

    The executable unpacks itself into a temporary directory on every start; the
    resources travel there as data under the same relative layout, so the icon and
    the desktop template are found exactly where a checkout has them.

    :return: The project root
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", "."))
    return Path(__file__).resolve().parent


PROJECT_ROOT = _project_root()
RESOURCES_DIR = PROJECT_ROOT / "resources"

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", STATE_DIR))
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
LOCK_DIR = RUNTIME_DIR / "devserver-commander"
TOOLS_DIR = Path.home() / ".local" / "share" / "devserver-commander" / "bin"
AUTOSTART_DIR = CONFIG_HOME / "autostart"

# User data lives in the per-user config directory, next to settings.json: the
# executable's own files are deleted when it exits, and a checkout should not
# carry anyone's server list.
USER_CONFIG_DIR = CONFIG_HOME / "devserver-commander"
# Launcher icons must outlive the executable's unpacked files.
USER_DATA_DIR = Path.home() / ".local" / "share" / "devserver-commander"

CONFIG_FILE = USER_CONFIG_DIR / "servers.json"
INIT_FILE = USER_CONFIG_DIR / ".initialized"
MAIN_SCRIPT = PROJECT_ROOT / "run.py"
DESKTOP_TEMPLATE = RESOURCES_DIR / "devserver-commander.desktop"
DESKTOP_FILENAME = "DevServer Commander.desktop"
AUTOSTART_FILENAME = "devserver-commander.desktop"
AUTOSTART_FILE = AUTOSTART_DIR / AUTOSTART_FILENAME
ICON_FILE = RESOURCES_DIR / "devserver-commander.png"

# Where older checkouts kept the user data: in the project root itself.
LEGACY_CONFIG_FILE = PROJECT_ROOT / "servers.json"
LEGACY_INIT_FILE = PROJECT_ROOT / ".initialized"


def migrate_legacy_user_data(
    moves: "tuple[tuple[Path, Path], ...]" = (
        (LEGACY_CONFIG_FILE, CONFIG_FILE),
        (LEGACY_INIT_FILE, INIT_FILE),
    ),
) -> None:
    """
    Copy user data from the project root to the per-user config directory, once.

    Only when the new file does not exist yet and the old one does. The old file
    stays where it is, so going back to an older checkout loses nothing. The
    executable has no project root of its own to migrate from.

    :param moves: Pairs of (old location, new location)
    """
    if IS_FROZEN:
        return
    for old, new in moves:
        if new.exists() or not old.is_file():
            continue
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(old), str(new))
        except OSError:
            continue


def executable() -> Path:
    """
    Return the single-file executable this process was started from.

    Only meaningful when :data:`IS_FROZEN` is set; otherwise it is the Python
    interpreter.

    :return: Resolved path of the running program
    """
    return Path(sys.executable).resolve()


def executable_name(version: str = "", build: int = 0) -> str:
    """
    Return the file name of the executable for this platform and version.

    ``build-exe.py`` writes the executable under this name. The version is part of
    it so a downloaded file says which one it is.

    :param version: ``major.minor.patch``; defaults to this program's
    :param build: The build number; defaults to this program's
    :return: e.g. ``devserver-commander-linux-x86_64-0.8.0-build24``
    """
    if not version:
        import version as program_version

        found = program_version.current()
        version, build = found.name, int(found.build or 0)
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    system = "windows" if IS_WINDOWS else ("macos" if IS_MACOS else "linux")
    return "devserver-commander-{0}-{1}-{2}-build{3}{4}".format(
        system, machine, version, build, ".exe" if IS_WINDOWS else "")


def child_environment(env: "dict | None" = None) -> dict:
    """Return the environment a child process should get.

    The executable runs with ``LD_LIBRARY_PATH`` - and, through PyInstaller's
    GTK hooks, ``GI_TYPELIB_PATH``, ``GTK_PATH`` and friends - pointing into its
    unpacked files.  Inherited, they make PHP, Node.js, systemctl or the file
    manager load the program's libraries instead of their own, which ends
    anywhere between odd warnings and crashes.  Every entry that points into the
    unpacked files is removed; ``LD_LIBRARY_PATH`` gets the value it had before
    the program started.

    :param env: The environment to clean; defaults to this process's.
    :return: A new dict; a plain copy outside the executable.
    """
    source = os.environ if env is None else env
    bundle = getattr(sys, "_MEIPASS", "")
    if not IS_FROZEN or not bundle:
        return dict(source)
    clean = {}
    for key, value in source.items():
        if key.startswith("_PYI_") or key == "LD_LIBRARY_PATH_ORIG":
            continue
        if bundle in value:
            kept = [part for part in value.split(os.pathsep) if part and bundle not in part]
            if not kept:
                continue
            value = os.pathsep.join(kept)
        clean[key] = value
    original = source.get("LD_LIBRARY_PATH_ORIG")
    if original:
        clean["LD_LIBRARY_PATH"] = original
    return clean


def use_system_environment_for_children() -> None:
    """Start every child process with :func:`child_environment`.

    One place instead of every ``subprocess`` call: the program starts dozens
    of tools, and a single forgotten ``env=`` would bring the problem back.
    Does nothing outside the executable.

    :return: None
    """
    import subprocess

    if not IS_FROZEN or getattr(subprocess.Popen, "_devserver_commander_clean_env", False):
        return

    class _SystemPopen(subprocess.Popen):  # type: ignore[misc, valid-type]
        """``Popen`` that never hands the bundled libraries to a child."""

        _devserver_commander_clean_env = True

        def __init__(self, *args, **kwargs) -> None:
            kwargs["env"] = child_environment(kwargs.get("env"))
            super().__init__(*args, **kwargs)

    subprocess.Popen = _SystemPopen  # type: ignore[misc]

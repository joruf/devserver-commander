"""Shared filesystem paths for DevServer Commander."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RESOURCES_DIR = PROJECT_ROOT / "resources"

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", STATE_DIR))
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
LOCK_DIR = RUNTIME_DIR / "devserver-commander"
TOOLS_DIR = Path.home() / ".local" / "share" / "devserver-commander" / "bin"
AUTOSTART_DIR = CONFIG_HOME / "autostart"

CONFIG_FILE = PROJECT_ROOT / "servers.json"
INIT_FILE = PROJECT_ROOT / ".initialized"
MAIN_SCRIPT = PROJECT_ROOT / "run.py"
DESKTOP_TEMPLATE = RESOURCES_DIR / "devserver-commander.desktop"
DESKTOP_FILENAME = "DevServer Commander.desktop"
AUTOSTART_FILENAME = "devserver-commander.desktop"
AUTOSTART_FILE = AUTOSTART_DIR / AUTOSTART_FILENAME
ICON_FILE = RESOURCES_DIR / "devserver-commander.png"

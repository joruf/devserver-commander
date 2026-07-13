"""Shared filesystem paths for DevServer Commander."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RESOURCES_DIR = PROJECT_ROOT / "resources"

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", STATE_DIR))
LOCK_DIR = RUNTIME_DIR / "devserver-commander"
TOOLS_DIR = Path.home() / ".local" / "share" / "devserver-commander" / "bin"

CONFIG_FILE = PROJECT_ROOT / "servers.json"
INIT_FILE = PROJECT_ROOT / ".initialized"
MAIN_SCRIPT = PROJECT_ROOT / "devserver_commander.py"
DESKTOP_TEMPLATE = RESOURCES_DIR / "devserver-commander.desktop"
DESKTOP_FILENAME = "DevServer Commander.desktop"
ICON_FILE = RESOURCES_DIR / "devserver-commander.png"

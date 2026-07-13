#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Installer / bootstrap helper for DevServer Commander.

This script checks for all components that are required to run the application
and performs local setup steps that do not require elevated privileges.
"""

import stat
import sys
from pathlib import Path
from shutil import which
from typing import Tuple

from paths import MAIN_SCRIPT


def _check_python() -> Tuple[bool, str]:
    major, minor = sys.version_info[:2]
    if major > 3 or (major == 3 and minor >= 10):
        return True, f"Python version OK: {major}.{minor}"
    return False, f"Python 3.10+ required, found {major}.{minor}"


def _check_tkinter() -> Tuple[bool, str]:
    try:
        import tkinter  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        return False, f"tkinter not available: {exc}"
    return True, "tkinter available"


def _check_fuser() -> Tuple[bool, str]:
    if which("fuser") is not None:
        return True, "fuser found on PATH"
    return (
        False,
        "fuser not found on PATH (install the 'psmisc' package, e.g. 'sudo apt install psmisc')",
    )


def _ensure_executable(script: Path) -> Tuple[bool, str]:
    if not script.is_file():
        return False, f"Main script not found: {script}"

    try:
        mode = script.stat().st_mode
        if mode & stat.S_IXUSR:
            return True, f"Executable bit already set on {script.name}"
        script.chmod(mode | stat.S_IXUSR)
        return True, f"Set executable bit on {script.name}"
    except OSError as exc:
        return False, f"Could not set executable bit on {script}: {exc}"


def _check_gtk3() -> Tuple[bool, str]:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        return (
            False,
            f"GTK3 not available (optional, needed for system tray): {exc}",
        )
    return True, "GTK3 available (system tray supported)"


def main() -> int:
    print("DevServer Commander installer\n")

    checks = [
        ("Python version", _check_python),
        ("tkinter", _check_tkinter),
        ("fuser (psmisc)", _check_fuser),
        ("GTK3 (optional tray)", _check_gtk3),
    ]

    all_ok = True
    for label, func in checks:
        ok, message = func()
        optional = label.startswith("GTK3")
        if optional and not ok:
            status = "OPTIONAL"
        else:
            status = "OK" if ok else "MISSING"
            if not ok:
                all_ok = False
        print(f"[{status:7}] {label}: {message}")

    ok, msg = _ensure_executable(MAIN_SCRIPT)
    status = "OK" if ok else "FAILED"
    print(f"[{status:7}] Executable flag: {msg}")
    if not ok:
        all_ok = False

    print("\nNext steps:")
    print(f"- To start the app, run: ./{MAIN_SCRIPT.name}")
    print(
        "- If any components are marked as MISSING, install them with your package "
        "manager and re-run this installer."
    )

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

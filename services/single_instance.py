"""Ensure only one DevServer Commander instance runs at a time."""

import fcntl
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import IO, Optional

from paths import LOCK_DIR

LOCK_FILE = LOCK_DIR / "instance.lock"


class SingleInstanceGuard:
    """Acquire and hold an exclusive lock for the lifetime of the application."""

    def __init__(self) -> None:
        self._lock_handle: Optional[IO[str]] = None

    def acquire(self) -> bool:
        """
        Try to acquire the single-instance lock.

        :return: True when this process is the only running instance
        """
        LOCK_DIR.mkdir(parents=True, exist_ok=True)

        handle = open(LOCK_FILE, "w", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._lock_handle = handle
        return True

    def release(self) -> None:
        """Release the single-instance lock."""
        if self._lock_handle is None:
            return

        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

        try:
            self._lock_handle.close()
        except OSError:
            pass

        self._lock_handle = None


from services.instance_ipc import request_show_existing_instance


def show_already_running_message(focused_existing: bool = False) -> None:
    """Inform the user that another instance is already active."""
    from ui.window_icon import apply_window_icon

    root = tk.Tk()
    root.withdraw()
    apply_window_icon(root)
    if focused_existing:
        message = (
            "DevServer Commander is already running.\n\n"
            "The existing window has been brought to the front."
        )
        dialog = messagebox.showinfo
        title = "Already Running"
    else:
        title = "Already Running"
        message = (
            "DevServer Commander is already running.\n\n"
            "Only one instance of the application can be open at a time."
        )
        dialog = messagebox.showerror

    dialog(title, message, parent=root)
    root.destroy()


def enforce_single_instance() -> tuple[bool, SingleInstanceGuard]:
    """
    Block startup when another instance is already running.

    :return: Tuple of (may_continue, lock_guard)
    """
    guard = SingleInstanceGuard()
    if guard.acquire():
        return True, guard

    focused_existing = request_show_existing_instance()
    show_already_running_message(focused_existing=focused_existing)
    return False, guard


def exit_if_already_running() -> None:
    """
    Exit the process when another instance is already running.

    :return: None; terminates the process with exit code 1 when blocked
    """
    may_continue, _guard = enforce_single_instance()
    if not may_continue:
        raise SystemExit(1)

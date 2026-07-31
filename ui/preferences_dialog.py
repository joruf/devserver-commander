"""Preferences dialog for application-wide settings."""

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from config.app_settings import (
    CRASH_RESTART_DELAYS_SECONDS,
    MAX_STATS_REFRESH_INTERVAL_SECONDS,
    MIN_STATS_REFRESH_INTERVAL_SECONDS,
    AppSettings,
)
from services.notifications import notifications_available
from ui.window_icon import apply_window_icon

RESTART_DELAYS_LABEL = ", ".join(f"{delay}s" for delay in CRASH_RESTART_DELAYS_SECONDS)


class PreferencesDialog(tk.Toplevel):
    """Edit persisted application preferences."""

    def __init__(self, parent: tk.Misc, settings: AppSettings, login_autostart: bool = False) -> None:
        super().__init__(parent)
        self.result: Optional[AppSettings] = None
        self.login_autostart_result: Optional[bool] = None
        self.title("Preferences")
        self.transient(parent)
        self.resizable(False, False)
        apply_window_icon(self)

        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="CPU/memory refresh interval (seconds):").grid(
            row=0,
            column=0,
            sticky="w",
            **pad,
        )
        self.interval_var = tk.StringVar(value=str(settings.stats_refresh_interval_seconds))
        ttk.Spinbox(
            frame,
            from_=MIN_STATS_REFRESH_INTERVAL_SECONDS,
            to=MAX_STATS_REFRESH_INTERVAL_SECONDS,
            textvariable=self.interval_var,
            width=8,
        ).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(
            frame,
            text=f"Allowed range: {MIN_STATS_REFRESH_INTERVAL_SECONDS}-"
            f"{MAX_STATS_REFRESH_INTERVAL_SECONDS} seconds.",
            foreground="gray",
        ).grid(row=1, column=0, columnspan=2, sticky="w", **pad)

        ttk.Separator(frame, orient="horizontal").grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=8,
            pady=(10, 6),
        )

        self.notify_on_crash_var = tk.BooleanVar(master=self, value=settings.notify_on_server_crash)
        ttk.Checkbutton(
            frame,
            text="Notify when a server stops unexpectedly",
            variable=self.notify_on_crash_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        self.restart_crashed_var = tk.BooleanVar(master=self, value=settings.restart_crashed_servers)
        ttk.Checkbutton(
            frame,
            text="Restart crashed servers automatically",
            variable=self.restart_crashed_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(
            frame,
            text=f"Restart delays: {RESTART_DELAYS_LABEL}, then the server is left stopped."
            + ("" if notifications_available() else "\nDesktop notifications need the 'notify-send' command."),
            foreground="gray",
        ).grid(row=5, column=0, columnspan=2, sticky="w", **pad)

        ttk.Separator(frame, orient="horizontal").grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=8,
            pady=(10, 6),
        )

        self.login_autostart_var = tk.BooleanVar(master=self, value=login_autostart)
        ttk.Checkbutton(
            frame,
            text="Start DevServer Commander on login",
            variable=self.login_autostart_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(
            frame,
            text="On login the application starts in the system tray only, without opening the window.",
            foreground="gray",
        ).grid(row=8, column=0, columnspan=2, sticky="w", **pad)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=9, column=0, columnspan=2, pady=(12, 8))
        ttk.Button(button_frame, text="Save", style="Primary.TButton", command=self._on_save).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side="left", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _on_save(self) -> None:
        raw_value = self.interval_var.get().strip()
        if not raw_value.isdigit():
            messagebox.showerror(
                "Invalid Interval",
                "Please enter a whole number of seconds.",
                parent=self,
            )
            return

        interval = int(raw_value)
        if not MIN_STATS_REFRESH_INTERVAL_SECONDS <= interval <= MAX_STATS_REFRESH_INTERVAL_SECONDS:
            messagebox.showerror(
                "Invalid Interval",
                f"The interval must be between {MIN_STATS_REFRESH_INTERVAL_SECONDS} "
                f"and {MAX_STATS_REFRESH_INTERVAL_SECONDS} seconds.",
                parent=self,
            )
            return

        self.result = AppSettings(
            stats_refresh_interval_seconds=interval,
            notify_on_server_crash=bool(self.notify_on_crash_var.get()),
            restart_crashed_servers=bool(self.restart_crashed_var.get()),
        )
        self.login_autostart_result = bool(self.login_autostart_var.get())
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.login_autostart_result = None
        self.destroy()

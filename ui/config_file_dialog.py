"""Dialog for viewing and editing the raw server configuration file."""

import json
import tkinter as tk
from tkinter import messagebox, ttk

from paths import CONFIG_FILE
from ui.window_icon import apply_window_icon


class ConfigFileDialog(tk.Toplevel):
    """Edit servers.json directly as text."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.saved = False
        self.title(f"Edit Configuration File — {CONFIG_FILE.name}")
        self.transient(parent)
        self.geometry("720x600")
        apply_window_icon(self)

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        ttk.Label(frame, text=str(CONFIG_FILE), foreground="gray").pack(anchor="w", pady=(0, 6))

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        self.text = tk.Text(text_frame, wrap="none", undo=True)
        y_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        x_scroll = ttk.Scrollbar(text_frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        try:
            content = CONFIG_FILE.read_text(encoding="utf-8")
        except OSError as exc:
            content = ""
            messagebox.showerror(
                "Edit Configuration File",
                f"Could not read the file:\n{exc}",
                parent=self,
            )
        self.text.insert("1.0", content)

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(8, 0))
        ttk.Button(
            button_frame, text="Save", style="Primary.TButton", command=self._on_save
        ).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side="left", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _on_save(self) -> None:
        content = self.text.get("1.0", "end-1c")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            messagebox.showerror(
                "Invalid JSON",
                f"The configuration is not valid JSON:\n{exc}",
                parent=self,
            )
            return

        if not isinstance(parsed, dict):
            messagebox.showerror(
                "Invalid JSON",
                "The configuration must be a JSON object with 'servers' and 'services' entries.",
                parent=self,
            )
            return

        try:
            CONFIG_FILE.write_text(content, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(
                "Edit Configuration File",
                f"Could not save the file:\n{exc}",
                parent=self,
            )
            return

        self.saved = True
        self.destroy()

    def _on_cancel(self) -> None:
        self.destroy()

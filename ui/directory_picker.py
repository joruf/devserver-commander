"""Directory picker with optional hidden folder visibility."""

import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import List, Optional

from ui.window_icon import apply_window_icon


class DirectoryPickerDialog(tk.Toplevel):
    """Modal directory chooser with a show-hidden toggle."""

    def __init__(
        self,
        parent: tk.Misc,
        initialdir: str = "",
        show_hidden: bool = False,
    ) -> None:
        super().__init__(parent)
        self.result: Optional[str] = None
        self.title("Choose Directory")
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(520, 360)
        apply_window_icon(self)

        start_path = Path(initialdir).expanduser() if initialdir else Path.home()
        if not start_path.is_dir():
            start_path = Path.home()

        self._current_path = start_path.resolve()
        self.show_hidden_var = tk.BooleanVar(value=show_hidden)
        self._build_widgets()
        self._refresh_listing()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        ttk.Checkbutton(
            frame,
            text="Show hidden files/folders",
            variable=self.show_hidden_var,
            command=self._refresh_listing,
        ).pack(anchor="w", **pad)

        path_frame = ttk.Frame(frame)
        path_frame.pack(fill="x", **pad)
        ttk.Label(path_frame, text="Current path:").pack(side="left")
        self.path_var = tk.StringVar(value=str(self._current_path))
        path_entry = ttk.Entry(path_frame, textvariable=self.path_var)
        path_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        path_entry.bind("<Return>", self._on_path_entered)

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True, **pad)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(list_frame, height=14, activestyle="dotbox")
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.listbox.bind("<Double-1>", self._on_list_double_click)

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(8, 0))
        ttk.Button(button_frame, text="Up", command=self._go_up).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Select", style="Primary.TButton", command=self._on_select).pack(side="right", padx=4)
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side="right", padx=4)

    def _show_hidden(self) -> bool:
        return bool(self.show_hidden_var.get())

    def _set_current_path(self, path: Path) -> None:
        self._current_path = path.resolve()
        self.path_var.set(str(self._current_path))
        self._refresh_listing()

    def _list_entries(self) -> List[Path]:
        try:
            entries = list(self._current_path.iterdir())
        except OSError as exc:
            messagebox.showerror("Directory Error", str(exc), parent=self)
            return []

        directories = [entry for entry in entries if entry.is_dir()]
        if not self._show_hidden():
            directories = [entry for entry in directories if not entry.name.startswith(".")]

        return sorted(directories, key=lambda entry: entry.name.lower())

    def _refresh_listing(self) -> None:
        self.listbox.delete(0, tk.END)

        parent = self._current_path.parent
        if parent != self._current_path:
            self.listbox.insert(tk.END, "..")

        for directory in self._list_entries():
            self.listbox.insert(tk.END, f"{directory.name}/")

    def _on_path_entered(self, _event=None) -> None:
        entered = self.path_var.get().strip()
        path = Path(entered).expanduser()
        if not path.is_dir():
            messagebox.showerror(
                "Invalid Directory",
                f"Directory does not exist:\n{path}",
                parent=self,
            )
            self.path_var.set(str(self._current_path))
            return

        self._set_current_path(path)

    def _selected_list_name(self) -> Optional[str]:
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self.listbox.get(selection[0])

    def _on_list_double_click(self, _event=None) -> None:
        selected = self._selected_list_name()
        if selected is None:
            return

        if selected == "..":
            self._go_up()
            return

        if selected.endswith("/"):
            self._set_current_path(self._current_path / selected[:-1])

    def _go_up(self) -> None:
        parent = self._current_path.parent
        if parent == self._current_path:
            return
        self._set_current_path(parent)

    def _on_select(self) -> None:
        selected = self._selected_list_name()
        if selected and selected != ".." and selected.endswith("/"):
            self.result = str((self._current_path / selected[:-1]).resolve())
        else:
            self.result = str(self._current_path)

        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


def ask_directory(
    parent: tk.Misc,
    initialdir: str = "",
    show_hidden: bool = False,
) -> Optional[str]:
    """
    Open a directory chooser dialog.

    :param parent: Parent window for the dialog
    :param initialdir: Initial directory path
    :param show_hidden: Whether hidden folders should be listed
    :return: Selected directory path or None when cancelled
    """
    dialog = DirectoryPickerDialog(parent, initialdir=initialdir, show_hidden=show_hidden)
    parent.wait_window(dialog)
    return dialog.result

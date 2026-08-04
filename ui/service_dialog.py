"""Modal dialog for adding curated systemd services to the server list.

Only services from the catalog that are actually installed are offered. There is
no free-text unit field on purpose: this application manages the services its
projects depend on, not arbitrary systemd units.
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional

from models import SystemService
from services.service_catalog import DetectedService, detect_available_services
from ui.window_icon import apply_window_icon

COLUMN_HEADINGS = {
    "unit": "Unit",
    "port": "Port",
    "state": "State",
    "data_directory": "Data directory",
}


class AddServiceDialog(tk.Toplevel):
    """Lets the user pick installed catalog services and returns them via .result."""

    def __init__(
        self,
        parent: tk.Misc,
        existing_units: Optional[List[str]] = None,
    ) -> None:
        """
        :param parent: Parent window
        :param existing_units: Units already present in the server list
        """
        super().__init__(parent)
        self.result: Optional[List[SystemService]] = None
        self._existing_units = set(existing_units or [])
        self._detected: List[DetectedService] = []
        self._by_iid: Dict[str, DetectedService] = {}

        self.title("Add Service")
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(640, 340)
        apply_window_icon(self)

        self._build_widgets()
        self._run_detection()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        header = ttk.Frame(self)
        header.pack(side="top", fill="x", **pad)
        ttk.Label(
            header,
            text="Database and cache services installed on this machine:",
        ).pack(side="left")
        ttk.Button(header, text="Refresh", command=self._run_detection).pack(side="right")

        columns = tuple(COLUMN_HEADINGS)
        self.tree = ttk.Treeview(self, columns=columns, show="tree headings", height=10, selectmode="extended")
        self.tree.heading("#0", text="Service")
        for column_id, heading in COLUMN_HEADINGS.items():
            self.tree.heading(column_id, text=heading)
        self.tree.column("#0", width=140, stretch=False)
        self.tree.column("unit", width=160, stretch=False)
        self.tree.column("port", width=60, stretch=False)
        self.tree.column("state", width=90, stretch=False)
        self.tree.column("data_directory", width=200, stretch=True)
        self.tree.pack(side="top", fill="both", expand=True, padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)

        self.hint_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.hint_var, anchor="w", wraplength=600, foreground="#71717a").pack(
            side="top", fill="x", padx=8, pady=(0, 4)
        )

        button_frame = ttk.Frame(self)
        button_frame.pack(side="bottom", fill="x", padx=8, pady=8)
        self.btn_add = ttk.Button(
            button_frame, text="Add", style="Primary.TButton", command=self._on_add
        )
        self.btn_add.pack(side="right", padx=4)
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side="right", padx=4)

    def _run_detection(self) -> None:
        """Scan for installed catalog services and rebuild the list."""
        self._detected = detect_available_services()
        self._by_iid.clear()

        for item in self.tree.get_children():
            self.tree.delete(item)

        addable = 0
        for index, detected in enumerate(self._detected):
            already_added = detected.unit in self._existing_units
            label = detected.candidate.display_name
            if already_added:
                label = f"{label} (already in list)"
            else:
                addable += 1

            iid = f"detected-{index}"
            self._by_iid[iid] = detected
            self.tree.insert(
                "",
                "end",
                iid=iid,
                text=label,
                values=(
                    detected.unit,
                    detected.candidate.port,
                    detected.status.status_label(),
                    detected.data_directory or "not found",
                ),
                tags=() if not already_added else ("existing",),
            )

        self.tree.tag_configure("existing", foreground="#a1a1aa")

        if not self._detected:
            self.hint_var.set(
                "No supported service was found. MariaDB, MySQL, PostgreSQL and Redis "
                "are detected automatically once their systemd unit is installed."
            )
        elif addable == 0:
            self.hint_var.set("All detected services are already in the server list.")
        else:
            self.hint_var.set(
                "Starting and stopping a service asks for authorization. "
                "Its boot behavior stays under systemd's control."
            )

        self._on_select()

    def _selected_new_services(self) -> List[DetectedService]:
        """
        Return the selected entries that are not in the server list yet.

        :return: Selected, not-yet-added services
        """
        selected = []
        for iid in self.tree.selection():
            detected = self._by_iid.get(iid)
            if detected is not None and detected.unit not in self._existing_units:
                selected.append(detected)
        return selected

    def _on_select(self, _event=None) -> None:
        has_new = bool(self._selected_new_services())
        self.btn_add.configure(state="normal" if has_new else "disabled")

    def _on_double_click(self, _event=None) -> None:
        if self._selected_new_services():
            self._on_add()

    def _on_add(self) -> None:
        selected = self._selected_new_services()
        if not selected:
            return

        self.result = [detected.to_service() for detected in selected]
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

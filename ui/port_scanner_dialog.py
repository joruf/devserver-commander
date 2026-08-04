"""Dialog listing TCP ports currently listening on the machine that are not
yet saved as a project in servers.json."""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

from services.port_scan import ScannedPort, scan_listening_ports, socket_owner_for_port
from services.well_known_ports import service_name_for_port
from ui.tree_sort import TreeSorter
from ui.window_icon import apply_window_icon

COLUMN_HEADINGS = {
    "port": "Port",
    "address": "Address",
    "service": "Service",
    "process": "Process",
    "pid": "PID",
}


class PortScannerDialog(tk.Toplevel):
    """Shows listening TCP ports that are not yet saved in servers.json."""

    def __init__(
        self,
        parent: tk.Misc,
        configured_ports: Dict[int, str],
        on_take_over: Callable[[ScannedPort], None],
    ) -> None:
        super().__init__(parent)
        self._configured_ports = configured_ports
        self._on_take_over = on_take_over
        self._scanned_ports: List[ScannedPort] = []
        self._ports_by_iid: Dict[str, ScannedPort] = {}

        self.title("Port Scanner")
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(560, 380)
        apply_window_icon(self)

        self._build_widgets()
        self._run_scan()

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        toolbar = ttk.Frame(self)
        toolbar.pack(side="top", fill="x", **pad)
        ttk.Label(toolbar, text="Ports listening but not saved in servers.json:").pack(side="left")
        ttk.Button(toolbar, text="Refresh", command=self._run_scan).pack(side="right")

        columns = tuple(COLUMN_HEADINGS)
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=14)
        for column_id, heading in COLUMN_HEADINGS.items():
            self.tree.heading(column_id, text=heading)
        self.tree.column("port", width=70, anchor="w")
        self.tree.column("address", width=140, anchor="w")
        self.tree.column("service", width=210, anchor="w")
        self.tree.column("process", width=150, anchor="w")
        self.tree.column("pid", width=70, anchor="w")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_row_double_click)
        self.tree.pack(side="top", fill="both", expand=True, **pad)
        self._tree_sorter = TreeSorter(self.tree, COLUMN_HEADINGS, on_clear=self._render_rows)

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken").pack(
            side="bottom", fill="x"
        )

        button_frame = ttk.Frame(self)
        button_frame.pack(side="bottom", fill="x", **pad)
        ttk.Button(button_frame, text="Close", command=self.destroy).pack(side="right")
        self.btn_take_over = ttk.Button(
            button_frame,
            text="Add to Server List...",
            style="Primary.TButton",
            command=self._on_take_over_clicked,
            state="disabled",
        )
        self.btn_take_over.pack(side="right", padx=(0, 6))

    def _run_scan(self) -> None:
        self._scanned_ports = [
            scanned for scanned in scan_listening_ports() if scanned.port not in self._configured_ports
        ]
        self._render_rows()

    def _render_rows(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._ports_by_iid = {}

        for index, scanned in enumerate(self._scanned_ports):
            iid = str(index)
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    scanned.port,
                    scanned.address,
                    service_name_for_port(scanned.port) or "-",
                    scanned.process_name or "-",
                    scanned.pid if scanned.pid is not None else "-",
                ),
            )
            self._ports_by_iid[iid] = scanned

        self._tree_sorter.reapply()
        self.status_var.set(f"Found {len(self._scanned_ports)} unsaved listening port(s).")
        self._update_take_over_button()

    def _describe_selected_port(self) -> str:
        """
        Build the status line for the selected port.

        When the process stays hidden, the owning user account explains why: ``ss``
        only reports process details for sockets belonging to the calling user.

        :return: Status text, empty when nothing is selected
        """
        scanned = self._selected_scanned_port()
        if scanned is None:
            return f"Found {len(self._scanned_ports)} unsaved listening port(s)."

        parts = [f"Port {scanned.port}"]
        service = service_name_for_port(scanned.port)
        if service:
            parts.append(f"usually {service}")

        if scanned.process_name:
            parts.append(f"process {scanned.process_name}")
            if scanned.pid is not None:
                parts.append(f"PID {scanned.pid}")
        else:
            owner = socket_owner_for_port(scanned.port)
            if owner:
                parts.append(
                    f"owned by user '{owner}', so process details are not readable "
                    "without root privileges"
                )
            else:
                parts.append("process details are not readable without root privileges")

        return " · ".join(parts)

    def _selected_scanned_port(self) -> Optional[ScannedPort]:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._ports_by_iid.get(selection[0])

    def _update_take_over_button(self) -> None:
        can_take_over = self._selected_scanned_port() is not None
        self.btn_take_over.configure(state="normal" if can_take_over else "disabled")

    def _on_select(self, _event=None) -> None:
        self._update_take_over_button()
        self.status_var.set(self._describe_selected_port())

    def _on_row_double_click(self, event) -> None:
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.tree.selection_set(row_id)
        self._on_take_over_clicked()

    def _on_take_over_clicked(self) -> None:
        scanned = self._selected_scanned_port()
        if scanned is None:
            return
        self.destroy()
        self._on_take_over(scanned)

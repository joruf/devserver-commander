"""Main application window."""

import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from dataclasses import replace
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Optional, Sequence, Tuple

from config import AppSettingsManager, ConfigManager
from config.validation import make_unique_project_name
from models import ServerProject
from paths import AUTOSTART_FILE, ICON_FILE
from services.php import (
    extract_docroot_from_command,
    extract_php_binary_from_command,
    extract_router_from_command,
    is_php_builtin_command,
)
from services.port_scan import ScannedPort, read_process_cwd, suggest_command_for_port
from services.process import ServerProcess, log_path_for
from services.server_types import server_type_label_for_command
from services.cli_args import parse_args
from services.instance_ipc import InstanceControlServer
from services.single_instance import enforce_single_instance
from services.stats import format_cpu_percent, format_memory_bytes, get_process_stats
from ui.desktop_setup import (
    install_desktop_shortcut,
    is_login_autostart_enabled,
    maybe_prompt_desktop_setup,
    set_login_autostart,
)
from ui.port_scanner_dialog import PortScannerDialog
from ui.preferences_dialog import PreferencesDialog
from ui.project_dialog import ProjectDialog
from ui.startup_notify import notify_desktop_startup_complete
from ui.tray import TrayIcon
from ui.tree_sort import TreeSorter
from ui.window_icon import apply_window_icon

LIST_CHECK_INTERVAL_MS = 2000
LOG_TAIL_BYTES = 8000
TREE_COLUMN_PADDING = 12
TREE_HEADING_EXTRA_PADDING = 16
TREE_AUTOSTART_MIN_WIDTH = 24
LOG_COPY_MAX_LINES = 200
WINDOW_MIN_WIDTH = 960
WINDOW_MIN_HEIGHT = 480
WINDOW_SCREEN_MARGIN = 24
WINDOW_TREE_EXTRA_WIDTH = 48

TREE_COLUMN_HEADINGS = {
    "#0": "Name",
    "type": "Type",
    "port": "Port",
    "workers": "Workers",
    "status": "Status",
    "autostart": "Autostart",
    "directory": "Directory",
    "docroot": "Document root",
    "router": "Router script",
    "cpu": "CPU",
    "memory": "Memory",
}


class MainWindow(tk.Tk):
    """Main application window."""

    def __init__(self, start_in_tray: bool = False) -> None:
        """
        Build the main window.

        :param start_in_tray: Start hidden in the system tray without showing the window
        """
        super().__init__()
        self.title("DevServer Commander")
        self.geometry("1200x560")
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        apply_window_icon(self)

        self._start_in_tray = start_in_tray
        if start_in_tray:
            self.withdraw()

        self.config_manager = ConfigManager()
        self.settings_manager = AppSettingsManager()
        self.app_settings = self.settings_manager.load()
        self.projects: list[ServerProject] = self.config_manager.load()
        self.processes: Dict[str, ServerProcess] = {
            project.name: ServerProcess(project) for project in self.projects
        }
        self._log_offsets: Dict[str, int] = {}
        self._selected_name: Optional[str] = None
        self._refreshing_tree = False
        self._log_follow_tail = True
        self._stats_job_id: Optional[str] = None
        self._tray_icon: Optional[TrayIcon] = None
        self._control_server: Optional[InstanceControlServer] = None
        self._exiting = False
        self._unsaved_names: set[str] = set()
        self._autostart_vars: Dict[str, tk.BooleanVar] = {}
        self._autostart_checkbuttons: Dict[str, tk.Checkbutton] = {}
        self._syncing_autostart_widgets = False
        self._drag_source_name: Optional[str] = None
        self._drag_start_y: int = 0
        self._drag_active = False
        self._drop_indicator_index: Optional[int] = None
        self._columns_auto_sized = False
        self._config_mtime_seen = self._config_mtime()
        self._last_display_snapshot: Optional[tuple] = None
        self._list_poll_job_id: Optional[str] = None

        self._configure_ui_style()
        self._build_menu()
        self._build_widgets()
        self._build_context_menu()
        self._refresh_tree()
        self._update_action_buttons()
        self._schedule_stats_poll()

        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.bind_all("<F5>", self._on_manual_refresh)
        self.after_idle(self._on_application_ready)
        self.after(200, self._autostart_projects)
        self._schedule_list_poll()

    def _configure_ui_style(self) -> None:
        """
        Apply a modern ttk theme with subtle spacing improvements.

        This keeps the existing layout and behavior intact while improving
        visual appearance across the main window and dialogs.
        """
        style = ttk.Style(self)
        available_themes = set(style.theme_names())
        if "clam" in available_themes:
            style.theme_use("clam")

        # Modern neutral gray palette.
        bg = "#f4f4f5"
        panel_bg = "#ffffff"
        fg = "#18181b"
        muted_fg = "#71717a"
        border = "#e4e4e7"
        accent = "#3f3f46"
        accent_hover = "#27272a"
        accent_pressed = "#18181b"
        selection = "#e4e4e7"
        focus = "#a1a1aa"

        self.configure(background=bg)
        self.option_add("*Background", bg)
        self.option_add("*Foreground", fg)
        self.option_add("*Font", "TkDefaultFont 10")
        self.option_add("*Menu.Background", panel_bg)
        self.option_add("*Menu.Foreground", fg)
        self.option_add("*Menu.ActiveBackground", accent)
        self.option_add("*Menu.ActiveForeground", "#fafafa")

        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg, bordercolor=border, relief="flat")
        style.configure("TLabelframe.Label", background=bg, foreground=muted_fg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure(
            "TButton",
            padding=(12, 7),
            background=panel_bg,
            foreground=fg,
            borderwidth=1,
            bordercolor=border,
            focusthickness=1,
            focuscolor=focus,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", "#fafafa"), ("pressed", "#f4f4f5"), ("disabled", bg)],
            foreground=[("disabled", "#a1a1aa")],
            bordercolor=[("active", "#d4d4d8"), ("disabled", border)],
        )
        style.configure(
            "Primary.TButton",
            padding=(12, 7),
            background=accent,
            foreground="#fafafa",
            borderwidth=0,
            focusthickness=0,
            relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[
                ("active", accent_hover),
                ("pressed", accent_pressed),
                ("disabled", "#a1a1aa"),
            ],
            foreground=[("disabled", "#f4f4f5")],
        )
        style.configure(
            "TMenubutton",
            padding=(10, 6),
            background=panel_bg,
            foreground=fg,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "TMenubutton",
            background=[("active", "#fafafa")],
            bordercolor=[("focus", focus)],
        )
        style.configure(
            "TEntry",
            padding=(8, 6),
            fieldbackground=panel_bg,
            foreground=fg,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            relief="flat",
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", focus)],
            lightcolor=[("focus", focus)],
            darkcolor=[("focus", focus)],
        )
        style.configure(
            "TCombobox",
            padding=(8, 6),
            fieldbackground=panel_bg,
            foreground=fg,
            bordercolor=border,
            arrowsize=13,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", panel_bg)],
            bordercolor=[("focus", focus)],
            lightcolor=[("focus", focus)],
            darkcolor=[("focus", focus)],
        )
        style.configure(
            "Treeview",
            rowheight=26,
            background=panel_bg,
            fieldbackground=panel_bg,
            foreground=fg,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
        )
        style.map(
            "Treeview",
            background=[("selected", selection)],
            foreground=[("selected", fg)],
        )
        style.configure(
            "Treeview.Heading",
            padding=(10, 7),
            background=bg,
            foreground=muted_fg,
            bordercolor=border,
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", "#fafafa")], foreground=[("active", fg)])

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Close", command=self._hide_to_tray)
        file_menu.add_command(label="Close and Exit", command=self._quit_application)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(
            label="Refresh Server List",
            command=self._on_manual_refresh,
            accelerator="F5",
        )
        view_menu.add_command(label="Save Visible Log Output...", command=self._save_visible_log)
        view_menu.add_separator()
        view_menu.add_command(label="Port Scanner...", command=self._open_port_scanner)
        menubar.add_cascade(label="View", menu=view_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(label="Preferences...", command=self._open_preferences)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Create Desktop Shortcut...", command=self._create_desktop_shortcut)
        help_menu.add_command(label="About", command=self._show_about)
        help_menu.add_command(label="Developer", command=self._show_developer)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_widgets(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(side="top", fill="x", padx=8, pady=6)

        ttk.Button(toolbar, text="Add", style="Primary.TButton", command=self._add_project).pack(side="left", padx=2)
        self.btn_edit = ttk.Button(toolbar, text="Edit", command=self._edit_project)
        self.btn_edit.pack(side="left", padx=2)
        self.btn_remove = ttk.Button(toolbar, text="Remove", command=self._remove_project)
        self.btn_remove.pack(side="left", padx=2)
        self.btn_save_entry = ttk.Button(
            toolbar, text="Save to servers.json", command=self._save_selected_unsaved_project
        )
        self.btn_save_entry.pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.btn_start = ttk.Button(toolbar, text="Start", style="Primary.TButton", command=self._start_selected)
        self.btn_start.pack(side="left", padx=2)
        self.btn_stop = ttk.Button(toolbar, text="Stop", style="Primary.TButton", command=self._stop_selected)
        self.btn_stop.pack(side="left", padx=2)
        self.btn_restart = ttk.Button(toolbar, text="Restart", style="Primary.TButton", command=self._restart_selected)
        self.btn_restart.pack(side="left", padx=2)
        self.btn_open = ttk.Button(
            toolbar, text="Open Website", style="Primary.TButton", command=self._open_selected_website
        )
        self.btn_open.pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Port Scanner...", command=self._open_port_scanner).pack(side="left", padx=2)

        paned = ttk.Panedwindow(self, orient="vertical")
        paned.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))

        tree_frame = ttk.Frame(paned)
        self.tree_frame = tree_frame
        columns = (
            "type",
            "port",
            "workers",
            "status",
            "autostart",
            "directory",
            "docroot",
            "router",
            "cpu",
            "memory",
        )
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=10)
        self.drop_indicator = tk.Frame(self.tree, height=2, background="#22c55e")
        self.drop_indicator.place_forget()
        for column_id, heading in TREE_COLUMN_HEADINGS.items():
            self.tree.heading(column_id, text=heading)
        for column_id in ("#0", *columns):
            self.tree.column(column_id, stretch=False)
        self.tree.tag_configure("unsaved", foreground="#b45309")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self._tree_sorter = TreeSorter(self.tree, TREE_COLUMN_HEADINGS, on_clear=self._refresh_tree)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Up>", self._on_tree_arrow_key)
        self.tree.bind("<Down>", self._on_tree_arrow_key)
        self.tree.bind("<Button-1>", self._on_tree_focus, add="+")
        self.tree.bind("<Button-3>", self._on_tree_context_menu)
        self.tree.bind("<ButtonPress-1>", self._on_tree_drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._on_tree_drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_drag_release, add="+")
        self.tree.bind("<Configure>", self._position_autostart_widgets, add="+")
        self.tree.bind("<Expose>", self._position_autostart_widgets, add="+")
        self.bind("<Up>", self._on_tree_arrow_key)
        self.bind("<Down>", self._on_tree_arrow_key)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._on_tree_yscroll)
        self.tree.configure(yscrollcommand=self._set_tree_yscroll)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._tree_vscrollbar = scrollbar

        h_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._on_tree_xscroll)
        self.tree.configure(xscrollcommand=self._set_tree_xscroll)
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        self._tree_hscrollbar = h_scrollbar

        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        paned.add(tree_frame, weight=2)

        log_frame = ttk.Frame(paned)
        log_header = ttk.Frame(log_frame)
        log_header.pack(side="top", fill="x")
        ttk.Label(log_header, text="Log output:").pack(side="left", anchor="w")
        self.btn_copy_log = tk.Button(log_header, text="Copy", command=self._copy_log_to_clipboard, padx=6, pady=1)
        self.btn_copy_log.pack(side="right", anchor="e")
        self._copy_button_default_bg = self.btn_copy_log.cget("background")
        self._copy_button_default_active_bg = self.btn_copy_log.cget("activebackground")
        self._copy_button_default_fg = self.btn_copy_log.cget("foreground")
        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(side="top", fill="both", expand=True)
        self.log_text = tk.Text(log_text_frame, height=12, state="disabled", wrap="none")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_text_frame, orient="vertical", command=self._on_log_scroll)
        self.log_text.configure(yscrollcommand=self._set_log_scroll_position)
        log_scroll.pack(side="right", fill="y")
        self._log_scrollbar = log_scroll
        self.log_text.bind("<MouseWheel>", self._on_log_user_scroll)
        self.log_text.bind("<Button-4>", self._on_log_user_scroll)
        self.log_text.bind("<Button-5>", self._on_log_user_scroll)
        self.log_text.bind("<KeyPress>", self._on_log_user_scroll)
        paned.add(log_frame, weight=1)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken").pack(
            side="bottom", fill="x"
        )

    def _build_context_menu(self) -> None:
        self.context_menu = tk.Menu(self, tearoff=False)
        self.context_menu.add_command(label="Start Server", command=self._start_selected)
        self.context_menu.add_command(label="Stop Server", command=self._stop_selected)
        self.context_menu.add_command(label="Restart Server", command=self._restart_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Open Website", command=self._open_selected_website)
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Save to servers.json", command=self._save_selected_unsaved_project
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Edit...", command=self._edit_project)
        self.context_menu.add_command(label="Remove...", command=self._remove_project)

    def _on_application_ready(self) -> None:
        notify_desktop_startup_complete()
        self.update_idletasks()
        tray_available = self._start_tray_icon()
        self._start_control_server()

        if not self._start_in_tray:
            return

        if tray_available:
            self._set_status("Started in the system tray.")
            return

        self.deiconify()
        self._set_status(
            "System tray unavailable, showing the window instead. "
            "Install GTK3 bindings to enable tray support."
        )

    def _start_control_server(self) -> None:
        self._control_server = InstanceControlServer(on_show=lambda: self.after(0, self._show_from_tray))
        self._control_server.start()

    def _start_tray_icon(self) -> bool:
        """
        Start the system tray icon.

        :return: True when tray support is available
        """
        tray = TrayIcon(
            icon_path=ICON_FILE,
            tooltip="DevServer Commander",
            on_show=lambda: self.after(0, self._show_from_tray),
            on_exit=lambda: self.after(0, self._quit_application),
        )
        if tray.start():
            self._tray_icon = tray
            return True

        self._set_status("System tray unavailable. Install GTK3 bindings to enable tray support.")
        return False

    def _get_project(self, name: str) -> Optional[ServerProject]:
        return next((project for project in self.projects if project.name == name), None)

    def _selected_project_name(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _docroot_and_router(self, project: ServerProject) -> tuple[str, str]:
        if not is_php_builtin_command(project.command):
            return "-", "-"
        docroot = extract_docroot_from_command(project.command)
        router = extract_router_from_command(project.command) or "-"
        return docroot, router

    @staticmethod
    def _type_label(project: ServerProject) -> str:
        """
        Build the type label shown in the server table.

        For PHP projects, include the configured PHP version when available.

        :param project: Project whose type label is rendered
        :return: Type label for the table, e.g. ``PHP 8.2``
        """
        base_label = server_type_label_for_command(project.command)
        if base_label != "PHP":
            return base_label

        php_binary = extract_php_binary_from_command(project.command)
        if not php_binary:
            return "PHP"

        binary_name = php_binary.split("/")[-1]
        if binary_name == "php":
            return "PHP"
        if binary_name.startswith("php") and len(binary_name) > 3:
            return f"PHP {binary_name[3:]}"
        return "PHP"

    def _process_stats(self, name: str) -> Tuple[str, str]:
        process = self.processes.get(name)
        if process is None or not process.is_running():
            return "-", "-"

        pid = process.resolve_pid()
        if pid is None:
            return "-", "-"

        cpu_percent, memory_bytes = get_process_stats(pid)
        return format_cpu_percent(cpu_percent), format_memory_bytes(memory_bytes)

    def _update_action_buttons(self) -> None:
        selected_name = self._selected_project_name()
        has_selection = selected_name is not None
        state = "normal" if has_selection else "disabled"
        for button in (
            self.btn_edit,
            self.btn_remove,
            self.btn_start,
            self.btn_stop,
            self.btn_restart,
            self.btn_open,
        ):
            button.configure(state=state)

        can_save_entry = has_selection and selected_name in self._unsaved_names
        self.btn_save_entry.configure(state="normal" if can_save_entry else "disabled")

        if has_selection:
            project = self._get_project(selected_name or "")
            can_open = project is not None and project.port is not None
            self.btn_open.configure(state="normal" if can_open else "disabled")

    def _config_mtime(self) -> float:
        """
        Return the modification time of the servers configuration file.

        :return: File mtime in seconds, or ``0.0`` when unavailable
        """
        try:
            return self.config_manager.path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _projects_signature(projects: list[ServerProject]) -> tuple:
        """
        Build a comparable signature for the current project configuration.

        :param projects: Project list to summarize
        :return: Stable tuple describing project identity and runtime fields
        """
        return tuple(
            (
                project.name,
                project.directory,
                project.command,
                project.port,
                tuple(sorted(project.env.items())),
                project.autostart,
            )
            for project in projects
        )

    def _sync_processes_with_projects(self) -> None:
        """
        Keep the process map aligned with the current project list.

        Creates missing process wrappers, updates existing project references,
        and drops wrappers for removed projects.
        """
        current_names = {project.name for project in self.projects}
        for name in list(self.processes):
            if name not in current_names:
                del self.processes[name]
                self._log_offsets.pop(name, None)

        for project in self.projects:
            existing = self.processes.get(project.name)
            if existing is None:
                self.processes[project.name] = ServerProcess(project)
            else:
                existing.project = project

    def _reload_projects_from_disk(self, *, force: bool = False) -> bool:
        """
        Reload projects from disk when the configuration file changed.

        Unsaved trial projects (added from the port scanner but not yet
        written to servers.json) are kept across the reload, unless a
        persisted project with the same name now exists on disk.

        :param force: Reload even when the file mtime appears unchanged
        :return: True when the in-memory project list changed
        """
        mtime = self._config_mtime()
        if not force and mtime == self._config_mtime_seen:
            return False

        loaded = self.config_manager.load()
        self._config_mtime_seen = mtime

        loaded_names = {project.name for project in loaded}
        surviving_unsaved = [
            project
            for project in self.projects
            if project.name in self._unsaved_names and project.name not in loaded_names
        ]
        self._unsaved_names = {project.name for project in surviving_unsaved}
        merged = loaded + surviving_unsaved

        if self._projects_signature(merged) == self._projects_signature(self.projects):
            return False

        self.projects = merged
        self._sync_processes_with_projects()
        return True

    def _project_status_label(self, project: ServerProject) -> str:
        """
        Build the status label for one project row.

        :param project: Project whose runtime status is rendered
        :return: Status text for the table
        """
        process = self.processes.get(project.name)
        if process is None or not process.is_running():
            return "Stopped"
        if process.unmanaged:
            return "Running (unmanaged)"
        return "Running"

    def _display_snapshot(self) -> tuple:
        """
        Build a comparable snapshot of currently displayed list data.

        CPU/memory are excluded because they are refreshed on a separate timer.

        :return: Snapshot of list rows that should trigger a UI refresh
        """
        rows = []
        for project in self.projects:
            docroot, router = self._docroot_and_router(project)
            rows.append(
                (
                    project.name,
                    self._type_label(project),
                    project.port if project.port is not None else "-",
                    self._workers_label(project),
                    self._project_status_label(project),
                    project.autostart,
                    project.directory,
                    docroot,
                    router,
                )
            )
        return tuple(rows)

    def _refresh_tree(self) -> None:
        previous_selection = self._selected_project_name()
        self._refreshing_tree = True
        try:
            for item in self.tree.get_children():
                self.tree.delete(item)

            for project in self.projects:
                docroot, router = self._docroot_and_router(project)
                cpu_label, memory_label = self._process_stats(project.name)
                is_unsaved = project.name in self._unsaved_names
                display_name = f"{project.name} (not saved)" if is_unsaved else project.name
                self.tree.insert(
                    "",
                    "end",
                    iid=project.name,
                    text=display_name,
                    values=(
                        self._type_label(project),
                        project.port if project.port is not None else "-",
                        self._workers_label(project),
                        self._project_status_label(project),
                        "",
                        project.directory,
                        docroot,
                        router,
                        cpu_label,
                        memory_label,
                    ),
                    tags=("unsaved",) if is_unsaved else (),
                )

            self._tree_sorter.reapply()

            if previous_selection and self.tree.exists(previous_selection):
                self.tree.selection_set(previous_selection)
            else:
                self.tree.selection_remove(self.tree.selection())
        finally:
            self._refreshing_tree = False

        if not self._columns_auto_sized:
            self._resize_tree_columns()
            self._fit_window_width_to_tree()
            self._columns_auto_sized = True
        self._sync_autostart_widgets()
        self._selected_name = self._selected_project_name()
        self._update_action_buttons()
        self._last_display_snapshot = self._display_snapshot()

    def _refresh_tree_if_changed(self, *, force: bool = False) -> bool:
        """
        Refresh the server table only when display data changed.

        :param force: Rebuild the table even when the snapshot is unchanged
        :return: True when the table was refreshed
        """
        snapshot = self._display_snapshot()
        if not force and snapshot == self._last_display_snapshot:
            return False
        self._refresh_tree()
        return True

    @staticmethod
    def _read_boolean_var(variable: tk.BooleanVar) -> bool:
        """
        Read a Tk boolean variable as a Python bool.

        :param variable: Tk variable bound to a checkbox
        :return: Parsed boolean value
        """
        value = variable.get()
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return int(value) != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _set_tree_yscroll(self, first: str, last: str) -> None:
        self._tree_vscrollbar.set(first, last)
        self._position_autostart_widgets()
        self._update_drop_indicator_position()

    def _on_tree_yscroll(self, *args) -> None:
        self.tree.yview(*args)
        self._position_autostart_widgets()

    def _set_tree_xscroll(self, first: str, last: str) -> None:
        self._tree_hscrollbar.set(first, last)
        self._position_autostart_widgets()
        self._update_drop_indicator_position()

    def _on_tree_xscroll(self, *args) -> None:
        self.tree.xview(*args)
        self._position_autostart_widgets()

    def _tree_font(self) -> tkfont.Font:
        """
        Return the font used by the server list tree view.

        :return: Treeview font
        """
        style = ttk.Style()
        font_spec = style.lookup("Treeview", "font")
        if font_spec:
            return tkfont.Font(font=font_spec)
        return tkfont.Font()

    def _tree_heading_font(self) -> tkfont.Font:
        """
        Return the font used by tree view column headings.

        :return: Treeview heading font
        """
        style = ttk.Style()
        font_spec = style.lookup("Treeview.Heading", "font")
        if font_spec:
            return tkfont.Font(font=font_spec)
        return self._tree_font()

    def _text_width(self, font: tkfont.Font, text: str) -> int:
        """
        Measure rendered text width in pixels.

        :param font: Font used for rendering
        :param text: Text to measure
        :return: Width in pixels
        """
        return font.measure(text or "")

    def _resize_tree_columns(self) -> None:
        """Resize tree columns to fit the longest visible cell content."""
        content_font = self._tree_font()
        heading_font = self._tree_heading_font()

        for column_id, heading in TREE_COLUMN_HEADINGS.items():
            heading_width = self._text_width(heading_font, heading) + TREE_HEADING_EXTRA_PADDING
            max_width = heading_width
            if column_id == "#0":
                for item in self.tree.get_children():
                    max_width = max(
                        max_width,
                        self._text_width(content_font, self.tree.item(item, "text")),
                    )
            else:
                for item in self.tree.get_children():
                    values = self.tree.item(item, "values")
                    column_index = list(self.tree["columns"]).index(column_id)
                    if column_index < len(values):
                        max_width = max(
                            max_width,
                            self._text_width(content_font, str(values[column_index])),
                        )

            if column_id == "autostart":
                max_width = max(max_width, TREE_AUTOSTART_MIN_WIDTH)

            width = max_width + TREE_COLUMN_PADDING
            min_width = TREE_AUTOSTART_MIN_WIDTH if column_id == "autostart" else 40
            self.tree.column(column_id, width=width, minwidth=min_width, stretch=False, anchor="w")

    def _fit_window_width_to_tree(self) -> None:
        """
        Resize the main window width to the table width within screen bounds.

        The width is clamped so the window remains fully visible on screen.
        """
        self.update_idletasks()

        column_ids = ["#0", *self.tree["columns"]]
        table_width = sum(int(self.tree.column(column_id, "width")) for column_id in column_ids)
        scrollbar_width = self._tree_vscrollbar.winfo_width() or 16
        target_width = table_width + scrollbar_width + WINDOW_TREE_EXTRA_WIDTH
        target_width = max(target_width, WINDOW_MIN_WIDTH)

        screen_width = self.winfo_screenwidth()
        max_width = max(WINDOW_MIN_WIDTH, screen_width - WINDOW_SCREEN_MARGIN)
        target_width = min(target_width, max_width)

        current_height = max(self.winfo_height(), WINDOW_MIN_HEIGHT)
        current_x = max(self.winfo_x(), 0)
        current_y = max(self.winfo_y(), 0)
        screen_height = self.winfo_screenheight()

        max_x = max(0, screen_width - target_width)
        max_y = max(0, screen_height - current_height)
        target_x = min(current_x, max_x)
        target_y = min(current_y, max_y)

        self.geometry(f"{target_width}x{current_height}+{target_x}+{target_y}")

    def _sync_autostart_widgets(self) -> None:
        """Create or update autostart checkboxes for the current server list."""
        active_names = {project.name for project in self.projects}

        for name in list(self._autostart_checkbuttons):
            if name in active_names:
                continue
            self._autostart_checkbuttons[name].destroy()
            del self._autostart_checkbuttons[name]
            del self._autostart_vars[name]

        for project in self.projects:
            name = project.name
            if name not in self._autostart_vars:
                variable = tk.BooleanVar(master=self, value=project.autostart)
                self._autostart_vars[name] = variable
                checkbox = tk.Checkbutton(
                    self.tree,
                    variable=variable,
                    command=lambda project_name=name: self._on_autostart_checkbox_toggle(project_name),
                    bd=0,
                    highlightthickness=0,
                )
                self._autostart_checkbuttons[name] = checkbox
                continue

            self._syncing_autostart_widgets = True
            try:
                self._autostart_vars[name].set(project.autostart)
            finally:
                self._syncing_autostart_widgets = False

        self.after_idle(self._position_autostart_widgets)

    def _position_autostart_widgets(self, _event=None) -> None:
        """Place autostart checkboxes over the Autostart column cells."""
        for name, checkbox in self._autostart_checkbuttons.items():
            if not self.tree.exists(name):
                checkbox.place_forget()
                continue

            bbox = self.tree.bbox(name, "autostart")
            if not bbox:
                checkbox.place_forget()
                continue

            x, y, width, height = bbox
            checkbox_width = 20
            checkbox_height = min(height, 20)
            checkbox.place(
                in_=self.tree,
                x=x + max((width - checkbox_width) // 2, 0),
                y=y + max((height - checkbox_height) // 2, 0),
                width=checkbox_width,
                height=checkbox_height,
            )
        self._update_drop_indicator_position()

    def _on_autostart_checkbox_toggle(self, name: str) -> None:
        """
        Persist an autostart change from the server list checkbox.

        :param name: Project name whose autostart flag changed
        """
        if self._syncing_autostart_widgets or self._refreshing_tree:
            return

        variable = self._autostart_vars.get(name)
        if variable is None:
            return

        self._set_project_autostart(name, self._read_boolean_var(variable))

    def _set_project_autostart(self, name: str, enabled: bool) -> None:
        """
        Update autostart for a project, save JSON, and refresh the list.

        :param name: Project name
        :param enabled: New autostart value
        """
        project = self._get_project(name)
        if project is None or project.autostart == enabled:
            return

        updated = replace(project, autostart=enabled)
        index = self.projects.index(project)
        self.projects[index] = updated
        if name in self.processes:
            self.processes[name].project = updated

        self.config_manager.save(self.projects)
        self._refresh_tree()
        if self.tree.exists(name):
            self.tree.selection_set(name)
        self._set_status(f"Autostart for '{name}' {'enabled' if enabled else 'disabled'}.")

    def _update_server_stats(self) -> None:
        for project in self.projects:
            if not self.tree.exists(project.name):
                continue

            cpu_label, memory_label = self._process_stats(project.name)
            values = list(self.tree.item(project.name, "values"))
            if len(values) >= 10:
                values[8] = cpu_label
                values[9] = memory_label
                self.tree.item(project.name, values=values)

        self.after_idle(self._position_autostart_widgets)

    def _schedule_stats_poll(self) -> None:
        if self._stats_job_id is not None:
            self.after_cancel(self._stats_job_id)

        self._update_server_stats()
        interval_ms = self.app_settings.stats_refresh_interval_seconds * 1000
        self._stats_job_id = self.after(interval_ms, self._schedule_stats_poll)

    def _schedule_list_poll(self) -> None:
        """
        Schedule the next server-list consistency check.

        :return: None
        """
        if self._list_poll_job_id is not None:
            self.after_cancel(self._list_poll_job_id)
        self._list_poll_job_id = self.after(LIST_CHECK_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        """
        Periodically reload config changes and refresh the list when needed.

        :return: None
        """
        reloaded = self._reload_projects_from_disk()
        self._refresh_tree_if_changed(force=reloaded)
        self._refresh_log_tail()
        self._schedule_list_poll()

    def _on_manual_refresh(self, _event=None) -> Optional[str]:
        """
        Force-reload the server list from disk and refresh the table.

        Triggered by F5 or View → Refresh Server List.

        :param _event: Optional Tk key event
        :return: ``"break"`` when called from a key binding
        """
        reloaded = self._reload_projects_from_disk(force=True)
        self._refresh_tree_if_changed(force=True)
        self._refresh_log_tail(force_full=True)
        if reloaded:
            self._set_status("Server list reloaded from configuration.")
        else:
            self._set_status("Server list refreshed.")
        return "break"

    def _on_tree_focus(self, _event=None) -> None:
        self.tree.focus_set()

    def _on_tree_drag_start(self, event) -> None:
        """
        Initialize a potential drag-and-drop reorder operation.

        :param event: Tkinter mouse event from the tree view
        """
        if self._refreshing_tree:
            return

        if self._tree_sorter.is_sorted:
            self._drag_source_name = None
            self._set_status(
                "Manual reordering is disabled while the list is sorted. "
                "Click the sorted column header again to return to the saved order."
            )
            return

        row_id = self.tree.identify_row(event.y)
        self._drag_source_name = row_id if row_id else None
        self._drag_start_y = event.y
        self._drag_active = False
        self._hide_drop_indicator()

    def _on_tree_drag_motion(self, event) -> None:
        """
        Mark drag operation as active after slight mouse movement.

        :param event: Tkinter mouse event from the tree view
        """
        if not self._drag_source_name:
            return

        if self._drag_active:
            self._show_drop_indicator(self._drop_index_for_y(event.y))
            return

        if abs(event.y - self._drag_start_y) < 4:
            self._hide_drop_indicator()
            return

        self._drag_active = True
        self.tree.configure(cursor="fleur")
        self._show_drop_indicator(self._drop_index_for_y(event.y))

    def _drop_index_for_y(self, y: int) -> int:
        """
        Calculate insertion index for a drop position in the tree view.

        :param y: Mouse y-coordinate relative to the tree widget
        :return: Target insertion index in the current tree order
        """
        items = list(self.tree.get_children())
        if not items:
            return 0

        row_id = self.tree.identify_row(y)
        if row_id:
            bbox = self.tree.bbox(row_id)
            target_index = items.index(row_id)
            if bbox:
                _x, row_y, _width, row_height = bbox
                if y > row_y + (row_height // 2):
                    target_index += 1
            return target_index

        first_bbox = self.tree.bbox(items[0])
        if first_bbox and y < first_bbox[1]:
            return 0

        return len(items)

    def _show_drop_indicator(self, target_index: int) -> None:
        """
        Show a horizontal insertion line for the current drag target.

        :param target_index: Insertion index represented by the line
        """
        self._drop_indicator_index = target_index
        self._update_drop_indicator_position()

    def _update_drop_indicator_position(self) -> None:
        """Recalculate and place the insertion line for the active drag target."""
        if self._drop_indicator_index is None:
            self.drop_indicator.place_forget()
            return

        items = list(self.tree.get_children())
        if not items:
            self.drop_indicator.place_forget()
            return

        target_index = max(0, min(self._drop_indicator_index, len(items)))
        y_position: Optional[int] = None

        if target_index < len(items):
            target_bbox = self.tree.bbox(items[target_index])
            if target_bbox:
                _x, y_position, _width, _height = target_bbox
        else:
            last_bbox = self.tree.bbox(items[-1])
            if last_bbox:
                _x, last_y, _width, last_height = last_bbox
                y_position = last_y + last_height

        if y_position is None:
            self.drop_indicator.place_forget()
            return

        line_width = max(self.tree.winfo_width() - 2, 1)
        self.drop_indicator.place(in_=self.tree, x=1, y=max(y_position - 1, 0), width=line_width, height=2)
        self.drop_indicator.lift()

    def _hide_drop_indicator(self) -> None:
        """Hide and reset the drag-and-drop insertion line."""
        self._drop_indicator_index = None
        self.drop_indicator.place_forget()

    def _reorder_project(self, source_name: str, target_index: int) -> bool:
        """
        Move a project within the list and keep process mapping in sync.

        :param source_name: Name of the dragged project
        :param target_index: Requested insertion index in current order
        :return: True when order changed, otherwise False
        """
        names = [project.name for project in self.projects]
        if source_name not in names:
            return False

        source_index = names.index(source_name)
        normalized_target_index = max(0, min(target_index, len(self.projects)))
        if normalized_target_index > source_index:
            normalized_target_index -= 1

        if normalized_target_index == source_index:
            return False

        moved_project = self.projects.pop(source_index)
        self.projects.insert(normalized_target_index, moved_project)

        self.processes = {
            project.name: self.processes[project.name]
            for project in self.projects
            if project.name in self.processes
        }
        return True

    def _on_tree_drag_release(self, event) -> None:
        """
        Finalize drag-and-drop reorder and persist updated server order.

        :param event: Tkinter mouse event from the tree view
        """
        source_name = self._drag_source_name
        drag_active = self._drag_active

        self._drag_source_name = None
        self._drag_active = False
        self.tree.configure(cursor="")
        self._hide_drop_indicator()

        if not source_name or not drag_active:
            return

        target_index = self._drop_index_for_y(event.y)
        if not self._reorder_project(source_name, target_index):
            return

        self._save()
        self._refresh_tree()
        if self.tree.exists(source_name):
            self.tree.selection_set(source_name)
            self.tree.focus(source_name)
            self.tree.see(source_name)
        self._set_status(f"Moved '{source_name}' and saved server order.")

    def _on_tree_context_menu(self, event) -> None:
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            self._selected_name = row_id
            self._update_action_buttons()
            save_state = "normal" if row_id in self._unsaved_names else "disabled"
            self.context_menu.entryconfig("Save to servers.json", state=save_state)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _on_tree_arrow_key(self, event) -> Optional[str]:
        if self._refreshing_tree:
            return "break"

        focus = self.focus_get()
        if focus is self.log_text:
            return None

        items = list(self.tree.get_children())
        if not items:
            return "break"

        current = self._selected_project_name()
        if current in items:
            index = items.index(current)
        elif event.keysym == "Down":
            index = -1
        else:
            index = len(items)

        if event.keysym == "Down":
            new_index = min(index + 1, len(items) - 1)
        else:
            new_index = max(index - 1, 0)

        new_id = items[new_index]
        if new_id != current:
            self.tree.focus_set()
            self.tree.selection_set(new_id)
            self.tree.focus(new_id)
            self.tree.see(new_id)

        return "break"

    def _on_select(self, _event=None) -> None:
        self._selected_name = self._selected_project_name()
        self._update_action_buttons()

        if self._selected_name:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
            self._log_offsets.pop(self._selected_name, None)
            self._log_follow_tail = True
            self._refresh_log_tail(force_full=True)
        else:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")

    def _on_tree_double_click(self, event) -> None:
        if self._refreshing_tree:
            return
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self._edit_project()

    def _set_log_scroll_position(self, first: str, last: str) -> None:
        self._log_scrollbar.set(first, last)

    def _on_log_scroll(self, *args) -> None:
        self.log_text.yview(*args)
        self._sync_log_follow_state()

    def _on_log_user_scroll(self, _event=None) -> Optional[str]:
        self.after_idle(self._sync_log_follow_state)
        return None

    def _sync_log_follow_state(self) -> None:
        try:
            _first, last = self.log_text.yview()
        except tk.TclError:
            return

        self._log_follow_tail = float(last) >= 0.999

    def _refresh_log_tail(self, force_full: bool = False) -> None:
        name = self._selected_name
        if not name:
            return
        project = self._get_project(name)
        if project is None:
            return

        path = log_path_for(project)
        if not path.is_file():
            return

        try:
            size = path.stat().st_size
            offset = 0 if force_full else self._log_offsets.get(name, size)
            offset = min(offset, size)
            if force_full:
                offset = max(0, size - LOG_TAIL_BYTES)

            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                new_content = handle.read()

            if new_content:
                self.log_text.configure(state="normal")
                self.log_text.insert("end", new_content)
                if self._log_follow_tail:
                    self.log_text.see("end")
                self.log_text.configure(state="disabled")

            self._log_offsets[name] = size
        except OSError:
            pass

    def _save_visible_log(self) -> None:
        content = self.log_text.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showinfo("Save Log", "There is no visible log output to save.")
            return

        selected_name = self._selected_project_name() or "log"
        safe_name = "".join(
            character if character.isalnum() or character in "-_." else "_"
            for character in selected_name
        )
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Save Visible Log Output",
            defaultextension=".txt",
            initialfile=f"{safe_name}-log.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not destination:
            return

        try:
            with open(destination, "w", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as exc:
            messagebox.showerror("Save Log", f"Could not save the log file:\n{exc}")
            return

        self._set_status(f"Saved visible log output to {destination}.")

    def _add_project(self) -> None:
        dialog = ProjectDialog(self, existing_projects=self.projects)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.projects.append(dialog.result)
        self.processes[dialog.result.name] = ServerProcess(dialog.result)
        self._save()
        self._start_project(dialog.result.name)
        self._refresh_tree()

    def _edit_project(self) -> None:
        name = self._selected_project_name()
        if not name:
            return
        project = self._get_project(name)
        if project is None:
            return

        was_running = self.processes[name].is_running()
        dialog = ProjectDialog(self, project=project, existing_projects=self.projects)
        self.wait_window(dialog)
        if dialog.result is None:
            return

        needs_restart = project.runtime_config_differs(dialog.result)
        restart_now = False
        if was_running and needs_restart:
            restart_now = messagebox.askyesno(
                "Restart Required",
                "The server must be stopped and restarted for changes to take effect.\n\n"
                "Stop the server, apply the changes, and restart now?",
            )
            if restart_now:
                self._stop_project(name)

        index = self.projects.index(project)
        self.projects[index] = dialog.result
        del self.processes[name]
        self.processes[dialog.result.name] = ServerProcess(dialog.result)
        if name in self._unsaved_names:
            self._unsaved_names.discard(name)
            self._unsaved_names.add(dialog.result.name)
        self._save()
        self._refresh_tree()

        if was_running and needs_restart:
            if restart_now:
                self._start_project(dialog.result.name)
            else:
                messagebox.showinfo(
                    "Changes Saved",
                    "Configuration saved. Restart the server manually for runtime changes to take effect.",
                )

    def _remove_project(self) -> None:
        name = self._selected_project_name()
        if not name:
            return
        if self.processes[name].is_running():
            messagebox.showwarning("Server Running", "Stop the server before removing this project.")
            return
        if not messagebox.askyesno("Remove Project", f"Remove '{name}' from the project list?"):
            return

        self.projects = [project for project in self.projects if project.name != name]
        del self.processes[name]
        self._unsaved_names.discard(name)
        self._save()
        self._refresh_tree()

    @staticmethod
    def _workers_label(project: ServerProject) -> str:
        """
        Build the workers label shown in the server table.

        :param project: Project whose worker configuration is rendered
        :return: Worker count or "-" when no worker count is configured
        """
        workers = project.env.get("PHP_CLI_SERVER_WORKERS", "").strip()
        return workers if workers else "-"

    def _copy_log_to_clipboard(self) -> None:
        """Copy up to the latest 200 log lines of the selected project to the clipboard."""
        name = self._selected_project_name()
        if not name:
            messagebox.showinfo("Copy Log", "Please select a project first.")
            return

        project = self._get_project(name)
        if project is None:
            messagebox.showinfo("Copy Log", "The selected project is no longer available.")
            return

        log_path = log_path_for(project)
        if not log_path.is_file():
            messagebox.showinfo("Copy Log", "No log file exists yet for this project.")
            return

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError as exc:
            messagebox.showerror("Copy Log", f"Could not read the log file:\n{exc}")
            return

        if not lines:
            messagebox.showinfo("Copy Log", "The log file is empty.")
            return

        copied_lines = lines[-LOG_COPY_MAX_LINES:]
        clipboard_text = "\n".join(copied_lines)
        self.clipboard_clear()
        self.clipboard_append(clipboard_text)
        self.update_idletasks()
        self._flash_copy_button()
        self._set_status(
            f"Copied {len(copied_lines)} log line(s) from '{project.name}' "
            f"(latest {LOG_COPY_MAX_LINES} max)."
        )

    def _flash_copy_button(self) -> None:
        """Highlight the copy button briefly to confirm a successful clipboard copy."""
        self.btn_copy_log.configure(
            background="#22c55e",
            activebackground="#16a34a",
            foreground="#ffffff",
        )
        self.after(700, self._reset_copy_button_style)

    def _reset_copy_button_style(self) -> None:
        """Restore the copy button colors after the success highlight animation."""
        self.btn_copy_log.configure(
            background=self._copy_button_default_bg,
            activebackground=self._copy_button_default_active_bg,
            foreground=self._copy_button_default_fg,
        )

    def _website_url_for(self, project: ServerProject) -> Optional[str]:
        if project.port is None:
            return None
        return f"http://localhost:{project.port}/"

    def _open_selected_website(self) -> None:
        name = self._selected_project_name()
        if not name:
            return
        project = self._get_project(name)
        if project is None:
            return

        url = self._website_url_for(project)
        if url is None:
            messagebox.showinfo("Open Website", "This server has no port configured.")
            return

        webbrowser.open(url)
        self._set_status(f"Opened {url}")

    def _start_selected(self) -> None:
        name = self._selected_project_name()
        if not name:
            return
        self._start_project(name)
        self._refresh_tree()

    def _stop_selected(self) -> None:
        name = self._selected_project_name()
        if not name:
            return
        self._stop_project(name)
        self._refresh_tree()

    def _restart_selected(self) -> None:
        name = self._selected_project_name()
        if not name:
            return
        try:
            self.processes[name].restart()
            self._set_status(f"Restarted '{name}'.")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            messagebox.showerror("Restart Failed", str(exc))
        self._refresh_tree()

    def _start_project(self, name: str) -> bool:
        try:
            self.processes[name].start()
            self._set_status(f"Started '{name}'.")
            return True
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            messagebox.showerror("Start Failed", f"Could not start '{name}':\n{exc}")
            return False

    def _stop_project(self, name: str) -> None:
        try:
            self.processes[name].stop()
            self._set_status(f"Stopped '{name}'.")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            messagebox.showerror("Stop Failed", f"Could not stop '{name}':\n{exc}")

    def _autostart_projects(self) -> None:
        started = []
        for project in self.projects:
            if project.autostart and not self.processes[project.name].is_running():
                if self._start_project(project.name):
                    started.append(project.name)
        if started:
            self._set_status(f"Autostarted: {', '.join(started)}")
        self._refresh_tree()

    def _save(self) -> None:
        """Persist all projects except unsaved trial entries from the port scanner."""
        persisted = [project for project in self.projects if project.name not in self._unsaved_names]
        self.config_manager.save(persisted)
        self._config_mtime_seen = self._config_mtime()

    def _open_preferences(self) -> None:
        dialog = PreferencesDialog(
            self,
            settings=self.app_settings,
            login_autostart=is_login_autostart_enabled(),
        )
        self.wait_window(dialog)
        if dialog.result is None:
            return

        self.app_settings = dialog.result
        self.settings_manager.save(self.app_settings)
        self._schedule_stats_poll()
        self._apply_login_autostart(dialog.login_autostart_result)
        self._set_status(
            "Preferences saved. CPU and memory values refresh every "
            f"{self.app_settings.stats_refresh_interval_seconds} seconds."
        )

    def _apply_login_autostart(self, enabled: Optional[bool]) -> None:
        """
        Install or remove the login autostart entry when the setting changed.

        :param enabled: Requested state, or None when the dialog was cancelled
        :return: None
        """
        if enabled is None or enabled == is_login_autostart_enabled():
            return

        if set_login_autostart(enabled):
            return

        action = "enable" if enabled else "disable"
        messagebox.showerror(
            "Autostart",
            f"Could not {action} the autostart entry at:\n{AUTOSTART_FILE}",
            parent=self,
        )

    def _open_port_scanner(self) -> None:
        """Open the port scanner dialog listing all listening TCP ports."""
        configured_ports = {
            project.port: project.name for project in self.projects if project.port is not None
        }
        dialog = PortScannerDialog(
            self,
            configured_ports=configured_ports,
            on_take_over=self._take_over_scanned_port,
        )
        self.wait_window(dialog)

    def _take_over_scanned_port(self, scanned: ScannedPort) -> None:
        """
        Open the project dialog pre-filled from a scanned port for a trial add.

        The result is added to the in-memory server list so it can be started,
        stopped, and tested right away, but is intentionally NOT written to
        servers.json until the user explicitly saves it.

        :param scanned: Port entry taken over from the port scanner dialog
        """
        directory = read_process_cwd(scanned.pid) if scanned.pid is not None else None
        command = suggest_command_for_port(scanned.pid, scanned.port) if scanned.pid is not None else ""

        suggested_name = make_unique_project_name(
            self.projects, scanned.process_name or f"Port {scanned.port}"
        )
        guessed = ServerProject(
            name=suggested_name,
            directory=directory or "",
            command=command,
            port=scanned.port,
            env={},
            autostart=False,
        )

        dialog = ProjectDialog(self, project=guessed, existing_projects=self.projects)
        dialog.title("Add Project from Port Scan")
        self.wait_window(dialog)
        if dialog.result is None:
            return

        self.projects.append(dialog.result)
        self.processes[dialog.result.name] = ServerProcess(dialog.result)
        self._unsaved_names.add(dialog.result.name)
        self._refresh_tree()
        self._set_status(
            f"Added '{dialog.result.name}' to the list for testing. "
            "Use 'Save to servers.json' to keep it permanently."
        )

    def _save_selected_unsaved_project(self) -> None:
        """Persist the selected unsaved trial project to servers.json."""
        name = self._selected_project_name()
        if not name or name not in self._unsaved_names:
            return

        self._unsaved_names.discard(name)
        self._save()
        self._refresh_tree()
        if self.tree.exists(name):
            self.tree.selection_set(name)
        self._set_status(f"Saved '{name}' to servers.json.")

    def _create_desktop_shortcut(self) -> None:
        success, path = install_desktop_shortcut()
        if success:
            messagebox.showinfo("Desktop Shortcut", f"Shortcut created at:\n{path}")
        else:
            messagebox.showerror("Desktop Shortcut", "Could not create the desktop shortcut.")

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About DevServer Commander",
            "DevServer Commander\n\n"
            "Start, stop and restart local development servers "
            "defined in your own project list.",
        )

    def _show_developer(self) -> None:
        messagebox.showinfo(
            "Developer",
            "Joachim Ruf\n"
            "Loresoft\n\n"
            "GitHub: https://github.com/joruf\n"
            "Web: https://www.loresoft.de/",
        )

    def _hide_to_tray(self) -> None:
        self.withdraw()
        self._set_status("Running in the system tray.")

    def _show_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_window_close(self) -> None:
        self._hide_to_tray()

    def _quit_application(self) -> None:
        if self._exiting:
            return

        self._exiting = True
        if self._control_server is not None:
            self._control_server.stop()
            self._control_server = None
        self.destroy()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Run the application.

    :param argv: Command-line arguments without the program name; defaults to sys.argv[1:]
    :return: Process exit code
    """
    options = parse_args(argv)

    may_continue, instance_guard = enforce_single_instance(quiet=options.start_in_tray)
    if not may_continue:
        return 1

    app = MainWindow(start_in_tray=options.start_in_tray)
    app._instance_guard = instance_guard
    if not options.start_in_tray:
        app.after(100, lambda: maybe_prompt_desktop_setup(app))
    app.mainloop()
    instance_guard.release()
    return 0

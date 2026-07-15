"""Main application window."""

import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from dataclasses import replace
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Optional, Tuple

from config import AppSettingsManager, ConfigManager
from models import ServerProject
from paths import ICON_FILE
from services.php import (
    extract_docroot_from_command,
    extract_router_from_command,
    is_php_builtin_command,
)
from services.process import ServerProcess, log_path_for
from services.server_types import server_type_label_for_command
from services.instance_ipc import InstanceControlServer
from services.single_instance import enforce_single_instance
from services.stats import format_cpu_percent, format_memory_bytes, get_process_stats
from ui.desktop_setup import install_desktop_shortcut, maybe_prompt_desktop_setup
from ui.preferences_dialog import PreferencesDialog
from ui.project_dialog import ProjectDialog
from ui.startup_notify import notify_desktop_startup_complete
from ui.tray import TrayIcon
from ui.window_icon import apply_window_icon

POLL_INTERVAL_MS = 1000
LOG_TAIL_BYTES = 8000
TREE_COLUMN_PADDING = 12
TREE_AUTOSTART_MIN_WIDTH = 24
LOG_COPY_MAX_LINES = 200


class MainWindow(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("DevServer Commander")
        self.geometry("1200x560")
        self.minsize(960, 480)
        apply_window_icon(self)

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
        self._autostart_vars: Dict[str, tk.BooleanVar] = {}
        self._autostart_checkbuttons: Dict[str, tk.Checkbutton] = {}
        self._syncing_autostart_widgets = False
        self._drag_source_name: Optional[str] = None
        self._drag_start_y: int = 0
        self._drag_active = False
        self._drop_indicator_index: Optional[int] = None

        self._build_menu()
        self._build_widgets()
        self._build_context_menu()
        self._refresh_tree()
        self._update_action_buttons()
        self._schedule_stats_poll()

        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.after_idle(self._on_application_ready)
        self.after(200, self._autostart_projects)
        self.after(POLL_INTERVAL_MS, self._poll)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Close", command=self._hide_to_tray)
        file_menu.add_command(label="Close and Exit", command=self._quit_application)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Save Visible Log Output...", command=self._save_visible_log)
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

        ttk.Button(toolbar, text="Add", command=self._add_project).pack(side="left", padx=2)
        self.btn_edit = ttk.Button(toolbar, text="Edit", command=self._edit_project)
        self.btn_edit.pack(side="left", padx=2)
        self.btn_remove = ttk.Button(toolbar, text="Remove", command=self._remove_project)
        self.btn_remove.pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.btn_start = ttk.Button(toolbar, text="Start", command=self._start_selected)
        self.btn_start.pack(side="left", padx=2)
        self.btn_stop = ttk.Button(toolbar, text="Stop", command=self._stop_selected)
        self.btn_stop.pack(side="left", padx=2)
        self.btn_restart = ttk.Button(toolbar, text="Restart", command=self._restart_selected)
        self.btn_restart.pack(side="left", padx=2)
        self.btn_open = ttk.Button(toolbar, text="Open Website", command=self._open_selected_website)
        self.btn_open.pack(side="left", padx=2)

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
        self.tree.heading("#0", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("port", text="Port")
        self.tree.heading("workers", text="Workers")
        self.tree.heading("status", text="Status")
        self.tree.heading("autostart", text="Autostart")
        self.tree.heading("directory", text="Directory")
        self.tree.heading("docroot", text="Document root")
        self.tree.heading("router", text="Router script")
        self.tree.heading("cpu", text="CPU")
        self.tree.heading("memory", text="Memory")
        for column_id in ("#0", *columns):
            self.tree.column(column_id, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
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
        self.context_menu.add_command(label="Edit...", command=self._edit_project)
        self.context_menu.add_command(label="Remove...", command=self._remove_project)

    def _on_application_ready(self) -> None:
        notify_desktop_startup_complete()
        self.update_idletasks()
        self._start_tray_icon()
        self._start_control_server()

    def _start_control_server(self) -> None:
        self._control_server = InstanceControlServer(on_show=lambda: self.after(0, self._show_from_tray))
        self._control_server.start()

    def _start_tray_icon(self) -> None:
        tray = TrayIcon(
            icon_path=ICON_FILE,
            tooltip="DevServer Commander",
            on_show=lambda: self.after(0, self._show_from_tray),
            on_exit=lambda: self.after(0, self._quit_application),
        )
        if tray.start():
            self._tray_icon = tray
            return

        self._set_status("System tray unavailable. Install GTK3 bindings to enable tray support.")

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
        has_selection = self._selected_project_name() is not None
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

        if has_selection:
            project = self._get_project(self._selected_project_name() or "")
            can_open = project is not None and project.port is not None
            self.btn_open.configure(state="normal" if can_open else "disabled")

    def _refresh_tree(self) -> None:
        previous_selection = self._selected_project_name()
        self._refreshing_tree = True
        try:
            for item in self.tree.get_children():
                self.tree.delete(item)

            for project in self.projects:
                process = self.processes[project.name]
                running = process.is_running()
                if running:
                    status = "Running (unmanaged)" if process.unmanaged else "Running"
                else:
                    status = "Stopped"
                docroot, router = self._docroot_and_router(project)
                cpu_label, memory_label = self._process_stats(project.name)
                self.tree.insert(
                    "",
                    "end",
                    iid=project.name,
                    text=project.name,
                    values=(
                        server_type_label_for_command(project.command),
                        project.port if project.port is not None else "-",
                        self._workers_label(project),
                        status,
                        "",
                        project.directory,
                        docroot,
                        router,
                        cpu_label,
                        memory_label,
                    ),
                )

            if previous_selection and self.tree.exists(previous_selection):
                self.tree.selection_set(previous_selection)
            else:
                self.tree.selection_remove(self.tree.selection())
        finally:
            self._refreshing_tree = False

        self._resize_tree_columns()
        self._sync_autostart_widgets()
        self._selected_name = self._selected_project_name()
        self._update_action_buttons()

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
        font = self._tree_font()
        centered_columns = {"type", "port", "workers", "status", "autostart", "cpu", "memory"}
        column_headings = {
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

        for column_id, heading in column_headings.items():
            max_width = self._text_width(font, heading)
            if column_id == "#0":
                for item in self.tree.get_children():
                    max_width = max(max_width, self._text_width(font, self.tree.item(item, "text")))
            else:
                for item in self.tree.get_children():
                    values = self.tree.item(item, "values")
                    column_index = list(self.tree["columns"]).index(column_id)
                    if column_index < len(values):
                        max_width = max(max_width, self._text_width(font, str(values[column_index])))

            if column_id == "autostart":
                max_width = max(max_width, TREE_AUTOSTART_MIN_WIDTH)

            width = max_width + TREE_COLUMN_PADDING
            anchor = "center" if column_id in centered_columns else "w"
            self.tree.column(column_id, width=width, minwidth=width, stretch=False, anchor=anchor)

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

        self._resize_tree_columns()
        self.after_idle(self._position_autostart_widgets)

    def _schedule_stats_poll(self) -> None:
        if self._stats_job_id is not None:
            self.after_cancel(self._stats_job_id)

        self._update_server_stats()
        interval_ms = self.app_settings.stats_refresh_interval_seconds * 1000
        self._stats_job_id = self.after(interval_ms, self._schedule_stats_poll)

    def _poll(self) -> None:
        self._refresh_tree()
        self._refresh_log_tail()
        self.after(POLL_INTERVAL_MS, self._poll)

    def _on_tree_focus(self, _event=None) -> None:
        self.tree.focus_set()

    def _on_tree_drag_start(self, event) -> None:
        """
        Initialize a potential drag-and-drop reorder operation.

        :param event: Tkinter mouse event from the tree view
        """
        if self._refreshing_tree:
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
        self.config_manager.save(self.projects)

    def _open_preferences(self) -> None:
        dialog = PreferencesDialog(self, settings=self.app_settings)
        self.wait_window(dialog)
        if dialog.result is None:
            return

        self.app_settings = dialog.result
        self.settings_manager.save(self.app_settings)
        self._schedule_stats_poll()
        self._set_status(
            "Preferences saved. CPU and memory values refresh every "
            f"{self.app_settings.stats_refresh_interval_seconds} seconds."
        )

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


def main() -> int:
    may_continue, instance_guard = enforce_single_instance()
    if not may_continue:
        return 1

    app = MainWindow()
    app._instance_guard = instance_guard
    app.after(100, lambda: maybe_prompt_desktop_setup(app))
    app.mainloop()
    instance_guard.release()
    return 0

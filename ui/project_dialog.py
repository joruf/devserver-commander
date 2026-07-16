"""Modal dialog for adding or editing a ServerProject."""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple

from config.presets import find_preset, preset_labels
from config.validation import make_unique_project_name, make_unique_project_port, validate_server_setup
from models import ServerProject
from services.dev_tools import (
    default_command_for_tool,
    dev_tool_status_text,
    identify_dev_tool_from_command,
    install_dev_tool,
    is_dev_tool_installed,
)
from services.node import (
    NODE_MODES,
    build_node_command,
    default_node_env,
    extract_node_mode_label,
    extract_node_target,
)
from services.php import (
    build_php_builtin_command,
    default_php_binary,
    detect_php_versions,
    extract_docroot_from_command,
    extract_php_binary_from_command,
    extract_router_from_command,
    format_docroot_for_display,
    install_php_version,
)
from services.project_detection import ProjectDetectionResult, detect_project_settings
from services.process import format_launch_command
from services.server_types import detect_server_type, server_type_label
from ui.directory_picker import ask_directory
from ui.window_icon import apply_window_icon

SERVER_TYPES = {
    "PHP built-in server": "php",
    "Node.js": "node",
    "Custom command": "custom",
}

LABEL_COLUMN_MINSIZE = 175


class ProjectDialog(tk.Toplevel):
    """Collects the fields of a ServerProject and returns it via .result."""

    def __init__(
        self,
        parent: tk.Misc,
        project: Optional[ServerProject] = None,
        existing_projects: Optional[List[ServerProject]] = None,
    ) -> None:
        super().__init__(parent)
        self.result: Optional[ServerProject] = None
        self._editing = project is not None
        self._editing_name = project.name if project else None
        self._existing_projects = list(existing_projects or [])
        self._php_versions: List[Tuple[str, str]] = []
        self._updating_command = False
        self._applying_preset = False
        self._auto_detected_config_applied = False

        self.title("Edit Project" if self._editing else "Add Project")
        self.transient(parent)
        self.resizable(False, False)
        apply_window_icon(self)

        self._build_form(project)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._on_escape_pressed)
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _current_server_type(self) -> str:
        return SERVER_TYPES[self.server_type_var.get()]

    def _build_form(self, project: Optional[ServerProject]) -> None:
        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self)
        frame.grid(row=0, column=0, sticky="nsew")

        project_env = dict(project.env) if project else {}
        project_command = project.command if project else ""
        initial_type_key = detect_server_type(project_command) if project else "php"
        initial_type = server_type_label(initial_type_key)
        use_php = initial_type_key == "php"
        use_node = initial_type_key == "node"
        self.show_hidden_var = tk.BooleanVar(value=False)

        row = 0
        if not self._editing:
            self.path_frame = ttk.Frame(frame)
            self.path_frame.grid(row=row, column=0, columnspan=3, sticky="we")
            ttk.Label(self.path_frame, text="Project main path:").grid(row=0, column=0, sticky="w", **pad)
            self.main_path_var = tk.StringVar()
            ttk.Entry(self.path_frame, textvariable=self.main_path_var, width=40).grid(
                row=0, column=1, sticky="we", **pad
            )
            ttk.Button(
                self.path_frame,
                text="Browse...",
                command=self._browse_main_path,
            ).grid(row=0, column=2, **pad)
            ttk.Button(
                self.path_frame,
                text="Auto Detect",
                style="Primary.TButton",
                command=self._detect_from_main_path,
            ).grid(row=0, column=3, **pad)
            self.path_frame.columnconfigure(1, weight=1)

            row += 1
            self.detect_status_var = tk.StringVar(
                value="Select the project main path, then run auto detection."
            )
            ttk.Label(frame, textvariable=self.detect_status_var, foreground="gray").grid(
                row=row,
                column=0,
                columnspan=3,
                sticky="w",
                **pad,
            )
            row += 1

            self.template_frame = ttk.Frame(frame)
            self.template_frame.grid(row=row, column=0, columnspan=3, sticky="we")
            ttk.Label(self.template_frame, text="Template:").grid(row=0, column=0, sticky="w", **pad)
            self.preset_var = tk.StringVar(value="(none)")
            ttk.OptionMenu(
                self.template_frame,
                self.preset_var,
                "(none)",
                *preset_labels(),
                command=self._on_preset_changed,
            ).grid(row=0, column=1, sticky="we", **pad)
            self.template_frame.columnconfigure(1, weight=1)
            row += 1

        self.project_details_frame = ttk.Frame(frame)
        self.project_details_frame.grid(row=row, column=0, columnspan=3, sticky="we")
        details = self.project_details_frame
        details_row = 0

        ttk.Label(details, text="Name:").grid(row=details_row, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar(value=project.name if project else "")
        ttk.Entry(details, textvariable=self.name_var, width=48).grid(row=details_row, column=1, sticky="we", **pad)

        details_row += 1
        ttk.Label(details, text="Directory:").grid(row=details_row, column=0, sticky="w", **pad)
        self.directory_var = tk.StringVar(value=project.directory if project else "")
        ttk.Entry(details, textvariable=self.directory_var, width=40).grid(
            row=details_row, column=1, sticky="we", **pad
        )
        ttk.Button(details, text="Browse...", command=self._browse_directory).grid(row=details_row, column=2, **pad)

        details_row += 1
        ttk.Checkbutton(
            details,
            text="Show hidden files/folders when browsing",
            variable=self.show_hidden_var,
        ).grid(row=details_row, column=1, columnspan=2, sticky="w", **pad)

        details_row += 1
        ttk.Label(details, text="Port:").grid(row=details_row, column=0, sticky="w", **pad)
        self.port_var = tk.StringVar(value=str(project.port) if project and project.port else "")
        ttk.Entry(details, textvariable=self.port_var, width=12).grid(row=details_row, column=1, sticky="w", **pad)

        details_row += 1
        ttk.Label(details, text="Server type:").grid(row=details_row, column=0, sticky="w", **pad)
        self.server_type_var = tk.StringVar(value=initial_type)
        ttk.OptionMenu(
            details,
            self.server_type_var,
            initial_type,
            *SERVER_TYPES.keys(),
            command=self._on_server_type_changed,
        ).grid(row=details_row, column=1, sticky="we", **pad)

        details_row += 1
        self.php_options_frame = ttk.Frame(details)
        self.php_options_frame.grid(row=details_row, column=0, columnspan=3, sticky="we")

        php_row = 0
        ttk.Label(self.php_options_frame, text="PHP version:").grid(row=php_row, column=0, sticky="w", **pad)
        php_frame = ttk.Frame(self.php_options_frame)
        php_frame.grid(row=php_row, column=1, sticky="we", **pad)
        self.php_version_var = tk.StringVar()
        self.php_version_menu = ttk.OptionMenu(php_frame, self.php_version_var, "")
        self.php_version_menu.pack(side="left", fill="x", expand=True)
        ttk.Button(php_frame, text="Refresh", command=self._refresh_php_versions).pack(side="left", padx=(6, 0))
        ttk.Button(php_frame, text="Install...", style="Primary.TButton", command=self._install_php_version).pack(
            side="left", padx=(6, 0)
        )

        php_row += 1
        ttk.Label(self.php_options_frame, text="Document root (-t):").grid(row=php_row, column=0, sticky="w", **pad)
        initial_docroot = (
            format_docroot_for_display(extract_docroot_from_command(project_command))
            if use_php
            else "public/"
        )
        self.docroot_var = tk.StringVar(value=initial_docroot)
        self.docroot_entry = ttk.Entry(self.php_options_frame, textvariable=self.docroot_var, width=40)
        self.docroot_entry.grid(row=php_row, column=1, sticky="we", **pad)
        self.docroot_entry.bind("<FocusOut>", self._on_docroot_focus_out)

        php_row += 1
        ttk.Label(
            self.php_options_frame,
            text="Use / for the working directory, or e.g. public/ for a subfolder.",
            foreground="gray",
        ).grid(row=php_row, column=1, sticky="w", **pad)

        php_row += 1
        ttk.Label(self.php_options_frame, text="Router script:").grid(row=php_row, column=0, sticky="w", **pad)
        self.router_var = tk.StringVar(
            value=extract_router_from_command(project_command) if use_php else ""
        )
        ttk.Entry(self.php_options_frame, textvariable=self.router_var, width=40).grid(
            row=php_row, column=1, sticky="we", **pad
        )

        php_row += 1
        ttk.Label(
            self.php_options_frame,
            text="Optional. Routes all requests through this file, e.g. public/index.php",
            foreground="gray",
        ).grid(row=php_row, column=1, sticky="w", **pad)

        php_row += 1
        self.xdebug_var = tk.BooleanVar(value=project_env.get("XDEBUG_SESSION") == "1")
        ttk.Checkbutton(self.php_options_frame, text="Enable Xdebug (XDEBUG_SESSION=1)", variable=self.xdebug_var).grid(
            row=php_row, column=1, sticky="w", **pad
        )

        php_row += 1
        ttk.Label(self.php_options_frame, text="PHP workers:").grid(row=php_row, column=0, sticky="w", **pad)
        self.workers_var = tk.StringVar(value=project_env.get("PHP_CLI_SERVER_WORKERS", ""))
        ttk.Entry(self.php_options_frame, textvariable=self.workers_var, width=12).grid(
            row=php_row, column=1, sticky="w", **pad
        )
        ttk.Label(
            self.php_options_frame,
            text="0 = disabled. Sets PHP_CLI_SERVER_WORKERS.",
            foreground="gray",
        ).grid(row=php_row, column=2, sticky="w", **pad)

        details_row += 1
        self.node_options_frame = ttk.Frame(details)
        self.node_options_frame.grid(row=details_row, column=0, columnspan=3, sticky="we")

        node_row = 0
        ttk.Label(self.node_options_frame, text="Run mode:").grid(row=node_row, column=0, sticky="w", **pad)
        initial_node_mode = extract_node_mode_label(project_command) if use_node else "npm run"
        self.node_mode_var = tk.StringVar(value=initial_node_mode)
        ttk.OptionMenu(
            self.node_options_frame,
            self.node_mode_var,
            initial_node_mode,
            *NODE_MODES.keys(),
            command=self._on_node_mode_changed,
        ).grid(row=node_row, column=1, sticky="we", **pad)

        node_row += 1
        ttk.Label(self.node_options_frame, text="Script / command:").grid(row=node_row, column=0, sticky="w", **pad)
        self.node_target_var = tk.StringVar(
            value=extract_node_target(project_command) if use_node else "dev"
        )
        ttk.Entry(self.node_options_frame, textvariable=self.node_target_var, width=40).grid(
            row=node_row, column=1, sticky="we", **pad
        )

        node_row += 1
        ttk.Label(
            self.node_options_frame,
            text="npm script name, npx arguments, or node entry file",
            foreground="gray",
        ).grid(row=node_row, column=1, sticky="w", **pad)

        node_row += 1
        self.node_port_env_var = tk.BooleanVar(
            value=project_env.get("PORT") == "{port}" if use_node else True
        )
        ttk.Checkbutton(
            self.node_options_frame,
            text="Set PORT={port} environment variable",
            variable=self.node_port_env_var,
        ).grid(row=node_row, column=1, sticky="w", **pad)

        details_row += 1
        self.custom_command_frame = ttk.Frame(details)
        self.custom_command_frame.grid(row=details_row, column=0, columnspan=3, sticky="we")
        ttk.Label(self.custom_command_frame, text="Custom command:").grid(row=0, column=0, sticky="w", **pad)
        custom_default = project_command if project and not use_php and not use_node else ""
        self.custom_command_var = tk.StringVar(value=custom_default)
        ttk.Entry(self.custom_command_frame, textvariable=self.custom_command_var, width=48).grid(
            row=0, column=1, sticky="we", **pad
        )
        self.dev_tool_frame = ttk.Frame(self.custom_command_frame)
        self.dev_tool_frame.grid(row=0, column=2, sticky="e", **pad)
        self.dev_tool_status_var = tk.StringVar()
        self.dev_tool_status_label = ttk.Label(
            self.dev_tool_frame,
            textvariable=self.dev_tool_status_var,
            foreground="gray",
        )
        self.dev_tool_install_button = ttk.Button(
            self.dev_tool_frame,
            text="Install...",
            style="Primary.TButton",
            command=self._install_dev_tool,
        )
        self.dev_tool_status_label.pack(side="left", padx=(0, 6))
        self.dev_tool_install_button.pack(side="left")
        ttk.Label(
            self.custom_command_frame,
            text="Use {port} as placeholder for the port above.",
            foreground="gray",
        ).grid(row=1, column=1, sticky="w", **pad)

        details_row += 1
        ttk.Label(details, text="Generated command:").grid(row=details_row, column=0, sticky="nw", **pad)
        command_frame = ttk.Frame(details)
        command_frame.grid(row=details_row, column=1, sticky="we", **pad)
        self.command_display = tk.Text(command_frame, width=48, height=3, wrap="word")
        self.command_display.pack(fill="both", expand=True)
        self.command_display.configure(state="disabled")

        details_row += 1
        ttk.Label(
            details,
            text="Preview with port and environment variables as used at launch.",
            foreground="gray",
        ).grid(row=details_row, column=1, sticky="w", **pad)

        details_row += 1
        self.autostart_var = tk.BooleanVar(master=self, value=bool(project.autostart if project else False))
        tk.Checkbutton(
            details,
            text="Autostart with DevServer Commander",
            variable=self.autostart_var,
            anchor="w",
        ).grid(
            row=details_row, column=1, sticky="w", **pad
        )

        details.columnconfigure(0, minsize=LABEL_COLUMN_MINSIZE)
        details.columnconfigure(1, weight=1)

        row += 1
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=row, column=0, columnspan=3, pady=(12, 8))
        self.btn_save = ttk.Button(button_frame, text="Save", style="Primary.TButton", command=self._on_save)
        self.btn_cancel = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        self.btn_cancel.pack(side="left", padx=4)

        frame.columnconfigure(0, minsize=LABEL_COLUMN_MINSIZE)
        frame.columnconfigure(1, weight=1)
        self.php_options_frame.columnconfigure(0, minsize=LABEL_COLUMN_MINSIZE)
        self.php_options_frame.columnconfigure(1, weight=1)
        self.node_options_frame.columnconfigure(0, minsize=LABEL_COLUMN_MINSIZE)
        self.node_options_frame.columnconfigure(1, weight=1)
        self.custom_command_frame.columnconfigure(0, minsize=LABEL_COLUMN_MINSIZE)
        self.custom_command_frame.columnconfigure(1, weight=1)

        for variable in (
            self.docroot_var,
            self.router_var,
            self.port_var,
            self.custom_command_var,
            self.workers_var,
            self.node_target_var,
        ):
            variable.trace_add("write", self._on_command_input_changed)
        self.xdebug_var.trace_add("write", self._on_command_input_changed)
        self.node_port_env_var.trace_add("write", self._on_command_input_changed)

        initial_binary = extract_php_binary_from_command(project_command) if use_php else None
        self._refresh_php_versions(select_binary=initial_binary)
        self._update_server_type_visibility()
        self._update_command_preview()
        self._update_dev_tool_controls()
        if not self._editing:
            self._set_template_visibility(False)
            self.project_details_frame.grid_remove()
            self.btn_save.pack_forget()
        else:
            self.btn_save.pack(side="left", padx=4, before=self.btn_cancel)

    def _set_template_visibility(self, visible: bool) -> None:
        """
        Show or hide the template selection row in add mode.

        :param visible: True to show the template row, False to hide it
        """
        if self._editing:
            return
        if visible:
            self.template_frame.grid()
        else:
            self.template_frame.grid_remove()

    def _browse_main_path(self) -> None:
        """Select a main project path and trigger auto detection."""
        chosen = ask_directory(
            parent=self,
            initialdir=self.main_path_var.get() or ".",
            show_hidden=self.show_hidden_var.get(),
        )
        if not chosen:
            return
        self.main_path_var.set(chosen)
        self._detect_from_main_path()

    def _apply_detected_project_settings(self, detected: ProjectDetectionResult) -> None:
        """
        Apply detected project settings to the add form.

        :param detected: Detected project settings
        """
        self._auto_detected_config_applied = True
        self._set_template_visibility(False)
        self.project_details_frame.grid()
        if not self.btn_save.winfo_ismapped():
            self.btn_save.pack(side="left", padx=4, before=self.btn_cancel)

        self.server_type_var.set(server_type_label(detected.server_type))
        self.directory_var.set(detected.directory)
        if detected.server_type == "php":
            self.docroot_var.set(detected.docroot)
            self.router_var.set(detected.router)
            self.custom_command_var.set("")
        elif detected.server_type == "node":
            node_mode_label = next(
                (label for label, key in NODE_MODES.items() if key == detected.node_mode),
                "npm run",
            )
            self.node_mode_var.set(node_mode_label)
            self.node_target_var.set(detected.node_target)
            self.node_port_env_var.set(detected.use_port_env)
            self.custom_command_var.set("")
        else:
            self.custom_command_var.set(detected.command)
            self.docroot_var.set("public/")
            self.router_var.set("")

        if not self.name_var.get().strip():
            self.name_var.set(
                make_unique_project_name(self._existing_projects, detected.suggested_name)
            )
        if detected.suggested_port is not None and not self.port_var.get().strip():
            self.port_var.set(
                str(make_unique_project_port(self._existing_projects, detected.suggested_port))
            )

        self._update_server_type_visibility()
        self._update_command_preview()
        self._update_dev_tool_controls()
        if detected.validation_error:
            self.detect_status_var.set(
                f"Detected {detected.detected_layout}, but validation failed: {detected.validation_error}"
            )
        else:
            self.detect_status_var.set(
                f"Detected {detected.detected_layout}. Configuration validation passed."
            )

    def _detect_from_main_path(self) -> None:
        """Run automatic project detection for the selected main path."""
        main_path = self.main_path_var.get().strip()
        if not main_path:
            self.detect_status_var.set("Enter a project main path to run auto detection.")
            self._auto_detected_config_applied = False
            self._set_template_visibility(False)
            self.project_details_frame.grid_remove()
            self.btn_save.pack_forget()
            return

        if not Path(main_path).expanduser().is_dir():
            self.detect_status_var.set("The selected main path does not exist.")
            self._auto_detected_config_applied = False
            self._set_template_visibility(False)
            self.project_details_frame.grid_remove()
            self.btn_save.pack_forget()
            return

        detected = detect_project_settings(main_path)
        if detected is None:
            self._auto_detected_config_applied = False
            self.detect_status_var.set(
                "No automatic settings found. Please choose a template."
            )
            self.preset_var.set("(none)")
            self._set_template_visibility(True)
            self._update_preset_visibility("(none)")
            self.directory_var.set(main_path)
            return

        self._apply_detected_project_settings(detected)

    def _clear_form_fields(self) -> None:
        """Reset project form fields after the template selection is cleared."""
        self.name_var.set("")
        self.directory_var.set("")
        self.port_var.set("")
        self.server_type_var.set(server_type_label("php"))
        self.docroot_var.set("public/")
        self.router_var.set("")
        self.xdebug_var.set(False)
        self.workers_var.set("")
        self.node_mode_var.set("npm run")
        self.node_target_var.set("dev")
        self.node_port_env_var.set(True)
        self.custom_command_var.set("")
        self.autostart_var.set(False)
        self._refresh_php_versions()
        self._update_server_type_visibility()
        self._update_command_preview()

    def _update_preset_visibility(self, choice: str) -> None:
        """
        Show or hide the project form based on the selected template.

        :param choice: Selected template label
        """
        has_preset = choice != "(none)"
        if has_preset:
            self.project_details_frame.grid()
            if not self.btn_save.winfo_ismapped():
                self.btn_save.pack(side="left", padx=4, before=self.btn_cancel)
            return

        self.project_details_frame.grid_remove()
        self.btn_save.pack_forget()
        self._clear_form_fields()

    def _on_preset_changed(self, choice: str) -> None:
        if not self._editing:
            self._auto_detected_config_applied = False
            self._update_preset_visibility(choice)

        preset = find_preset(choice)
        if preset is None:
            return

        self._applying_preset = True
        try:
            self.server_type_var.set(server_type_label(preset.server_type))
            if preset.suggested_name and not self.name_var.get().strip():
                self.name_var.set(
                    make_unique_project_name(self._existing_projects, preset.suggested_name)
                )
            if preset.port is not None:
                self.port_var.set(
                    str(make_unique_project_port(self._existing_projects, preset.port))
                )
            if (
                not self._editing
                and self.main_path_var.get().strip()
                and not self.directory_var.get().strip()
            ):
                self.directory_var.set(self.main_path_var.get().strip())
            if preset.directory_hint and not self.directory_var.get().strip():
                self.directory_var.set(preset.directory_hint)

            if preset.server_type == "php":
                self.docroot_var.set(preset.docroot)
                self.router_var.set(preset.router)
            elif preset.server_type == "node":
                self.node_mode_var.set(preset.node_mode)
                self.node_target_var.set(preset.node_target)
                self.node_port_env_var.set(preset.use_port_env)
            else:
                if preset.dev_tool_id:
                    self.custom_command_var.set(default_command_for_tool(preset.dev_tool_id))
                else:
                    self.custom_command_var.set(preset.command)

            self._update_server_type_visibility()
            self._update_command_preview()
            self._update_dev_tool_controls()
        finally:
            self._applying_preset = False

    def _on_command_input_changed(self, *_args) -> None:
        self._update_command_preview()
        self._update_dev_tool_controls()

    def _on_docroot_focus_out(self, _event: tk.Event) -> None:
        """
        Normalize the document root display after editing.

        :param _event: Tk focus-out event
        """
        if self._current_server_type() != "php":
            return

        normalized = format_docroot_for_display(self.docroot_var.get())
        if normalized != self.docroot_var.get():
            self.docroot_var.set(normalized)

    def _sync_php_fields_before_save(self) -> None:
        """
        Synchronize PHP form fields before building the final command.

        This ensures values entered in the dialog are persisted even when the
        document-root entry did not emit a focus-out event before Save.
        """
        if self._current_server_type() != "php":
            return

        # Read directly from the entry widget to avoid stale values while focus
        # is still inside the input field.
        docroot_value = format_docroot_for_display(self.docroot_entry.get())
        if docroot_value != self.docroot_var.get():
            self.docroot_var.set(docroot_value)

        router_value = self.router_var.get().strip()
        if router_value != self.router_var.get():
            self.router_var.set(router_value)

    def _current_dev_tool_id(self) -> Optional[str]:
        if not self._editing:
            preset = find_preset(self.preset_var.get())
            if preset is not None and preset.dev_tool_id:
                return preset.dev_tool_id

        if self._current_server_type() != "custom":
            return None

        return identify_dev_tool_from_command(self.custom_command_var.get())

    def _update_dev_tool_controls(self) -> None:
        tool_id = self._current_dev_tool_id()
        if tool_id is None or self._current_server_type() != "custom":
            self.dev_tool_frame.grid_remove()
            self.dev_tool_status_var.set("")
            return

        self.dev_tool_frame.grid()
        self.dev_tool_status_var.set(dev_tool_status_text(tool_id))

    def _install_dev_tool(self) -> None:
        tool_id = self._current_dev_tool_id()
        if tool_id is None:
            return

        progress = tk.Toplevel(self)
        progress.title("Install Development Tool")
        progress.transient(self)
        progress.resizable(False, False)
        progress.grab_set()
        apply_window_icon(progress)

        pad = {"padx": 12, "pady": 8}
        status_var = tk.StringVar(value=f"Downloading {tool_id}...")
        ttk.Label(progress, textvariable=status_var).pack(**pad)
        progress_bar = ttk.Progressbar(progress, mode="indeterminate", length=280)
        progress_bar.pack(padx=12, pady=(0, 12))
        progress_bar.start(12)

        result: List[Tuple[bool, str]] = []

        def worker() -> None:
            result.append(install_dev_tool(tool_id))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        def finish() -> None:
            progress_bar.stop()
            progress.destroy()

            if not result:
                messagebox.showerror(
                    "Install Development Tool",
                    "Installation did not finish.",
                    parent=self,
                )
                return

            success, message = result[0]
            if success:
                self.custom_command_var.set(default_command_for_tool(tool_id))
                self._update_dev_tool_controls()
                self._update_command_preview()
                messagebox.showinfo("Install Development Tool", message, parent=self)
            else:
                messagebox.showerror("Install Development Tool", message, parent=self)

        def poll() -> None:
            if thread.is_alive():
                self.after(100, poll)
                return
            finish()

        self.after(100, poll)

    def _offer_dev_tool_install(self, tool_id: str) -> bool:
        if is_dev_tool_installed(tool_id):
            return True

        install = messagebox.askyesno(
            "Install Development Tool",
            f"{dev_tool_status_text(tool_id)}\n\nInstall it now?",
            parent=self,
        )
        if not install:
            return False

        success, message = install_dev_tool(tool_id)
        if not success:
            messagebox.showerror("Install Development Tool", message, parent=self)
            return False

        self.custom_command_var.set(default_command_for_tool(tool_id))
        self._update_dev_tool_controls()
        self._update_command_preview()
        messagebox.showinfo("Install Development Tool", message, parent=self)
        return True

    def _on_server_type_changed(self, _choice: str) -> None:
        self._update_server_type_visibility()
        self._update_command_preview()
        self._update_dev_tool_controls()

    def _on_node_mode_changed(self, _choice: str) -> None:
        self._update_command_preview()

    def _update_server_type_visibility(self) -> None:
        server_type = self._current_server_type()
        if server_type == "php":
            self.php_options_frame.grid()
            self.node_options_frame.grid_remove()
            self.custom_command_frame.grid_remove()
            return

        if server_type == "node":
            self.php_options_frame.grid_remove()
            self.node_options_frame.grid()
            self.custom_command_frame.grid_remove()
            return

        self.php_options_frame.grid_remove()
        self.node_options_frame.grid_remove()
        self.custom_command_frame.grid()
        self._update_dev_tool_controls()

    def _refresh_php_version_menu(self) -> None:
        menu = self.php_version_menu["menu"]
        menu.delete(0, "end")
        labels = [label for label, _binary in self._php_versions]
        if not labels:
            labels = ["No PHP found"]
            self.php_version_var.set(labels[0])
            menu.add_command(label=labels[0], command=lambda: self.php_version_var.set(labels[0]))
            return

        for label in labels:
            menu.add_command(label=label, command=self._make_php_version_handler(label))

        current = self.php_version_var.get()
        if current not in labels:
            self.php_version_var.set(labels[0])

    def _make_php_version_handler(self, label: str):
        def handler() -> None:
            self.php_version_var.set(label)
            self._update_command_preview()

        return handler

    def _selected_php_binary(self) -> str:
        selected_label = self.php_version_var.get()
        for label, binary in self._php_versions:
            if label == selected_label:
                return binary
        return default_php_binary(self._php_versions)

    def _refresh_php_versions(self, select_binary: Optional[str] = None) -> None:
        self._php_versions = detect_php_versions()
        if select_binary:
            for label, binary in self._php_versions:
                if binary == select_binary:
                    self.php_version_var.set(label)
                    break
        self._refresh_php_version_menu()
        self._update_command_preview()

    def _selected_node_mode(self) -> str:
        return NODE_MODES[self.node_mode_var.get()]

    def _build_stored_command(self) -> str:
        server_type = self._current_server_type()
        if server_type == "custom":
            return self.custom_command_var.get().strip()

        if server_type == "node":
            return build_node_command(self._selected_node_mode(), self.node_target_var.get())

        return build_php_builtin_command(
            self._selected_php_binary(),
            self.docroot_var.get(),
            self.router_var.get(),
        )

    def _build_preview_env(self) -> Dict[str, str]:
        server_type = self._current_server_type()
        if server_type == "php":
            env: Dict[str, str] = {}
            if self.xdebug_var.get():
                env["XDEBUG_SESSION"] = "1"

            workers = self.workers_var.get().strip()
            if workers.isdigit() and int(workers) > 0:
                env["PHP_CLI_SERVER_WORKERS"] = workers
            return env

        if server_type == "node":
            return default_node_env(self.node_port_env_var.get())

        return {}

    def _build_preview_command(self, stored_command: str) -> str:
        port_raw = self.port_var.get().strip()
        port_placeholder = port_raw if port_raw else "PORT"
        command = stored_command.replace("{port}", port_placeholder)
        env = self._build_preview_env()
        if not env:
            return command

        preview_env = {
            key: value.replace("{port}", port_placeholder)
            for key, value in env.items()
        }
        return format_launch_command(command, preview_env)

    def _update_command_preview(self) -> None:
        if self._updating_command:
            return

        stored_command = self._build_stored_command()
        preview_command = self._build_preview_command(stored_command)

        self.command_display.configure(state="normal")
        self.command_display.delete("1.0", "end")
        self.command_display.insert("1.0", preview_command)
        self.command_display.configure(state="disabled")

    def _install_php_version(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Install PHP Version")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()

        pad = {"padx": 8, "pady": 4}
        ttk.Label(dialog, text="PHP version to install (e.g. 8.4):").grid(
            row=0, column=0, columnspan=2, sticky="w", **pad
        )
        version_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=version_var, width=12).grid(row=1, column=0, sticky="w", **pad)

        def start_install() -> None:
            success, message = install_php_version(version_var.get())
            if success:
                messagebox.showinfo("Install PHP", message, parent=dialog)
                dialog.destroy()
            else:
                messagebox.showerror("Install PHP", message, parent=dialog)

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=1, column=1, sticky="e", **pad)
        ttk.Button(button_frame, text="Install", style="Primary.TButton", command=start_install).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side="left", padx=4)

    def _browse_directory(self) -> None:
        chosen = ask_directory(
            parent=self,
            initialdir=self.directory_var.get() or ".",
            show_hidden=self.show_hidden_var.get(),
        )
        if chosen:
            self.directory_var.set(chosen)

    @staticmethod
    def _read_autostart_value(variable: tk.BooleanVar) -> bool:
        """
        Read the autostart checkbox value as a Python bool.

        :param variable: Tk variable bound to the autostart checkbox
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

    def _build_env(self) -> Optional[Dict[str, str]]:
        server_type = self._current_server_type()
        if server_type == "php":
            workers = self.workers_var.get().strip()
            if workers:
                if not workers.isdigit() or int(workers) < 0:
                    messagebox.showerror(
                        "Invalid PHP Workers",
                        "PHP_CLI_SERVER_WORKERS must be 0 or a positive number.",
                        parent=self,
                    )
                    return None
            return self._build_preview_env()

        if server_type == "node":
            return self._build_preview_env()

        return {}

    def _on_save(self) -> None:
        if (
            not self._editing
            and not self._auto_detected_config_applied
            and self.preset_var.get() == "(none)"
        ):
            messagebox.showerror(
                "Template Required",
                "Please run auto detection or choose a template before saving the project.",
                parent=self,
            )
            return

        self._sync_php_fields_before_save()

        name = self.name_var.get().strip()
        directory = self.directory_var.get().strip()
        command = self._build_stored_command()
        port_raw = self.port_var.get().strip()
        server_type = self._current_server_type()

        if not name:
            messagebox.showerror("Missing Name", "Please enter a project name.", parent=self)
            return
        name = make_unique_project_name(self._existing_projects, name, exclude_name=self._editing_name)
        if not directory:
            messagebox.showerror("Missing Directory", "Please choose a working directory.", parent=self)
            return
        if not command:
            messagebox.showerror("Missing Command", "Please configure a start command.", parent=self)
            return

        port = None
        if port_raw:
            if not port_raw.isdigit() or not (1 <= int(port_raw) <= 65535):
                messagebox.showerror("Invalid Port", "Port must be a number between 1 and 65535.", parent=self)
                return
            port = int(port_raw)
            port = make_unique_project_port(self._existing_projects, port, exclude_name=self._editing_name)
            if port > 65535:
                messagebox.showerror(
                    "No Free Port",
                    "No unused port could be found for this project.",
                    parent=self,
                )
                return
        elif server_type in {"php", "node"}:
            messagebox.showerror(
                "Missing Port",
                "Please enter a port for the development server.",
                parent=self,
            )
            return

        env = self._build_env()
        if env is None:
            return

        setup_error = validate_server_setup(
            server_type=server_type,
            directory=directory,
            command=command,
            php_binary=self._selected_php_binary() if server_type == "php" else "",
            docroot=self.docroot_var.get() if server_type == "php" else "",
            router=self.router_var.get() if server_type == "php" else "",
            node_mode=self._selected_node_mode() if server_type == "node" else "",
            node_target=self.node_target_var.get() if server_type == "node" else "",
        )
        if setup_error:
            tool_id = identify_dev_tool_from_command(command)
            if tool_id is not None and not is_dev_tool_installed(tool_id):
                if not self._offer_dev_tool_install(tool_id):
                    return
                command = self._build_stored_command()
                setup_error = validate_server_setup(
                    server_type=server_type,
                    directory=directory,
                    command=command,
                    php_binary=self._selected_php_binary() if server_type == "php" else "",
                    docroot=self.docroot_var.get() if server_type == "php" else "",
                    router=self.router_var.get() if server_type == "php" else "",
                    node_mode=self._selected_node_mode() if server_type == "node" else "",
                    node_target=self.node_target_var.get() if server_type == "node" else "",
                )
            if setup_error:
                messagebox.showerror("Invalid Configuration", setup_error, parent=self)
                return

        self.update_idletasks()
        self.update()

        self.result = ServerProject(
            name=name,
            directory=directory,
            command=command,
            port=port,
            env=env,
            autostart=self._read_autostart_value(self.autostart_var),
        )
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    def _on_escape_pressed(self, _event=None) -> str:
        """
        Close the dialog without saving when Escape is pressed.

        :param _event: Tkinter key event (unused)
        :return: Event handling stop marker
        """
        self._on_cancel()
        return "break"

#!/usr/bin/env python3
"""Generate README screenshots for DevServer Commander."""

import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.app_settings import AppSettingsManager
from models import ServerProject
from services.dev_tools import default_command_for_tool
from services.process import ServerProcess, log_path_for
from ui.directory_picker import DirectoryPickerDialog
from ui.main_window import MainWindow
from ui.preferences_dialog import PreferencesDialog
from ui.project_dialog import ProjectDialog
from ui.window_icon import apply_window_icon

SCREENSHOT_DIR = PROJECT_ROOT / "docs" / "screenshots"
DOCS_DIR = str(Path.home() / "Documents" if (Path.home() / "Documents").is_dir() else Path.home() / "Dokumente")


def _patch_dialog_blocking() -> None:
    """Disable modal grabs that require a running mainloop during capture."""

    def wait_visibility(self) -> None:
        self.update_idletasks()
        self.update()

    def grab_set(self) -> None:
        return

    tk.Misc.wait_visibility = wait_visibility  # type: ignore[method-assign]
    tk.Misc.grab_set = grab_set  # type: ignore[method-assign]


_patch_dialog_blocking()


def demo_projects() -> list[ServerProject]:
    """Return a representative demo server list for screenshots."""
    common_env = {"XDEBUG_SESSION": "1", "PHP_CLI_SERVER_WORKERS": "6"}
    return [
        ServerProject(
            name="PM-Tool MVC",
            directory=f"{DOCS_DIR}/pmtool",
            command="/usr/bin/php8.2 -S localhost:{port} -t public/ public/router.php",
            port=8001,
            env=dict(common_env),
            autostart=True,
        ),
        ServerProject(
            name="Vite Frontend",
            directory=f"{DOCS_DIR}/frontend",
            command="npx vite --port {port} --host localhost",
            port=5173,
            env={},
            autostart=False,
        ),
        ServerProject(
            name="Mailpit",
            directory=DOCS_DIR,
            command=default_command_for_tool("mailpit"),
            port=8025,
            env={},
            autostart=True,
        ),
        ServerProject(
            name="Python Static",
            directory=f"{DOCS_DIR}/docs-site",
            command="python3 -m http.server {port}",
            port=8080,
            env={},
            autostart=False,
        ),
    ]


class ScreenshotMainWindow(MainWindow):
    """Main window configured for static screenshot capture."""

    def _on_application_ready(self) -> None:
        self.update_idletasks()

    def _autostart_projects(self) -> None:
        return

    def _poll(self) -> None:
        return

    def _schedule_stats_poll(self) -> None:
        return


def capture_window(widget: tk.Misc, output_path: Path) -> None:
    """
    Capture a Tk window to a PNG file.

    :param widget: Tk widget whose top-level window should be captured
    :param output_path: Destination PNG path
    """
    top = widget.winfo_toplevel()
    top.update_idletasks()
    top.update()
    top.deiconify()
    top.lift()
    top.attributes("-topmost", True)
    top.update_idletasks()
    top.update()

    window_id = top.winfo_id()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["import", "-window", str(window_id), str(output_path)],
        check=True,
        timeout=15,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    top.attributes("-topmost", False)


def apply_demo_main_window_state(app: ScreenshotMainWindow) -> None:
    """Populate the main window with demo list, status, and log output."""
    app.projects = demo_projects()
    app.processes = {project.name: ServerProcess(project) for project in app.projects}
    app._refresh_tree()

    app.geometry("1200x640")
    for child in app.winfo_children():
        if isinstance(child, ttk.Panedwindow):
            child.sashpos(0, 260)
            break

    app.tree.selection_set("PM-Tool MVC")
    app._selected_name = "PM-Tool MVC"
    app._update_action_buttons()

    values = list(app.tree.item("PM-Tool MVC", "values"))
    values[2] = "Running"
    values[7] = "1.4%"
    values[8] = "52.1 MB"
    app.tree.item("PM-Tool MVC", values=values)

    values = list(app.tree.item("Mailpit", "values"))
    values[2] = "Running"
    values[7] = "0.3%"
    values[8] = "18.6 MB"
    app.tree.item("Mailpit", values=values)

    log_lines = [
        "[Thu Jul  9 18:12:04 2026] PHP 8.2.28 Development Server (http://localhost:8001) started",
        "[Thu Jul  9 18:12:04 2026] Listening on http://127.0.0.1:8001",
        f"[Thu Jul  9 18:12:04 2026] Document root is {DOCS_DIR}/pmtool/public",
        "[Thu Jul  9 18:12:04 2026] Press Ctrl+C to quit.",
        "[Thu Jul  9 18:12:18 2026] 127.0.0.1:52814 Accepted",
        "[Thu Jul  9 18:12:18 2026] 127.0.0.1:52814 [200]: GET /projects",
        "[Thu Jul  9 18:12:18 2026] 127.0.0.1:52814 Closing",
        "[Thu Jul  9 18:12:22 2026] 127.0.0.1:52820 Accepted",
        "[Thu Jul  9 18:12:22 2026] 127.0.0.1:52820 [200]: GET /assets/app.css",
        "[Thu Jul  9 18:12:22 2026] 127.0.0.1:52820 Closing",
    ]
    log_path = log_path_for(app.projects[0])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    app.tree.selection_set("PM-Tool MVC")
    app._on_select()
    app._set_status("2 server(s) running.")
    app.update_idletasks()
    app.update()


def open_project_dialog(
    parent: tk.Misc,
    preset: str = "",
    project: ServerProject | None = None,
) -> ProjectDialog:
    """
    Open a project dialog prepared for screenshot capture.

    :param parent: Parent window
    :param preset: Optional template label to select
    :param project: Optional project for edit mode
    :return: Visible project dialog
    """
    dialog = ProjectDialog(parent, project=project, existing_projects=demo_projects())
    if preset and not project:
        dialog.preset_var.set(preset)
        dialog._on_preset_changed(preset)
    dialog.update_idletasks()
    dialog.update()
    return dialog


def capture_context_menu(app: ScreenshotMainWindow, output_path: Path) -> None:
    """Capture the server list context menu."""
    app.tree.selection_set("PM-Tool MVC")
    app.tree.focus_set()
    app.update_idletasks()
    app.update()

    x = app.tree.winfo_rootx() + 120
    y = app.tree.winfo_rooty() + 36
    app.context_menu.tk_popup(x, y)
    app.update_idletasks()
    app.update()
    time.sleep(0.25)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    subprocess.run(
        ["scrot", "-u", str(output_path)],
        check=True,
        timeout=15,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    app.context_menu.grab_release()


def generate_screenshots(outputs: Iterable[Path] | None = None) -> list[Path]:
    """
    Generate all README screenshots.

    :param outputs: Optional explicit output paths to generate
    :return: List of generated screenshot paths
    """
    handlers = {
        "main-window.png": _capture_main_window,
        "project-dialog-php.png": _capture_project_dialog_php,
        "project-dialog-node.png": _capture_project_dialog_node,
        "project-dialog-mailpit.png": _capture_project_dialog_mailpit,
        "project-dialog-mailhog.png": _capture_project_dialog_mailhog,
        "preferences.png": _capture_preferences,
        "directory-picker.png": _capture_directory_picker,
        "context-menu.png": _capture_context_menu,
    }

    if outputs is not None:
        selected = {path.name: handlers[path.name] for path in outputs if path.name in handlers}
    else:
        selected = handlers

    generated: list[Path] = []
    for filename, handler in selected.items():
        output_path = SCREENSHOT_DIR / filename
        handler(output_path)
        generated.append(output_path)
        print(f"Wrote {output_path}")

    return generated


def _hidden_parent() -> tk.Tk:
    parent = tk.Tk()
    parent.withdraw()
    apply_window_icon(parent)
    return parent


def _capture_main_window(output_path: Path) -> None:
    app = ScreenshotMainWindow()
    apply_demo_main_window_state(app)
    capture_window(app, output_path)
    app.destroy()


def _capture_project_dialog_php(output_path: Path) -> None:
    parent = _hidden_parent()
    try:
        dialog = open_project_dialog(parent, preset="PHP MVC (router)")
        capture_window(dialog, output_path)
        dialog.destroy()
    finally:
        parent.destroy()


def _capture_project_dialog_node(output_path: Path) -> None:
    parent = _hidden_parent()
    try:
        dialog = open_project_dialog(parent, preset="Node.js (npm run dev)")
        capture_window(dialog, output_path)
        dialog.destroy()
    finally:
        parent.destroy()


def _capture_project_dialog_mailpit(output_path: Path) -> None:
    parent = _hidden_parent()
    try:
        dialog = open_project_dialog(parent, preset="Mailpit")
        capture_window(dialog, output_path)
        dialog.destroy()
    finally:
        parent.destroy()


def _capture_project_dialog_mailhog(output_path: Path) -> None:
    parent = _hidden_parent()
    try:
        dialog = open_project_dialog(parent, preset="MailHog")
        capture_window(dialog, output_path)
        dialog.destroy()
    finally:
        parent.destroy()


def _capture_preferences(output_path: Path) -> None:
    parent = _hidden_parent()
    try:
        settings = AppSettingsManager().load()
        dialog = PreferencesDialog(parent, settings)
        capture_window(dialog, output_path)
        dialog.destroy()
    finally:
        parent.destroy()


def _capture_directory_picker(output_path: Path) -> None:
    parent = _hidden_parent()
    try:
        dialog = DirectoryPickerDialog(parent, initialdir=DOCS_DIR, show_hidden=False)
        capture_window(dialog, output_path)
        dialog.destroy()
    finally:
        parent.destroy()


def _capture_context_menu(output_path: Path) -> None:
    app = ScreenshotMainWindow()
    apply_demo_main_window_state(app)
    capture_context_menu(app, output_path)
    app.destroy()


def main() -> int:
    generate_screenshots()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

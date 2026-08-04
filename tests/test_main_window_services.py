"""UI tests for how service rows behave in the main window.

These tests need a display. They are skipped automatically when Tk cannot open
one, so a headless CI run stays green.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

from models import SystemService
from services.systemd import UnitStatus


def _tk_available() -> bool:
    """
    Check whether a Tk display can be opened in this environment.

    :return: True when Tk windows can be created
    """
    try:
        import tkinter as tk
    except ImportError:
        return False

    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001 - any Tk failure means "no display"
        return False

    root.destroy()
    return True


TK_AVAILABLE = _tk_available()

SERVICE_UNIT = "mariadb.service"
PROJECT_NAME = "Demo App"


@unittest.skipUnless(TK_AVAILABLE, "Tk display is not available")
class ServiceRowTests(unittest.TestCase):
    """Tests for service rows, their actions, and the data directory button."""

    def setUp(self) -> None:
        self.service_active = True
        self._config_dir = tempfile.TemporaryDirectory()
        self.data_directory = Path(self._config_dir.name) / "mysql-data"
        self.data_directory.mkdir()

        config_path = Path(self._config_dir.name) / "servers.json"
        config_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": PROJECT_NAME,
                            "directory": self._config_dir.name,
                            "command": "/usr/bin/php -S localhost:{port} -t .",
                            "port": 8199,
                            "env": {},
                            "autostart": False,
                        }
                    ],
                    "services": [
                        {
                            "name": "MariaDB",
                            "unit": SERVICE_UNIT,
                            "port": 3306,
                            "data_directory": str(self.data_directory),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        from config.manager import ConfigManager
        from ui import main_window as main_window_module

        self._module = main_window_module
        self.window = main_window_module.MainWindow.__new__(main_window_module.MainWindow)
        # Build the window without the tray icon, IPC server and autostart timers.
        import tkinter as tk

        tk.Tk.__init__(self.window)
        self.window.withdraw()
        self.window.config_manager = ConfigManager(config_path)

        from config import AppSettingsManager

        # Point preferences at the temp directory so the user's own settings
        # file is neither read nor written by the test.
        self.window.settings_manager = AppSettingsManager(
            Path(self._config_dir.name) / "settings.json"
        )
        self.window.app_settings = self.window.settings_manager.load()
        self.window.projects = self.window.config_manager.load()
        self.window.services = self.window.config_manager.load_services()

        from services.process import ServerProcess

        self.window.processes = {
            project.name: ServerProcess(project) for project in self.window.projects
        }
        self.window.service_monitor = _FakeMonitor(self._status_for)
        self.window._pending_service_actions = set()
        self.window._log_offsets = {}
        self.window._selected_name = None
        self.window._refreshing_tree = False
        self.window._log_follow_tail = True
        self.window._stats_job_id = None
        self.window._tray_icon = None
        self.window._control_server = None
        self.window._exiting = False
        self.window._unsaved_names = set()
        self.window._autostart_vars = {}
        self.window._autostart_checkbuttons = {}
        self.window._syncing_autostart_widgets = False
        self.window._drag_source_name = None
        self.window._drag_start_y = 0
        self.window._drag_active = False
        self.window._drop_indicator_index = None
        self.window._columns_auto_sized = False
        self.window._config_mtime_seen = 0.0
        self.window._last_display_snapshot = None
        self.window._list_poll_job_id = None
        self.window._restart_attempts = {}
        self.window._pending_restart_jobs = {}

        self.window._configure_ui_style()
        self.window._build_menu()
        self.window._build_widgets()
        self.window._build_context_menu()
        self.window._refresh_tree()
        self.window._update_action_buttons()

    def tearDown(self) -> None:
        try:
            # Let queued idle callbacks run, so Tk does not report them as
            # background errors once their widgets are gone.
            self.window.update()
            self.window.destroy()
        except Exception:  # noqa: BLE001 - teardown must not mask test failures
            pass
        self._config_dir.cleanup()

    def _status_for(self, unit: str) -> UnitStatus:
        """Report the fake systemd state the current test wants."""
        return UnitStatus(
            unit=unit,
            load_state="loaded",
            active_state="active" if self.service_active else "inactive",
            sub_state="running" if self.service_active else "dead",
            enabled_state="enabled",
            main_pid=os.getpid() if self.service_active else None,
        )

    @property
    def service_row(self) -> str:
        return f"{self._module.SERVICE_ROW_PREFIX}{SERVICE_UNIT}"

    def _select(self, row_id: str) -> None:
        self.window.tree.selection_set(row_id)
        self.window._on_select()

    def _data_dir_button_visible(self) -> bool:
        return bool(self.window.btn_open_data_dir.winfo_manager())

    def _context_menu_labels(self, row_id: str) -> List[str]:
        self.window._populate_context_menu(row_id)
        menu = self.window.context_menu
        labels = []
        for index in range(menu.index("end") + 1):
            if menu.type(index) == "separator":
                continue
            labels.append(menu.entrycget(index, "label"))
        return labels

    def test_service_row_is_listed(self) -> None:
        self.assertTrue(self.window.tree.exists(self.service_row))

    def test_service_row_shows_systemd_type_and_data_directory(self) -> None:
        values = self.window.tree.item(self.service_row, "values")
        self.assertEqual(values[0], self._module.SERVICE_TYPE_LABEL)
        self.assertEqual(values[1], "3306")
        self.assertEqual(values[3], "Running")
        self.assertEqual(values[5], str(self.data_directory))

    def test_service_row_has_no_autostart_checkbox(self) -> None:
        """Boot behavior belongs to systemd, so the app offers no checkbox."""
        self.assertNotIn(self.service_row, self.window._autostart_checkbuttons)
        self.assertIn(PROJECT_NAME, self.window._autostart_checkbuttons)

    def test_data_directory_button_hidden_without_selection(self) -> None:
        self.window.tree.selection_remove(self.window.tree.selection())
        self.window._on_select()
        self.assertFalse(self._data_dir_button_visible())

    def test_data_directory_button_hidden_for_server_row(self) -> None:
        self._select(PROJECT_NAME)
        self.assertFalse(self._data_dir_button_visible())

    def test_data_directory_button_shown_for_service_row(self) -> None:
        self._select(self.service_row)
        self.assertTrue(self._data_dir_button_visible())
        self.assertEqual(str(self.window.btn_open_data_dir["state"]), "normal")

    def test_data_directory_button_hides_again_when_leaving_service_row(self) -> None:
        self._select(self.service_row)
        self._select(PROJECT_NAME)
        self.assertFalse(self._data_dir_button_visible())

    def test_data_directory_button_disabled_when_directory_is_missing(self) -> None:
        self.window.services = [
            SystemService(
                name="MariaDB",
                unit=SERVICE_UNIT,
                port=3306,
                data_directory="/nonexistent/mysql",
            )
        ]
        self.window._refresh_tree()
        self._select(self.service_row)
        self.assertTrue(self._data_dir_button_visible())
        self.assertEqual(str(self.window.btn_open_data_dir["state"]), "disabled")

    def test_service_cannot_be_edited(self) -> None:
        self._select(self.service_row)
        self.assertEqual(str(self.window.btn_edit["state"]), "disabled")

    def test_service_has_no_website(self) -> None:
        self._select(self.service_row)
        self.assertEqual(str(self.window.btn_open["state"]), "disabled")

    def test_running_service_can_be_stopped_but_not_started(self) -> None:
        self._select(self.service_row)
        self.assertEqual(str(self.window.btn_start["state"]), "disabled")
        self.assertEqual(str(self.window.btn_stop["state"]), "normal")
        self.assertEqual(str(self.window.btn_restart["state"]), "normal")

    def test_stopped_service_can_be_started_but_not_stopped(self) -> None:
        self.service_active = False
        self.window.service_monitor.invalidate()
        self.window._refresh_tree()
        self._select(self.service_row)
        self.assertEqual(str(self.window.btn_start["state"]), "normal")
        self.assertEqual(str(self.window.btn_stop["state"]), "disabled")

    def test_actions_are_blocked_while_an_action_is_pending(self) -> None:
        self.window._pending_service_actions.add(SERVICE_UNIT)
        self._select(self.service_row)
        for button in (self.window.btn_start, self.window.btn_stop, self.window.btn_restart):
            self.assertEqual(str(button["state"]), "disabled")
        self.assertEqual(str(self.window.btn_remove["state"]), "disabled")

    def test_pending_action_is_visible_in_the_status_column(self) -> None:
        self.window._pending_service_actions.add(SERVICE_UNIT)
        self.window._refresh_tree()
        self.assertEqual(self.window.tree.item(self.service_row, "values")[3], "Working...")

    def test_selecting_a_service_shows_its_details(self) -> None:
        self._select(self.service_row)
        text = self.window.log_text.get("1.0", "end")
        self.assertIn(SERVICE_UNIT, text)
        self.assertIn(str(self.data_directory), text)
        self.assertIn("managed by systemd", text)

    def test_service_context_menu_offers_the_data_directory(self) -> None:
        labels = self._context_menu_labels(self.service_row)
        self.assertIn("Open Data Directory", labels)
        self.assertIn("Start Service", labels)
        self.assertIn("Remove...", labels)

    def test_service_context_menu_hides_server_only_actions(self) -> None:
        labels = self._context_menu_labels(self.service_row)
        self.assertNotIn("Open Website", labels)
        self.assertNotIn("Edit...", labels)
        self.assertNotIn("Save to servers.json", labels)

    def test_server_context_menu_has_no_data_directory_entry(self) -> None:
        labels = self._context_menu_labels(PROJECT_NAME)
        self.assertNotIn("Open Data Directory", labels)
        self.assertIn("Open Website", labels)
        self.assertIn("Edit...", labels)

    def test_services_are_not_autostarted_by_the_application(self) -> None:
        """systemd owns the boot behavior, so autostart must ignore services."""
        self.window._autostart_projects()
        self.assertEqual(self.window._pending_service_actions, set())

    def test_removing_a_service_keeps_the_servers(self) -> None:
        self.window.services = []
        self.window._save()
        self.assertEqual(self.window.config_manager.load_services(), [])
        self.assertEqual(
            [project.name for project in self.window.config_manager.load()],
            [PROJECT_NAME],
        )

    def test_toolbar_fits_into_the_window(self) -> None:
        """Every toolbar button must stay reachable at the computed window width."""
        self.window.update_idletasks()
        width = int(self.window.geometry().split("x")[0])
        self.assertGreaterEqual(width, self.window._required_toolbar_width())


class _FakeMonitor:
    """Stands in for ServiceMonitor without calling systemctl."""

    def __init__(self, status_provider) -> None:
        self._status_provider = status_provider

    def status(self, unit: str) -> UnitStatus:
        return self._status_provider(unit)

    def invalidate(self, unit: Optional[str] = None) -> None:
        return None


if __name__ == "__main__":
    unittest.main()

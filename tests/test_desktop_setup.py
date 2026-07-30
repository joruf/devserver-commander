"""Tests for desktop entry generation and login autostart handling."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paths import MAIN_SCRIPT
from ui import desktop_setup


class DesktopEntryContentTests(unittest.TestCase):
    """Tests for the generated .desktop file contents."""

    def test_shortcut_entry_has_no_extra_arguments(self) -> None:
        content = desktop_setup.build_desktop_entry_content()
        exec_lines = [line for line in content.splitlines() if line.startswith("Exec=")]
        self.assertEqual(exec_lines, [f"Exec=python3 {MAIN_SCRIPT}"])

    def test_autostart_entry_launches_into_tray(self) -> None:
        content = desktop_setup.build_autostart_entry_content()
        exec_lines = [line for line in content.splitlines() if line.startswith("Exec=")]
        self.assertEqual(exec_lines, [f"Exec=python3 {MAIN_SCRIPT} --tray"])

    def test_autostart_entry_is_enabled_for_the_session(self) -> None:
        lines = desktop_setup.build_autostart_entry_content().splitlines()
        self.assertIn("X-GNOME-Autostart-enabled=true", lines)
        self.assertIn("Hidden=false", lines)
        self.assertEqual(lines[0], "[Desktop Entry]")

    def test_autostart_entry_does_not_duplicate_autostart_keys(self) -> None:
        lines = desktop_setup.build_autostart_entry_content().splitlines()
        self.assertEqual(len([line for line in lines if line.startswith("Hidden=")]), 1)
        self.assertEqual(
            len([line for line in lines if line.startswith("X-GNOME-Autostart-enabled=")]),
            1,
        )


class LoginAutostartTests(unittest.TestCase):
    """Tests for installing and removing the login autostart entry."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.autostart_file = Path(self._temp_dir.name) / "autostart" / "devserver-commander.desktop"
        patcher = mock.patch.object(desktop_setup, "AUTOSTART_FILE", self.autostart_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._temp_dir.cleanup)

    def test_disabled_when_no_entry_exists(self) -> None:
        self.assertFalse(desktop_setup.is_login_autostart_enabled())

    def test_enable_creates_executable_entry(self) -> None:
        self.assertTrue(desktop_setup.enable_login_autostart())
        self.assertTrue(desktop_setup.is_login_autostart_enabled())
        self.assertIn("--tray", self.autostart_file.read_text(encoding="utf-8"))
        self.assertTrue(os.access(self.autostart_file, os.X_OK))

    def test_disable_removes_entry(self) -> None:
        desktop_setup.enable_login_autostart()
        self.assertTrue(desktop_setup.disable_login_autostart())
        self.assertFalse(desktop_setup.is_login_autostart_enabled())

    def test_disable_is_idempotent(self) -> None:
        self.assertTrue(desktop_setup.disable_login_autostart())

    def test_set_login_autostart_toggles_state(self) -> None:
        desktop_setup.set_login_autostart(True)
        self.assertTrue(desktop_setup.is_login_autostart_enabled())
        desktop_setup.set_login_autostart(False)
        self.assertFalse(desktop_setup.is_login_autostart_enabled())


if __name__ == "__main__":
    unittest.main()

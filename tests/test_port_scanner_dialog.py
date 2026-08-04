"""UI tests for the Service column in the port scanner dialog.

These tests need a display and skip themselves when Tk cannot open one.
"""

import unittest
from typing import List, Optional

from services.port_scan import ScannedPort


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

# A database socket owned by another user: ss reports no process for it.
MYSQL_PORT = ScannedPort(port=3306, address="127.0.0.1", pid=None, process_name=None)
# An ephemeral port of an own process: named by ss, but no well-known service.
EPHEMERAL_PORT = ScannedPort(port=45678, address="127.0.0.1", pid=4321, process_name="code")
# A port both sources know about.
MAILPIT_PORT = ScannedPort(port=8025, address="127.0.0.1", pid=1435, process_name="mailhog")


@unittest.skipUnless(TK_AVAILABLE, "Tk display is not available")
class ServiceColumnTests(unittest.TestCase):
    """Tests that every listed port gets named where a name exists."""

    def setUp(self) -> None:
        import tkinter as tk

        from ui import port_scanner_dialog as dialog_module

        self._module = dialog_module
        self._original_scan = dialog_module.scan_listening_ports
        dialog_module.scan_listening_ports = lambda: list(self.scanned_ports)
        self.scanned_ports: List[ScannedPort] = [MYSQL_PORT, EPHEMERAL_PORT, MAILPIT_PORT]

        self.root = tk.Tk()
        self.root.geometry("200x60")
        # The dialog waits for visibility, so the parent must be mapped first.
        self.root.update()
        self.dialog = dialog_module.PortScannerDialog(
            self.root,
            configured_ports={},
            on_take_over=lambda scanned: None,
        )

    def tearDown(self) -> None:
        self._module.scan_listening_ports = self._original_scan
        try:
            self.root.update()
            self.root.destroy()
        except Exception:  # noqa: BLE001 - teardown must not mask test failures
            pass

    def _row_for_port(self, port: int) -> Optional[tuple]:
        for iid in self.dialog.tree.get_children():
            values = self.dialog.tree.item(iid, "values")
            if str(values[0]) == str(port):
                return values
        return None

    def _select_port(self, port: int) -> None:
        for iid, scanned in self.dialog._ports_by_iid.items():
            if scanned.port == port:
                self.dialog.tree.selection_set(iid)
                self.dialog._on_select()
                return
        self.fail(f"Port {port} is not listed")

    def test_dialog_has_a_service_column(self) -> None:
        self.assertIn("service", self.dialog.tree["columns"])

    def test_every_row_fills_all_columns(self) -> None:
        column_count = len(self.dialog.tree["columns"])
        for iid in self.dialog.tree.get_children():
            with self.subTest(row=iid):
                self.assertEqual(len(self.dialog.tree.item(iid, "values")), column_count)

    def test_names_a_database_port_without_a_visible_process(self) -> None:
        """The original complaint: 3306 showed only a dash."""
        values = self._row_for_port(3306)
        self.assertIsNotNone(values)
        self.assertEqual(values[2], "MySQL / MariaDB")
        self.assertEqual(values[3], "-")

    def test_names_a_known_development_tool_port(self) -> None:
        values = self._row_for_port(8025)
        self.assertEqual(values[2], "MailHog / Mailpit (web UI)")

    def test_leaves_an_ephemeral_port_unnamed(self) -> None:
        """An arbitrary high port has no service name to report honestly."""
        values = self._row_for_port(45678)
        self.assertEqual(values[2], "-")
        self.assertEqual(values[3], "code")

    def test_status_line_explains_a_hidden_process(self) -> None:
        self._select_port(3306)
        status = self.dialog.status_var.get()
        self.assertIn("MySQL / MariaDB", status)
        self.assertIn("root privileges", status)

    def test_status_line_reports_a_visible_process(self) -> None:
        self._select_port(8025)
        status = self.dialog.status_var.get()
        self.assertIn("mailhog", status)
        self.assertIn("1435", status)

    def test_status_line_returns_to_the_summary_without_selection(self) -> None:
        self._select_port(8025)
        self.dialog.tree.selection_remove(self.dialog.tree.selection())
        self.dialog._on_select()
        self.assertIn("unsaved listening port", self.dialog.status_var.get())


if __name__ == "__main__":
    unittest.main()

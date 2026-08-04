"""Tests for systemd unit querying and control helpers."""

import unittest

from services import systemd
from services.systemd import (
    ServiceMonitor,
    UnitStatus,
    build_unit_status,
    needs_authentication,
    parse_show_output,
    run_unit_action,
)


class ShowOutputParsingTests(unittest.TestCase):
    """Tests for parsing ``systemctl show`` output."""

    def test_parses_key_value_lines(self) -> None:
        text = "Id=mariadb.service\nActiveState=active\nMainPID=1538\n"
        self.assertEqual(
            parse_show_output(text),
            {"Id": "mariadb.service", "ActiveState": "active", "MainPID": "1538"},
        )

    def test_keeps_values_containing_equals_signs(self) -> None:
        text = "ExecStart={ path=/usr/sbin/mariadbd ; argv[]=/usr/sbin/mariadbd }\n"
        parsed = parse_show_output(text)
        self.assertEqual(
            parsed["ExecStart"],
            "{ path=/usr/sbin/mariadbd ; argv[]=/usr/sbin/mariadbd }",
        )

    def test_ignores_lines_without_separator(self) -> None:
        self.assertEqual(parse_show_output("garbage\nId=redis.service\n"), {"Id": "redis.service"})

    def test_returns_empty_mapping_for_empty_output(self) -> None:
        self.assertEqual(parse_show_output(""), {})


class UnitStatusBuildingTests(unittest.TestCase):
    """Tests for turning systemctl properties into a UnitStatus."""

    def test_builds_running_status(self) -> None:
        status = build_unit_status(
            "mariadb.service",
            {
                "Id": "mariadb.service",
                "LoadState": "loaded",
                "ActiveState": "active",
                "SubState": "running",
                "UnitFileState": "enabled",
                "MainPID": "1538",
            },
        )
        self.assertTrue(status.exists)
        self.assertTrue(status.is_running)
        self.assertEqual(status.main_pid, 1538)
        self.assertTrue(status.is_enabled_at_boot)
        self.assertEqual(status.status_label(), "Running")

    def test_resolves_alias_to_real_unit_id(self) -> None:
        status = build_unit_status("mysql.service", {"Id": "mariadb.service", "LoadState": "loaded"})
        self.assertEqual(status.unit, "mariadb.service")

    def test_falls_back_to_queried_name_without_id(self) -> None:
        status = build_unit_status("redis.service", {"LoadState": "loaded"})
        self.assertEqual(status.unit, "redis.service")

    def test_treats_zero_main_pid_as_absent(self) -> None:
        status = build_unit_status("mariadb.service", {"MainPID": "0"})
        self.assertIsNone(status.main_pid)

    def test_treats_unparsable_main_pid_as_absent(self) -> None:
        status = build_unit_status("mariadb.service", {"MainPID": "not-a-number"})
        self.assertIsNone(status.main_pid)

    def test_missing_unit_does_not_exist(self) -> None:
        status = build_unit_status("nope.service", {"LoadState": "not-found"})
        self.assertFalse(status.exists)
        self.assertEqual(status.status_label(), "Not installed")


class UnitStatusLabelTests(unittest.TestCase):
    """Tests for the status label shown in the server list."""

    def test_labels_stopped_unit(self) -> None:
        status = UnitStatus(unit="mariadb.service", load_state="loaded", active_state="inactive")
        self.assertEqual(status.status_label(), "Stopped")

    def test_labels_failed_unit(self) -> None:
        status = UnitStatus(unit="mariadb.service", load_state="loaded", active_state="failed")
        self.assertEqual(status.status_label(), "Failed")

    def test_labels_starting_unit(self) -> None:
        status = UnitStatus(unit="mariadb.service", load_state="loaded", active_state="activating")
        self.assertEqual(status.status_label(), "Starting...")
        self.assertTrue(status.is_transitioning)

    def test_labels_stopping_unit(self) -> None:
        status = UnitStatus(unit="mariadb.service", load_state="loaded", active_state="deactivating")
        self.assertEqual(status.status_label(), "Stopping...")

    def test_labels_masked_unit(self) -> None:
        status = UnitStatus(unit="mariadb.service", load_state="masked", active_state="inactive")
        self.assertEqual(status.status_label(), "Masked")
        self.assertTrue(status.is_masked)

    def test_reports_disabled_boot_state(self) -> None:
        status = UnitStatus(unit="mariadb.service", load_state="loaded", enabled_state="disabled")
        self.assertFalse(status.is_enabled_at_boot)

    def test_reports_unknown_boot_state_for_static_units(self) -> None:
        status = UnitStatus(unit="mariadb.service", load_state="loaded", enabled_state="static")
        self.assertIsNone(status.is_enabled_at_boot)


class AuthenticationDetectionTests(unittest.TestCase):
    """Tests for recognizing privilege errors from systemctl."""

    def test_detects_interactive_authentication_message(self) -> None:
        self.assertTrue(
            needs_authentication(
                "Failed to stop mariadb.service: Interactive authentication required."
            )
        )

    def test_detects_access_denied_message(self) -> None:
        self.assertTrue(needs_authentication("Access denied"))

    def test_ignores_unrelated_failure(self) -> None:
        self.assertFalse(needs_authentication("Unit nope.service not found."))


class UnitActionValidationTests(unittest.TestCase):
    """Tests guarding which systemd actions may be requested."""

    def test_rejects_unsupported_action(self) -> None:
        with self.assertRaises(ValueError):
            run_unit_action("enable", "mariadb.service")

    def test_rejects_disable_action(self) -> None:
        """Boot behavior stays with systemd, so disable must never be reachable."""
        with self.assertRaises(ValueError):
            run_unit_action("disable", "mariadb.service")


class ServiceMonitorTests(unittest.TestCase):
    """Tests for the cached unit status lookup."""

    def setUp(self) -> None:
        self.calls = []
        self._original = systemd.unit_status

        def fake_unit_status(unit: str) -> UnitStatus:
            self.calls.append(unit)
            return UnitStatus(unit=unit, load_state="loaded", active_state="active")

        systemd.unit_status = fake_unit_status

    def tearDown(self) -> None:
        systemd.unit_status = self._original

    def test_reuses_cached_status_within_ttl(self) -> None:
        monitor = ServiceMonitor(ttl_seconds=60.0)
        monitor.status("mariadb.service")
        monitor.status("mariadb.service")
        self.assertEqual(self.calls, ["mariadb.service"])

    def test_queries_each_unit_separately(self) -> None:
        monitor = ServiceMonitor(ttl_seconds=60.0)
        monitor.status("mariadb.service")
        monitor.status("redis.service")
        self.assertEqual(self.calls, ["mariadb.service", "redis.service"])

    def test_invalidate_forces_new_lookup(self) -> None:
        monitor = ServiceMonitor(ttl_seconds=60.0)
        monitor.status("mariadb.service")
        monitor.invalidate("mariadb.service")
        monitor.status("mariadb.service")
        self.assertEqual(self.calls, ["mariadb.service", "mariadb.service"])

    def test_invalidate_without_unit_clears_cache(self) -> None:
        monitor = ServiceMonitor(ttl_seconds=60.0)
        monitor.status("mariadb.service")
        monitor.status("redis.service")
        monitor.invalidate()
        monitor.status("mariadb.service")
        self.assertEqual(len(self.calls), 3)

    def test_expired_entry_is_refreshed(self) -> None:
        monitor = ServiceMonitor(ttl_seconds=0.0)
        monitor.status("mariadb.service")
        monitor.status("mariadb.service")
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()

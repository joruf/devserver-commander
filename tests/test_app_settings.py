"""Tests for loading and saving application preferences."""

import json
import tempfile
import unittest
from pathlib import Path

from config.app_settings import (
    DEFAULT_STATS_REFRESH_INTERVAL_SECONDS,
    MAX_STATS_REFRESH_INTERVAL_SECONDS,
    AppSettings,
    AppSettingsManager,
)


class AppSettingsParsingTests(unittest.TestCase):
    """Tests for reading settings from stored JSON."""

    def test_defaults_notify_on_and_restart_off(self) -> None:
        settings = AppSettings()
        self.assertTrue(settings.notify_on_server_crash)
        self.assertFalse(settings.restart_crashed_servers)

    def test_reads_stored_flags(self) -> None:
        settings = AppSettings.from_dict(
            {
                "stats_refresh_interval_seconds": 10,
                "notify_on_server_crash": False,
                "restart_crashed_servers": True,
            }
        )
        self.assertEqual(settings.stats_refresh_interval_seconds, 10)
        self.assertFalse(settings.notify_on_server_crash)
        self.assertTrue(settings.restart_crashed_servers)

    def test_accepts_string_and_number_booleans(self) -> None:
        settings = AppSettings.from_dict(
            {"notify_on_server_crash": "false", "restart_crashed_servers": 1}
        )
        self.assertFalse(settings.notify_on_server_crash)
        self.assertTrue(settings.restart_crashed_servers)

    def test_keeps_defaults_for_unreadable_values(self) -> None:
        settings = AppSettings.from_dict(
            {"stats_refresh_interval_seconds": "abc", "restart_crashed_servers": None}
        )
        self.assertEqual(
            settings.stats_refresh_interval_seconds,
            DEFAULT_STATS_REFRESH_INTERVAL_SECONDS,
        )
        self.assertFalse(settings.restart_crashed_servers)

    def test_clamps_out_of_range_interval(self) -> None:
        settings = AppSettings.from_dict({"stats_refresh_interval_seconds": 9999})
        self.assertEqual(
            settings.stats_refresh_interval_seconds,
            MAX_STATS_REFRESH_INTERVAL_SECONDS,
        )

    def test_settings_missing_from_older_files_use_defaults(self) -> None:
        settings = AppSettings.from_dict({"stats_refresh_interval_seconds": 7})
        self.assertTrue(settings.notify_on_server_crash)
        self.assertFalse(settings.restart_crashed_servers)


class AppSettingsRoundTripTests(unittest.TestCase):
    """Tests for persisting settings to disk."""

    def test_saved_settings_are_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AppSettingsManager(Path(temp_dir) / "nested" / "settings.json")
            manager.save(
                AppSettings(
                    stats_refresh_interval_seconds=12,
                    notify_on_server_crash=False,
                    restart_crashed_servers=True,
                )
            )

            stored = json.loads(manager.path.read_text(encoding="utf-8"))
            self.assertEqual(stored["restart_crashed_servers"], True)
            self.assertEqual(manager.load(), AppSettings(12, False, True))

    def test_missing_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AppSettingsManager(Path(temp_dir) / "settings.json")
            self.assertEqual(manager.load(), AppSettings())


if __name__ == "__main__":
    unittest.main()

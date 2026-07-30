"""Tests for command-line argument parsing."""

import contextlib
import io
import unittest

from services.cli_args import parse_args


class CliArgumentTests(unittest.TestCase):
    """Tests for the supported launch options."""

    def test_defaults_to_visible_window(self) -> None:
        self.assertFalse(parse_args([]).start_in_tray)

    def test_tray_flag_enables_tray_start(self) -> None:
        self.assertTrue(parse_args(["--tray"]).start_in_tray)

    def test_minimized_alias_enables_tray_start(self) -> None:
        self.assertTrue(parse_args(["--minimized"]).start_in_tray)

    def test_hidden_alias_enables_tray_start(self) -> None:
        self.assertTrue(parse_args(["--hidden"]).start_in_tray)

    def test_unknown_argument_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--does-not-exist"])


if __name__ == "__main__":
    unittest.main()

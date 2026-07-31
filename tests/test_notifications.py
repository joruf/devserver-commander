"""Tests for desktop notification dispatching."""

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from services import notifications


class NotificationAvailabilityTests(unittest.TestCase):
    """Tests for detecting notification support."""

    def test_available_when_binary_is_on_path(self) -> None:
        with mock.patch.object(notifications.shutil, "which", return_value="/usr/bin/notify-send"):
            self.assertTrue(notifications.notifications_available())

    def test_unavailable_without_binary(self) -> None:
        with mock.patch.object(notifications.shutil, "which", return_value=None):
            self.assertFalse(notifications.notifications_available())


class SendNotificationTests(unittest.TestCase):
    """Tests for the notify-send invocation."""

    def test_passes_urgency_title_and_message(self) -> None:
        with mock.patch.object(notifications.shutil, "which", return_value="/usr/bin/notify-send"):
            with mock.patch.object(notifications.subprocess, "run") as run:
                self.assertTrue(
                    notifications.send_desktop_notification(
                        "Server stopped",
                        "'PM-Tool' ended with exit code 1.",
                        urgency="critical",
                    )
                )

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/notify-send")
        self.assertEqual(command[-2:], ["Server stopped", "'PM-Tool' ended with exit code 1."])
        self.assertIn("--urgency", command)
        self.assertEqual(command[command.index("--urgency") + 1], "critical")

    def test_skips_icon_that_does_not_exist(self) -> None:
        with mock.patch.object(notifications.shutil, "which", return_value="/usr/bin/notify-send"):
            with mock.patch.object(notifications.subprocess, "run") as run:
                notifications.send_desktop_notification(
                    "Title",
                    "Body",
                    icon=Path("/does/not/exist.png"),
                )

        self.assertNotIn("--icon", run.call_args.args[0])

    def test_returns_false_without_notify_send(self) -> None:
        with mock.patch.object(notifications.shutil, "which", return_value=None):
            with mock.patch.object(notifications.subprocess, "run") as run:
                self.assertFalse(notifications.send_desktop_notification("Title", "Body"))

        run.assert_not_called()

    def test_survives_a_failing_notify_send(self) -> None:
        with mock.patch.object(notifications.shutil, "which", return_value="/usr/bin/notify-send"):
            with mock.patch.object(
                notifications.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="notify-send", timeout=5),
            ):
                self.assertFalse(notifications.send_desktop_notification("Title", "Body"))


if __name__ == "__main__":
    unittest.main()

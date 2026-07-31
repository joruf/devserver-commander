"""Tests for detecting server processes that stop without being asked to."""

import signal
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from models import ServerProject
from services import process as process_module
from services.process import ServerProcess, describe_exit, log_path_for


class ExitDescriptionTests(unittest.TestCase):
    """Tests for turning exit statuses into readable text."""

    def test_describes_regular_exit_code(self) -> None:
        self.assertEqual(describe_exit(3), "ended with exit code 3")

    def test_describes_clean_exit(self) -> None:
        self.assertEqual(describe_exit(0), "ended with exit code 0")

    def test_describes_known_signal(self) -> None:
        self.assertEqual(
            describe_exit(-int(signal.SIGKILL)),
            f"was killed by SIGKILL ({int(signal.SIGKILL)})",
        )

    def test_describes_missing_status(self) -> None:
        self.assertEqual(describe_exit(None), "ended for an unknown reason")


class UnexpectedExitTests(unittest.TestCase):
    """Tests for crash detection on managed processes."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._temp_dir.name)
        patcher = mock.patch.object(process_module, "LOG_DIR", self.log_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._temp_dir.cleanup)

    @staticmethod
    def _project(name: str, command: str) -> ServerProject:
        return ServerProject(name=name, directory="/tmp", command=command)

    def _wait_until_stopped(self, process: ServerProcess, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not process.is_running():
                return
            time.sleep(0.05)
        self.fail("process did not stop within the timeout")

    def test_crash_is_reported_once_with_exit_code(self) -> None:
        process = ServerProcess(self._project("Crasher", 'sh -c "exit 3"'))
        process.start()
        self._wait_until_stopped(process)

        self.assertEqual(process.take_unexpected_exit(), 3)
        self.assertIsNone(process.take_unexpected_exit())

    def test_crash_is_written_to_the_log(self) -> None:
        project = self._project("Logger", 'sh -c "exit 4"')
        process = ServerProcess(project)
        process.start()
        self._wait_until_stopped(process)
        process.take_unexpected_exit()

        log_text = log_path_for(project).read_text(encoding="utf-8")
        self.assertIn("exited unexpectedly: ended with exit code 4", log_text)

    def test_requested_stop_is_not_reported_as_crash(self) -> None:
        process = ServerProcess(self._project("Sleeper", "sleep 30"))
        process.start()
        self.assertTrue(process.is_running())

        process.stop(timeout=2.0)
        self.assertFalse(process.is_running())
        self.assertIsNone(process.take_unexpected_exit())

    def test_restart_is_not_reported_as_crash(self) -> None:
        process = ServerProcess(self._project("Restarter", "sleep 30"))
        process.start()
        process.restart()
        self.addCleanup(process.stop, 2.0)

        self.assertTrue(process.is_running())
        self.assertIsNone(process.take_unexpected_exit())

    def test_uptime_is_tracked_while_running_and_cleared_on_exit(self) -> None:
        process = ServerProcess(self._project("Uptime", 'sh -c "exit 0"'))
        self.assertIsNone(process.uptime_seconds)

        process.start()
        uptime = process.uptime_seconds
        self.assertIsNotNone(uptime)
        self.assertGreaterEqual(uptime, 0.0)

        self._wait_until_stopped(process)
        self.assertIsNone(process.uptime_seconds)

    def test_clean_exit_still_counts_as_unexpected(self) -> None:
        process = ServerProcess(self._project("QuietQuitter", 'sh -c "exit 0"'))
        process.start()
        self._wait_until_stopped(process)

        self.assertEqual(process.take_unexpected_exit(), 0)


if __name__ == "__main__":
    unittest.main()

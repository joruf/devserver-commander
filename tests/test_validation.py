"""Tests for project form validation and PHP document root handling."""

import tempfile
import unittest
from pathlib import Path

from config.validation import (
    make_unique_project_name,
    make_unique_project_port,
    validate_docroot_exists,
    validate_php_setup,
    validate_server_setup,
)
from models import ServerProject
from services.php import (
    WORKING_DIRECTORY_DOCROOT,
    build_php_builtin_command,
    extract_docroot_from_command,
    format_docroot_for_display,
    is_working_directory_docroot,
)


class UniqueProjectPortTests(unittest.TestCase):
    """Tests for automatic duplicate project port resolution."""

    @staticmethod
    def _projects(*ports: int) -> list[ServerProject]:
        return [
            ServerProject(name=f"Project {index}", directory="/tmp", command="echo", port=port)
            for index, port in enumerate(ports, start=1)
        ]

    def test_returns_desired_port_when_available(self) -> None:
        projects = self._projects(8001)
        self.assertEqual(make_unique_project_port(projects, 8002), 8002)

    def test_increments_when_port_exists(self) -> None:
        projects = self._projects(8001)
        self.assertEqual(make_unique_project_port(projects, 8001), 8002)

    def test_skips_multiple_taken_ports(self) -> None:
        projects = self._projects(8001, 8002, 8003)
        self.assertEqual(make_unique_project_port(projects, 8001), 8004)

    def test_keeps_port_when_editing_same_project(self) -> None:
        projects = self._projects(8002)
        self.assertEqual(
            make_unique_project_port(projects, 8002, exclude_name="Project 1"),
            8002,
        )


class UniqueProjectNameTests(unittest.TestCase):
    """Tests for automatic duplicate project name resolution."""

    @staticmethod
    def _projects(*names: str) -> list[ServerProject]:
        return [
            ServerProject(name=name, directory="/tmp", command="echo", port=8000)
            for name in names
        ]

    def test_returns_desired_name_when_available(self) -> None:
        projects = self._projects("My PHP App")
        self.assertEqual(make_unique_project_name(projects, "New App"), "New App")

    def test_appends_two_when_base_name_exists(self) -> None:
        projects = self._projects("My PHP App")
        self.assertEqual(make_unique_project_name(projects, "My PHP App"), "My PHP App2")

    def test_increments_highest_existing_suffix(self) -> None:
        projects = self._projects("My PHP App", "My PHP App2")
        self.assertEqual(make_unique_project_name(projects, "My PHP App"), "My PHP App3")

    def test_increments_suffix_from_desired_numbered_name(self) -> None:
        projects = self._projects("My PHP App2")
        self.assertEqual(make_unique_project_name(projects, "My PHP App2"), "My PHP App3")

    def test_keeps_name_when_editing_same_project(self) -> None:
        projects = self._projects("My PHP App2")
        self.assertEqual(
            make_unique_project_name(projects, "My PHP App2", exclude_name="My PHP App2"),
            "My PHP App2",
        )

    def test_skips_taken_incremented_names(self) -> None:
        projects = self._projects("My PHP App2", "My PHP App3")
        self.assertEqual(make_unique_project_name(projects, "My PHP App2"), "My PHP App4")


class PhpDocrootTests(unittest.TestCase):
    """Tests for PHP document root normalization and extraction."""

    def test_working_directory_markers(self) -> None:
        for value in ("", ".", "./", "/"):
            self.assertTrue(is_working_directory_docroot(value))

    def test_format_docroot_for_display_uses_slash(self) -> None:
        self.assertEqual(format_docroot_for_display(""), WORKING_DIRECTORY_DOCROOT)
        self.assertEqual(format_docroot_for_display("."), WORKING_DIRECTORY_DOCROOT)
        self.assertEqual(format_docroot_for_display("/"), WORKING_DIRECTORY_DOCROOT)
        self.assertEqual(format_docroot_for_display("public/"), "public/")

    def test_build_command_with_slash_docroot(self) -> None:
        command = build_php_builtin_command("/usr/bin/php8.5", "/", "")
        self.assertIn("-t .", command)
        self.assertEqual(extract_docroot_from_command(command), WORKING_DIRECTORY_DOCROOT)

    def test_build_command_with_public_docroot(self) -> None:
        command = build_php_builtin_command("/usr/bin/php8.5", "public/", "public/index.php")
        self.assertIn("-t public/", command)
        self.assertEqual(extract_docroot_from_command(command), "public/")


class ValidationTests(unittest.TestCase):
    """Tests for server configuration validation."""

    def test_slash_docroot_uses_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            (project_dir / "index.php").write_text("<?php echo 'ok';", encoding="utf-8")

            self.assertIsNone(validate_docroot_exists(str(project_dir), "/"))
            self.assertIsNone(
                validate_php_setup(
                    str(project_dir),
                    "/usr/bin/php8.5",
                    "/",
                    "",
                )
            )
            self.assertIsNone(
                validate_server_setup(
                    server_type="php",
                    directory=str(project_dir),
                    command=build_php_builtin_command("/usr/bin/php8.5", "/", ""),
                    php_binary="/usr/bin/php8.5",
                    docroot="/",
                    router="",
                )
            )

    def test_php_setup_without_index_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            error = validate_php_setup(
                temp_dir,
                "/usr/bin/php8.5",
                "/",
                "",
            )
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()

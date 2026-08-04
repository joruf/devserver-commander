"""Tests for the SystemService model and its persistence in the config file."""

import json
import tempfile
import unittest
from pathlib import Path

from config.manager import ConfigManager
from models import ServerProject, SystemService


class SystemServiceModelTests(unittest.TestCase):
    """Tests for serializing and parsing service entries."""

    def test_round_trips_through_dict(self) -> None:
        service = SystemService(
            name="MariaDB",
            unit="mariadb.service",
            port=3306,
            data_directory="/var/lib/mysql",
        )
        self.assertEqual(SystemService.from_dict(service.to_dict()), service)

    def test_parses_entry_without_optional_fields(self) -> None:
        service = SystemService.from_dict({"name": "Redis", "unit": "redis.service"})
        self.assertIsNone(service.port)
        self.assertEqual(service.data_directory, "")

    def test_parses_port_given_as_string(self) -> None:
        service = SystemService.from_dict(
            {"name": "MariaDB", "unit": "mariadb.service", "port": "3306"}
        )
        self.assertEqual(service.port, 3306)

    def test_treats_empty_port_as_unknown(self) -> None:
        service = SystemService.from_dict(
            {"name": "MariaDB", "unit": "mariadb.service", "port": ""}
        )
        self.assertIsNone(service.port)

    def test_rejects_entry_without_unit(self) -> None:
        with self.assertRaises(KeyError):
            SystemService.from_dict({"name": "MariaDB"})

    def test_rejects_blank_unit(self) -> None:
        with self.assertRaises(ValueError):
            SystemService.from_dict({"name": "MariaDB", "unit": "   "})

    def test_has_no_launch_command_or_working_directory(self) -> None:
        """A service is never launched as a child process, so it has no command."""
        fields = set(SystemService(name="MariaDB", unit="mariadb.service").to_dict())
        self.assertEqual(fields, {"name", "unit", "port", "data_directory"})


class ServiceConfigPersistenceTests(unittest.TestCase):
    """Tests for storing services alongside servers in servers.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "servers.json"
        self.manager = ConfigManager(self.path)
        self.projects = [
            ServerProject(
                name="App",
                directory="/tmp",
                command="php -S localhost:{port}",
                port=8001,
            )
        ]
        self.services = [
            SystemService(
                name="MariaDB",
                unit="mariadb.service",
                port=3306,
                data_directory="/var/lib/mysql",
            )
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_saves_and_loads_services(self) -> None:
        self.manager.save(self.projects, self.services)
        self.assertEqual(self.manager.load_services(), self.services)

    def test_server_only_save_preserves_services(self) -> None:
        self.manager.save(self.projects, self.services)
        self.manager.save(self.projects)
        self.assertEqual(self.manager.load_services(), self.services)

    def test_saving_empty_service_list_clears_services(self) -> None:
        self.manager.save(self.projects, self.services)
        self.manager.save(self.projects, [])
        self.assertEqual(self.manager.load_services(), [])

    def test_services_do_not_appear_as_servers(self) -> None:
        self.manager.save(self.projects, self.services)
        self.assertEqual([project.name for project in self.manager.load()], ["App"])

    def test_drops_units_outside_the_catalog(self) -> None:
        self.manager.save(self.projects, self.services)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["services"].append(
            {"name": "SSH", "unit": "sshd.service", "port": 22, "data_directory": "/"}
        )
        self.path.write_text(json.dumps(raw), encoding="utf-8")

        loaded = self.manager.load_services()
        self.assertEqual([service.unit for service in loaded], ["mariadb.service"])

    def test_skips_malformed_service_entries(self) -> None:
        self.path.write_text(
            json.dumps({"servers": [], "services": [{"name": "Broken"}, "not-an-object"]}),
            encoding="utf-8",
        )
        self.assertEqual(self.manager.load_services(), [])

    def test_returns_no_services_for_missing_file(self) -> None:
        self.assertEqual(ConfigManager(self.path).load_services(), [])

    def test_returns_no_services_for_unreadable_json(self) -> None:
        self.path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(self.manager.load_services(), [])

    def test_legacy_config_without_services_key_still_loads(self) -> None:
        self.path.write_text(
            json.dumps({"servers": [project.to_dict() for project in self.projects]}),
            encoding="utf-8",
        )
        self.assertEqual(self.manager.load_services(), [])
        self.assertEqual([project.name for project in self.manager.load()], ["App"])


if __name__ == "__main__":
    unittest.main()

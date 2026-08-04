"""Tests for the curated service catalog and its data directory detection."""

import tempfile
import unittest
from pathlib import Path

from services import service_catalog
from services.service_catalog import (
    SERVICE_CANDIDATES,
    ServiceCandidate,
    detect_available_services,
    detect_service_for_port,
    is_catalog_unit,
    parse_config_value,
    resolve_data_directory,
)
from services.systemd import UnitStatus


class ConfigValueParsingTests(unittest.TestCase):
    """Tests for reading a setting out of an ini-style config file."""

    def test_reads_plain_assignment(self) -> None:
        self.assertEqual(parse_config_value("datadir = /srv/mysql\n", "datadir"), "/srv/mysql")

    def test_reads_assignment_without_spaces(self) -> None:
        self.assertEqual(parse_config_value("datadir=/srv/mysql\n", "datadir"), "/srv/mysql")

    def test_ignores_commented_assignment(self) -> None:
        text = "[mysqld]\n#datadir = /var/lib/mysql\n"
        self.assertIsNone(parse_config_value(text, "datadir"))

    def test_ignores_semicolon_comment(self) -> None:
        self.assertIsNone(parse_config_value(";datadir = /var/lib/mysql\n", "datadir"))

    def test_last_assignment_wins(self) -> None:
        text = "datadir = /first\ndatadir = /second\n"
        self.assertEqual(parse_config_value(text, "datadir"), "/second")

    def test_strips_inline_comment(self) -> None:
        text = "datadir = /srv/mysql  # moved here\n"
        self.assertEqual(parse_config_value(text, "datadir"), "/srv/mysql")

    def test_strips_quotes(self) -> None:
        text = "data_directory = '/var/lib/postgresql/16/main'\n"
        self.assertEqual(
            parse_config_value(text, "data_directory"),
            "/var/lib/postgresql/16/main",
        )

    def test_matches_key_case_insensitively(self) -> None:
        self.assertEqual(parse_config_value("DataDir = /srv/mysql\n", "datadir"), "/srv/mysql")

    def test_does_not_match_similar_key(self) -> None:
        self.assertIsNone(parse_config_value("datadir_backup = /srv/backup\n", "datadir"))

    def test_returns_none_when_key_absent(self) -> None:
        self.assertIsNone(parse_config_value("[mysqld]\nport = 3306\n", "datadir"))


class DataDirectoryResolutionTests(unittest.TestCase):
    """Tests for choosing which data directory to report."""

    def test_prefers_configured_directory_that_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            configured = Path(tmp) / "configured-data"
            configured.mkdir()
            config_file = Path(tmp) / "my.cnf"
            config_file.write_text(f"[mysqld]\ndatadir = {configured}\n", encoding="utf-8")

            candidate = ServiceCandidate(
                unit="mariadb.service",
                display_name="MariaDB",
                port=3306,
                default_data_directory=tmp,
                config_globs=(str(config_file),),
                config_key="datadir",
            )
            self.assertEqual(resolve_data_directory(candidate), str(configured))

    def test_falls_back_to_default_when_nothing_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = ServiceCandidate(
                unit="mariadb.service",
                display_name="MariaDB",
                port=3306,
                default_data_directory=tmp,
                config_globs=(),
                config_key="datadir",
            )
            self.assertEqual(resolve_data_directory(candidate), tmp)

    def test_falls_back_to_default_when_configured_path_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "my.cnf"
            config_file.write_text("datadir = /nonexistent/path\n", encoding="utf-8")

            candidate = ServiceCandidate(
                unit="mariadb.service",
                display_name="MariaDB",
                port=3306,
                default_data_directory=tmp,
                config_globs=(str(config_file),),
                config_key="datadir",
            )
            self.assertEqual(resolve_data_directory(candidate), tmp)

    def test_returns_empty_string_when_nothing_can_be_resolved(self) -> None:
        candidate = ServiceCandidate(
            unit="redis.service",
            display_name="Redis",
            port=6379,
            default_data_directory="/nonexistent/redis",
            config_globs=(),
            config_key="",
        )
        self.assertEqual(resolve_data_directory(candidate), "")

    def test_ignores_unreadable_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = ServiceCandidate(
                unit="mariadb.service",
                display_name="MariaDB",
                port=3306,
                default_data_directory=tmp,
                config_globs=(str(Path(tmp) / "missing" / "*.cnf"),),
                config_key="datadir",
            )
            self.assertEqual(resolve_data_directory(candidate), tmp)


class CatalogGuardTests(unittest.TestCase):
    """Tests that only catalog units are accepted."""

    def test_accepts_known_unit(self) -> None:
        self.assertTrue(is_catalog_unit("mariadb.service"))

    def test_rejects_arbitrary_unit(self) -> None:
        self.assertFalse(is_catalog_unit("sshd.service"))

    def test_rejects_empty_unit(self) -> None:
        self.assertFalse(is_catalog_unit(""))

    def test_catalog_only_contains_database_and_cache_units(self) -> None:
        allowed = {
            "mariadb.service",
            "mysql.service",
            "mysqld.service",
            "postgresql.service",
            "redis-server.service",
            "redis.service",
        }
        self.assertEqual({candidate.unit for candidate in SERVICE_CANDIDATES}, allowed)


class DetectionTests(unittest.TestCase):
    """Tests for collapsing installed units into one entry per service."""

    def setUp(self) -> None:
        self._original_unit_status = service_catalog.unit_status
        self._original_resolve = service_catalog.resolve_data_directory
        service_catalog.resolve_data_directory = lambda candidate: "/var/lib/test"

    def tearDown(self) -> None:
        service_catalog.unit_status = self._original_unit_status
        service_catalog.resolve_data_directory = self._original_resolve

    def _install(self, mapping) -> None:
        """Pretend only the given units exist, mapping each to its resolved id."""

        def fake_unit_status(unit: str) -> UnitStatus:
            resolved = mapping.get(unit)
            if resolved is None:
                return UnitStatus(unit=unit, load_state="not-found")
            return UnitStatus(
                unit=resolved,
                load_state="loaded",
                active_state="active",
                enabled_state="enabled",
            )

        service_catalog.unit_status = fake_unit_status

    def test_collapses_alias_units_into_one_entry(self) -> None:
        self._install(
            {
                "mariadb.service": "mariadb.service",
                "mysql.service": "mariadb.service",
                "mysqld.service": "mariadb.service",
            }
        )
        detected = detect_available_services()
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].unit, "mariadb.service")
        self.assertEqual(detected[0].candidate.display_name, "MariaDB")

    def test_keeps_real_mysql_naming_when_mysql_is_its_own_unit(self) -> None:
        self._install({"mysql.service": "mysql.service", "mysqld.service": "mysql.service"})
        detected = detect_available_services()
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].unit, "mysql.service")
        self.assertEqual(detected[0].candidate.display_name, "MySQL")

    def test_reports_multiple_distinct_services(self) -> None:
        self._install(
            {
                "mariadb.service": "mariadb.service",
                "postgresql.service": "postgresql.service",
                "redis-server.service": "redis-server.service",
            }
        )
        names = [item.candidate.display_name for item in detect_available_services()]
        self.assertEqual(names, ["MariaDB", "PostgreSQL", "Redis"])

    def test_reports_nothing_when_no_unit_is_installed(self) -> None:
        self._install({})
        self.assertEqual(detect_available_services(), [])

    def test_detection_produces_persistable_service(self) -> None:
        self._install({"mariadb.service": "mariadb.service"})
        service = detect_available_services()[0].to_service()
        self.assertEqual(service.name, "MariaDB")
        self.assertEqual(service.unit, "mariadb.service")
        self.assertEqual(service.port, 3306)
        self.assertEqual(service.data_directory, "/var/lib/test")

    def test_finds_the_service_behind_a_scanned_port(self) -> None:
        self._install({"mariadb.service": "mariadb.service"})
        detected = detect_service_for_port(3306)
        self.assertIsNotNone(detected)
        self.assertEqual(detected.unit, "mariadb.service")

    def test_reports_no_service_for_a_development_server_port(self) -> None:
        self._install({"mariadb.service": "mariadb.service"})
        self.assertIsNone(detect_service_for_port(8001))

    def test_reports_no_service_when_the_unit_is_not_installed(self) -> None:
        self._install({})
        self.assertIsNone(detect_service_for_port(3306))

    def test_finds_postgresql_by_its_own_port(self) -> None:
        self._install({"postgresql.service": "postgresql.service"})
        detected = detect_service_for_port(5432)
        self.assertIsNotNone(detected)
        self.assertEqual(detected.candidate.display_name, "PostgreSQL")


if __name__ == "__main__":
    unittest.main()

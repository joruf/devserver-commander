"""Tests for naming the service behind a TCP port."""

import unittest

from services import well_known_ports
from services.well_known_ports import WELL_KNOWN_PORTS, service_name_for_port


class CuratedPortTests(unittest.TestCase):
    """Tests for the curated port table."""

    def test_names_mysql_and_mariadb_together(self) -> None:
        self.assertEqual(service_name_for_port(3306), "MySQL / MariaDB")

    def test_names_postgresql(self) -> None:
        self.assertEqual(service_name_for_port(5432), "PostgreSQL")

    def test_names_redis(self) -> None:
        self.assertEqual(service_name_for_port(6379), "Redis")

    def test_names_microsoft_sql_server(self) -> None:
        self.assertEqual(service_name_for_port(1433), "Microsoft SQL Server")

    def test_curated_table_wins_over_etc_services(self) -> None:
        """/etc/services calls 3306 "mysql"; the readable name must win."""
        self.assertEqual(service_name_for_port(3306), WELL_KNOWN_PORTS[3306])

    def test_names_development_tool_ports_unknown_to_the_system(self) -> None:
        for port in (5173, 8025, 4321, 4200, 11434):
            with self.subTest(port=port):
                self.assertIsNotNone(service_name_for_port(port))

    def test_all_curated_ports_are_valid_tcp_ports(self) -> None:
        for port in WELL_KNOWN_PORTS:
            with self.subTest(port=port):
                self.assertTrue(1 <= port <= 65535)

    def test_no_curated_name_is_empty(self) -> None:
        for port, name in WELL_KNOWN_PORTS.items():
            with self.subTest(port=port):
                self.assertTrue(name.strip())


class SystemPortDatabaseTests(unittest.TestCase):
    """Tests for the /etc/services fallback."""

    def test_falls_back_to_the_system_port_database(self) -> None:
        self.assertNotIn(22, {port for port in WELL_KNOWN_PORTS if port == 21})
        self.assertEqual(service_name_for_port(21), "ftp")

    def test_returns_none_for_an_unassigned_port(self) -> None:
        self.assertIsNone(service_name_for_port(49999))

    def test_handles_out_of_range_port_without_raising(self) -> None:
        self.assertIsNone(service_name_for_port(999999))

    def test_handles_negative_port_without_raising(self) -> None:
        self.assertIsNone(service_name_for_port(-1))

    def test_survives_a_missing_system_port_database(self) -> None:
        original = well_known_ports.socket.getservbyport

        def failing_lookup(port, protocol=None):
            raise OSError("no /etc/services")

        well_known_ports.socket.getservbyport = failing_lookup
        try:
            self.assertIsNone(service_name_for_port(21))
            # Curated entries must keep working without the system database.
            self.assertEqual(service_name_for_port(3306), "MySQL / MariaDB")
        finally:
            well_known_ports.socket.getservbyport = original


if __name__ == "__main__":
    unittest.main()

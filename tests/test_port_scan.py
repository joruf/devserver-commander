"""Tests for TCP port-scanning helpers."""

import unittest

from services.port_scan import ScannedPort, _parse_local_address, _parse_ss_line


class LocalAddressParsingTests(unittest.TestCase):
    """Tests for splitting ``ss`` local-address fields into address/port."""

    def test_parses_ipv4_address(self) -> None:
        self.assertEqual(_parse_local_address("127.0.0.1:4321"), ("127.0.0.1", 4321))

    def test_parses_ipv6_address(self) -> None:
        self.assertEqual(_parse_local_address("[::1]:4321"), ("::1", 4321))

    def test_parses_wildcard_address(self) -> None:
        self.assertEqual(_parse_local_address("0.0.0.0:8001"), ("0.0.0.0", 8001))

    def test_parses_address_with_interface_suffix(self) -> None:
        self.assertEqual(_parse_local_address("127.0.0.53%lo:53"), ("127.0.0.53%lo", 53))

    def test_returns_none_for_missing_port(self) -> None:
        self.assertIsNone(_parse_local_address("127.0.0.1"))


class SsLineParsingTests(unittest.TestCase):
    """Tests for parsing a full ``ss -H -tlnp`` output line."""

    def test_parses_line_with_single_process(self) -> None:
        line = (
            "LISTEN 0      511            127.0.0.1:4321  0.0.0.0:*    "
            'users:(("node",pid=12345,fd=20))'
        )
        self.assertEqual(
            _parse_ss_line(line),
            ScannedPort(port=4321, address="127.0.0.1", pid=12345, process_name="node"),
        )

    def test_parses_line_with_multiple_worker_processes(self) -> None:
        line = (
            "LISTEN 0      4096           127.0.0.1:8002  0.0.0.0:*    "
            'users:(("php8.2",pid=4457,fd=4),("php8.2",pid=4456,fd=4))'
        )
        result = _parse_ss_line(line)
        self.assertEqual(result.pid, 4457)
        self.assertEqual(result.process_name, "php8.2")

    def test_parses_line_without_process_info(self) -> None:
        line = "LISTEN 0      32             192.168.1.10:53 0.0.0.0:*"
        self.assertEqual(
            _parse_ss_line(line),
            ScannedPort(port=53, address="192.168.1.10", pid=None, process_name=None),
        )

    def test_ignores_non_listen_lines(self) -> None:
        line = "ESTAB 0      0             127.0.0.1:4321  127.0.0.1:52344"
        self.assertIsNone(_parse_ss_line(line))

    def test_returns_none_for_malformed_line(self) -> None:
        self.assertIsNone(_parse_ss_line("garbage"))


if __name__ == "__main__":
    unittest.main()

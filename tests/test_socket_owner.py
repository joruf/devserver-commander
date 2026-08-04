"""Tests for reading socket owners out of /proc/net/tcp."""

import unittest

from services.port_scan import parse_proc_net_listen_uids

PROC_NET_TCP_SAMPLE = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:0CEA 00000000:0000 0A 00000000:00000000 00:00000000 00000000   122        0 25803 1 0000000000000000 100 0 0 10 0
   1: 0100007F:1F41 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 41208 1 0000000000000000 100 0 0 10 0
   2: 0100007F:1F42 0100007F:C350 01 00000000:00000000 00:00000000 00000000  1000        0 41209 1 0000000000000000 100 0 0 10 0
"""

PROC_NET_TCP6_SAMPLE = """  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000000000000:1F90 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 30111 1 0000000000000000 100 0 0 10 0
"""


class ProcNetTcpParsingTests(unittest.TestCase):
    """Tests for extracting listening ports and their owning user ids."""

    def test_reads_listening_port_and_owner(self) -> None:
        owners = parse_proc_net_listen_uids(PROC_NET_TCP_SAMPLE)
        self.assertEqual(owners[3306], 122)

    def test_reads_second_listening_socket(self) -> None:
        owners = parse_proc_net_listen_uids(PROC_NET_TCP_SAMPLE)
        self.assertEqual(owners[8001], 1000)

    def test_ignores_established_connections(self) -> None:
        """Only listening sockets matter; 0x1F42 is an established connection."""
        owners = parse_proc_net_listen_uids(PROC_NET_TCP_SAMPLE)
        self.assertNotIn(8002, owners)

    def test_parses_ipv6_table(self) -> None:
        owners = parse_proc_net_listen_uids(PROC_NET_TCP6_SAMPLE)
        self.assertEqual(owners[8080], 0)

    def test_skips_the_header_line(self) -> None:
        owners = parse_proc_net_listen_uids(PROC_NET_TCP_SAMPLE)
        self.assertEqual(sorted(owners), [3306, 8001])

    def test_returns_empty_mapping_for_empty_input(self) -> None:
        self.assertEqual(parse_proc_net_listen_uids(""), {})

    def test_returns_empty_mapping_for_header_only(self) -> None:
        self.assertEqual(parse_proc_net_listen_uids("  sl  local_address\n"), {})

    def test_ignores_malformed_lines(self) -> None:
        text = (
            "header\n"
            "garbage line\n"
            "   0: nocolon 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
            "   122        0 25803 1\n"
        )
        self.assertEqual(parse_proc_net_listen_uids(text), {})

    def test_ignores_unparsable_port_or_uid(self) -> None:
        text = (
            "header\n"
            "   0: 0100007F:ZZZZ 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
            "   122        0 25803 1\n"
            "   1: 0100007F:0CEA 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
            "   notauid        0 25804 1\n"
        )
        self.assertEqual(parse_proc_net_listen_uids(text), {})

    def test_first_socket_wins_for_duplicate_ports(self) -> None:
        text = (
            "header\n"
            "   0: 0100007F:0CEA 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
            "   122        0 25803 1\n"
            "   1: 7F000001:0CEA 00000000:0000 0A 00000000:00000000 00:00000000 00000000"
            "  1000        0 25804 1\n"
        )
        self.assertEqual(parse_proc_net_listen_uids(text), {3306: 122})


if __name__ == "__main__":
    unittest.main()

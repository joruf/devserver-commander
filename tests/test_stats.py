"""Tests for CPU and memory statistics helpers."""

import unittest

from services.stats import _parse_process_total_time


class ProcessStatParsingTests(unittest.TestCase):
    """Tests for parsing `/proc/<pid>/stat` CPU fields."""

    def test_parses_standard_stat_line(self) -> None:
        line = (
            "12345 (php8.2) S 1 2 3 4 5 6 7 8 9 10 100 50 "
            "16 17 18 19 20 21 22 23 24 25 26 27 28 29 30"
        )
        self.assertEqual(_parse_process_total_time(line), 150)

    def test_parses_process_name_with_spaces(self) -> None:
        line = (
            "54321 (node dev server) S 1 2 3 4 5 6 7 8 9 10 220 80 "
            "16 17 18 19 20 21 22 23 24 25 26 27 28 29 30"
        )
        self.assertEqual(_parse_process_total_time(line), 300)

    def test_returns_none_for_invalid_line(self) -> None:
        self.assertIsNone(_parse_process_total_time("invalid"))


if __name__ == "__main__":
    unittest.main()

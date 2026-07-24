"""Tests for the click-to-sort cell key helper."""

import unittest

from ui.tree_sort import sort_key_for_cell


class SortKeyForCellTests(unittest.TestCase):
    """Tests for building sortable keys from displayed table cell text."""

    def test_plain_numbers_sort_numerically(self) -> None:
        keys = [sort_key_for_cell(text) for text in ("2", "10", "1")]
        self.assertEqual(sorted(keys), [sort_key_for_cell("1"), sort_key_for_cell("2"), sort_key_for_cell("10")])

    def test_percentage_values_sort_numerically(self) -> None:
        self.assertLess(sort_key_for_cell("5.0%"), sort_key_for_cell("12.3%"))

    def test_memory_sizes_convert_to_bytes_for_comparison(self) -> None:
        self.assertLess(sort_key_for_cell("900 KB"), sort_key_for_cell("1.0 MB"))
        self.assertLess(sort_key_for_cell("2.0 MB"), sort_key_for_cell("3.0 MB"))

    def test_text_sorts_case_insensitively(self) -> None:
        self.assertEqual(
            sorted(["banana", "Apple", "cherry"], key=sort_key_for_cell),
            ["Apple", "banana", "cherry"],
        )

    def test_dash_and_empty_sort_after_everything_else(self) -> None:
        keys = sorted(["-", "", "Alpha", "42"], key=sort_key_for_cell)
        self.assertEqual(keys[-2:], ["-", ""])

    def test_numeric_and_text_do_not_collide(self) -> None:
        self.assertLess(sort_key_for_cell("42"), sort_key_for_cell("Alpha"))


if __name__ == "__main__":
    unittest.main()

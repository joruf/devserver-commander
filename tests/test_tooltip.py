"""Tests for tooltip placement and lifecycle."""

import unittest

from ui.tooltip import (
    TOOLTIP_CURSOR_OFFSET_X,
    TOOLTIP_CURSOR_OFFSET_Y,
    TOOLTIP_SCREEN_MARGIN,
    tooltip_position,
)

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
TIP_WIDTH = 300
TIP_HEIGHT = 80


class TooltipPositionTests(unittest.TestCase):
    """Tests that a tooltip stays on screen wherever the pointer is."""

    def _position(self, pointer_x: int, pointer_y: int):
        return tooltip_position(
            pointer_x,
            pointer_y,
            TIP_WIDTH,
            TIP_HEIGHT,
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
        )

    def test_places_tooltip_below_right_of_the_pointer(self) -> None:
        x, y = self._position(400, 300)
        self.assertEqual(x, 400 + TOOLTIP_CURSOR_OFFSET_X)
        self.assertEqual(y, 300 + TOOLTIP_CURSOR_OFFSET_Y)

    def test_flips_to_the_left_at_the_right_screen_edge(self) -> None:
        x, _y = self._position(SCREEN_WIDTH - 20, 300)
        self.assertLessEqual(x + TIP_WIDTH, SCREEN_WIDTH - TOOLTIP_SCREEN_MARGIN)

    def test_flips_above_the_pointer_at_the_bottom_screen_edge(self) -> None:
        _x, y = self._position(400, SCREEN_HEIGHT - 10)
        self.assertLessEqual(y + TIP_HEIGHT, SCREEN_HEIGHT)
        self.assertLess(y, SCREEN_HEIGHT - 10)

    def test_never_places_tooltip_off_the_left_edge(self) -> None:
        x, _y = self._position(0, 300)
        self.assertGreaterEqual(x, TOOLTIP_SCREEN_MARGIN)

    def test_never_places_tooltip_above_the_top_edge(self) -> None:
        _x, y = self._position(400, 0)
        self.assertGreaterEqual(y, TOOLTIP_SCREEN_MARGIN)

    def test_stays_on_screen_in_every_corner(self) -> None:
        corners = [
            (0, 0),
            (SCREEN_WIDTH, 0),
            (0, SCREEN_HEIGHT),
            (SCREEN_WIDTH, SCREEN_HEIGHT),
        ]
        for pointer in corners:
            with self.subTest(pointer=pointer):
                x, y = self._position(*pointer)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + TIP_WIDTH, SCREEN_WIDTH)
                self.assertLessEqual(y + TIP_HEIGHT, SCREEN_HEIGHT)

    def test_handles_a_tooltip_wider_than_the_screen(self) -> None:
        x, y = tooltip_position(400, 300, 4000, TIP_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)


if __name__ == "__main__":
    unittest.main()

"""Hover tooltips for toolbar buttons and other widgets.

Tooltips stay readable on disabled widgets too, which is where they help most: a
greyed-out button raises the question why, and the tooltip answers it.
"""

import tkinter as tk
from typing import Optional, Tuple

TOOLTIP_DELAY_MS = 550
TOOLTIP_WRAP_LENGTH = 340
TOOLTIP_CURSOR_OFFSET_X = 12
TOOLTIP_CURSOR_OFFSET_Y = 22
TOOLTIP_SCREEN_MARGIN = 8

TOOLTIP_BACKGROUND = "#27272a"
TOOLTIP_FOREGROUND = "#fafafa"


def tooltip_position(
    pointer_x: int,
    pointer_y: int,
    width: int,
    height: int,
    screen_width: int,
    screen_height: int,
) -> Tuple[int, int]:
    """
    Place a tooltip near the pointer while keeping it fully on screen.

    :param pointer_x: Pointer x position on the virtual screen
    :param pointer_y: Pointer y position on the virtual screen
    :param width: Tooltip width in pixels
    :param height: Tooltip height in pixels
    :param screen_width: Screen width in pixels
    :param screen_height: Screen height in pixels
    :return: Tuple of (x, y) for the tooltip window
    """
    x = pointer_x + TOOLTIP_CURSOR_OFFSET_X
    y = pointer_y + TOOLTIP_CURSOR_OFFSET_Y

    max_x = screen_width - width - TOOLTIP_SCREEN_MARGIN
    if x > max_x:
        # Flip to the left of the pointer instead of hanging off the edge.
        x = min(max_x, pointer_x - width - TOOLTIP_CURSOR_OFFSET_X)

    max_y = screen_height - height - TOOLTIP_SCREEN_MARGIN
    if y > max_y:
        y = pointer_y - height - TOOLTIP_SCREEN_MARGIN

    return max(x, TOOLTIP_SCREEN_MARGIN), max(y, TOOLTIP_SCREEN_MARGIN)


class Tooltip:
    """Shows a short explanation while the pointer rests on a widget."""

    def __init__(
        self,
        widget: tk.Misc,
        text: str,
        delay_ms: int = TOOLTIP_DELAY_MS,
        wrap_length: int = TOOLTIP_WRAP_LENGTH,
    ) -> None:
        """
        :param widget: Widget the tooltip belongs to
        :param text: Explanation shown on hover
        :param delay_ms: How long the pointer must rest before showing
        :param wrap_length: Maximum text width in pixels before wrapping
        """
        self.widget = widget
        self.text = text
        self._delay_ms = delay_ms
        self._wrap_length = wrap_length
        self._window: Optional[tk.Toplevel] = None
        self._pending_job: Optional[str] = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def set_text(self, text: str) -> None:
        """
        Replace the explanation, e.g. when a button changes meaning.

        :param text: New explanation
        """
        self.text = text
        if self._window is not None:
            self.hide()

    def _on_enter(self, _event=None) -> None:
        self._cancel_pending()
        self._pending_job = self.widget.after(self._delay_ms, self.show)

    def _on_leave(self, _event=None) -> None:
        self._cancel_pending()
        self.hide()

    def _on_destroy(self, _event=None) -> None:
        self._cancel_pending()
        self.hide()

    def _cancel_pending(self) -> None:
        if self._pending_job is None:
            return
        try:
            self.widget.after_cancel(self._pending_job)
        except (tk.TclError, ValueError):
            pass
        self._pending_job = None

    def show(self) -> None:
        """Display the tooltip next to the pointer."""
        self._pending_job = None
        if self._window is not None or not self.text:
            return

        try:
            if not self.widget.winfo_exists():
                return
        except tk.TclError:
            return

        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.configure(background=TOOLTIP_BACKGROUND)
        try:
            # Ask the window manager to treat this as a tooltip, not a window.
            window.wm_attributes("-type", "tooltip")
        except tk.TclError:
            pass

        label = tk.Label(
            window,
            text=self.text,
            justify="left",
            background=TOOLTIP_BACKGROUND,
            foreground=TOOLTIP_FOREGROUND,
            wraplength=self._wrap_length,
            padx=8,
            pady=5,
            bd=0,
        )
        label.pack()

        window.update_idletasks()
        x, y = tooltip_position(
            self.widget.winfo_pointerx(),
            self.widget.winfo_pointery(),
            window.winfo_reqwidth(),
            window.winfo_reqheight(),
            self.widget.winfo_screenwidth(),
            self.widget.winfo_screenheight(),
        )
        window.wm_geometry(f"+{x}+{y}")
        self._window = window

    def hide(self) -> None:
        """Remove the tooltip window if it is showing."""
        if self._window is None:
            return

        try:
            self._window.destroy()
        except tk.TclError:
            pass
        self._window = None


def add_tooltip(widget: tk.Misc, text: str) -> Tooltip:
    """
    Attach a tooltip to a widget.

    :param widget: Widget that should explain itself on hover
    :param text: Explanation shown on hover
    :return: The created tooltip, so callers can update its text later
    """
    return Tooltip(widget, text)

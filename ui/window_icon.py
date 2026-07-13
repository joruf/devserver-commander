"""Apply the application window icon on Linux desktops and taskbars."""

import tkinter as tk

from paths import RESOURCES_DIR

ICON_FILE = RESOURCES_DIR / "devserver-commander.png"


def apply_window_icon(window: tk.Misc) -> None:
    """
    Set the window icon shown in the title bar and taskbar.

    :param window: Tk root window or Toplevel dialog
    """
    if not ICON_FILE.is_file():
        return

    try:
        icon = tk.PhotoImage(file=str(ICON_FILE))
    except tk.TclError:
        return

    window.iconphoto(True, icon)
    window._app_icon_image = icon  # keep reference alive

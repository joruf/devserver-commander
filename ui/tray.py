"""System tray integration using GTK3."""

import threading
from pathlib import Path
from typing import Callable, Optional

PROGRAM_NAME = "devserver-commander"
APPLICATION_NAME = "DevServer Commander"


class TrayIcon:
    """GTK3 status icon that keeps the app available from the system tray."""

    def __init__(
        self,
        icon_path: Path,
        tooltip: str,
        on_show: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._icon_path = icon_path
        self._tooltip = tooltip
        self._on_show = on_show
        self._on_exit = on_exit
        self._thread: Optional[threading.Thread] = None
        self._icon = None

    def start(self) -> bool:
        """
        Start the tray icon in a background thread.

        :return: True when GTK3 tray support is available
        """
        try:
            import gi

            gi.require_version("Gtk", "3.0")
        except (ImportError, ValueError):
            return False

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        from gi.repository import Gdk, GLib, Gtk

        # Without this, GTK derives the name from the launch script and the tray
        # icon identifies itself as "run.py" to the desktop environment.
        GLib.set_prgname(PROGRAM_NAME)
        GLib.set_application_name(APPLICATION_NAME)

        try:
            Gdk.notify_startup_complete()
        except (AttributeError, TypeError):
            pass

        icon = Gtk.StatusIcon()
        self._icon = icon
        if self._icon_path.is_file():
            icon.set_from_file(str(self._icon_path))
        icon.set_tooltip_text(self._tooltip)
        icon.connect("activate", self._handle_show)
        icon.connect("popup-menu", self._popup_menu)
        icon.set_visible(True)

        Gtk.main()

    def set_tooltip(self, tooltip: str) -> None:
        """
        Update the tray tooltip, e.g. to show how many servers are running.

        Safe to call from the Tk thread: the change is applied inside the GTK
        main loop.

        :param tooltip: New tooltip text
        :return: None
        """
        if tooltip == self._tooltip:
            return

        self._tooltip = tooltip
        if self._icon is None:
            return

        try:
            from gi.repository import GLib
        except (ImportError, ValueError):
            return

        GLib.idle_add(self._apply_tooltip)

    def _apply_tooltip(self) -> bool:
        if self._icon is not None:
            self._icon.set_tooltip_text(self._tooltip)
        return False

    def _handle_show(self, *_args) -> None:
        self._on_show()

    def _popup_menu(self, _icon, button, activate_time) -> None:
        from gi.repository import Gtk

        menu = Gtk.Menu()

        show_item = Gtk.MenuItem(label="Show DevServer Commander")
        show_item.connect("activate", self._handle_show)
        show_item.show()
        menu.append(show_item)

        menu.append(Gtk.SeparatorMenuItem())

        exit_item = Gtk.MenuItem(label="Exit")
        exit_item.connect("activate", self._handle_exit)
        exit_item.show()
        menu.append(exit_item)

        menu.show()
        menu.popup(None, None, None, None, button, activate_time)

    def _handle_exit(self, *_args) -> None:
        self._on_exit()

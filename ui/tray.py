"""System tray integration using GTK3."""

import threading
from pathlib import Path
from typing import Callable, Optional


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
        from gi.repository import Gdk, Gtk

        try:
            Gdk.notify_startup_complete()
        except (AttributeError, TypeError):
            pass

        icon = Gtk.StatusIcon()
        if self._icon_path.is_file():
            icon.set_from_file(str(self._icon_path))
        icon.set_tooltip_text(self._tooltip)
        icon.connect("activate", self._handle_show)
        icon.connect("popup-menu", self._popup_menu)
        icon.set_visible(True)

        Gtk.main()

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

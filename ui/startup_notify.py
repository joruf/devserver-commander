"""FreeDesktop startup-notification helpers for desktop launchers."""


def notify_desktop_startup_complete() -> None:
    """
    Tell the desktop environment that the application is ready.

    This clears the busy/loading mouse cursor shown by launchers that use
    StartupNotify=true in the .desktop file.
    """
    try:
        import gi

        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
    except (ImportError, ValueError, AttributeError):
        return

    try:
        Gdk.init([])
        Gdk.notify_startup_complete()
    except (TypeError, AttributeError):
        try:
            Gdk.notify_startup_complete()
        except (TypeError, AttributeError):
            pass

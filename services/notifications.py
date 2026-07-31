"""Desktop notifications for events that happen while the window is hidden."""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

NOTIFY_BINARY = "notify-send"
APP_NAME = "DevServer Commander"
NOTIFY_TIMEOUT_SECONDS = 5


def notifications_available() -> bool:
    """
    Check whether desktop notifications can be sent.

    :return: True when the notify-send binary is on PATH
    """
    return shutil.which(NOTIFY_BINARY) is not None


def send_desktop_notification(
    title: str,
    message: str,
    urgency: str = "normal",
    icon: Optional[Path] = None,
) -> bool:
    """
    Send a desktop notification, ignoring failures on systems without support.

    :param title: Notification summary line
    :param message: Notification body text
    :param urgency: Urgency hint passed to notify-send (low, normal, critical)
    :param icon: Optional icon file shown with the notification
    :return: True when the notification was handed over to notify-send
    """
    binary = shutil.which(NOTIFY_BINARY)
    if binary is None:
        return False

    command = [binary, "--app-name", APP_NAME, "--urgency", urgency]
    if icon is not None and icon.is_file():
        command += ["--icon", str(icon)]
    command += [title, message]

    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=NOTIFY_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return True

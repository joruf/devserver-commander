"""Helpers for identifying managed server command types."""

from services.node import is_node_command
from services.php import is_php_builtin_command


def detect_server_type(command: str) -> str:
    """
    Detect the server type for a stored start command.

    :param command: Stored start command
    :return: One of ``php``, ``node``, or ``custom``
    """
    if is_php_builtin_command(command):
        return "php"
    if is_node_command(command):
        return "node"
    return "custom"


def server_type_label(server_type: str) -> str:
    """
    Return the UI label for a server type key.

    :param server_type: Server type key
    :return: Human-readable server type label
    """
    labels = {
        "php": "PHP built-in server",
        "node": "Node.js",
        "custom": "Custom command",
    }
    return labels.get(server_type, "Custom command")


def server_type_short_label(server_type: str) -> str:
    """
    Return a compact server type label for the server list.

    :param server_type: Server type key
    :return: Short label suitable for table columns
    """
    labels = {
        "php": "PHP",
        "node": "Node.js",
        "custom": "Custom",
    }
    return labels.get(server_type, "Custom")


def server_type_label_for_command(command: str) -> str:
    """
    Return the short server type label for a stored start command.

    :param command: Stored start command
    :return: Short label for table columns
    """
    return server_type_short_label(detect_server_type(command))

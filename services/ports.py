"""Low-level TCP port helpers."""

import socket


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    """
    Return True if something is already listening on the given TCP port.

    :param port: TCP port number
    :param host: Host address to probe
    :param timeout: Socket timeout in seconds
    :return: True when the port accepts connections
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False

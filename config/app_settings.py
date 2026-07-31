"""Application-wide user preferences."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from paths import CONFIG_HOME

SETTINGS_DIR = CONFIG_HOME / "devserver-commander"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_STATS_REFRESH_INTERVAL_SECONDS = 5
MIN_STATS_REFRESH_INTERVAL_SECONDS = 1
MAX_STATS_REFRESH_INTERVAL_SECONDS = 300
DEFAULT_NOTIFY_ON_SERVER_CRASH = True
DEFAULT_RESTART_CRASHED_SERVERS = False

# Delay before each automatic restart attempt of a crashed server; the number of
# entries is also the maximum number of attempts before the server is left stopped.
CRASH_RESTART_DELAYS_SECONDS = (2, 5, 15)
# A restarted server that stays up this long is considered healthy again.
CRASH_RESTART_STABLE_SECONDS = 60


def _read_bool(data: Dict[str, Any], key: str, default: bool) -> bool:
    """
    Read a boolean setting, tolerating the string and number forms JSON may carry.

    :param data: Parsed JSON object
    :param key: Setting name to read
    :param default: Value used when the key is missing or unreadable
    :return: Parsed boolean value
    """
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


@dataclass
class AppSettings:
    """Persisted preferences that are not part of the server list."""

    stats_refresh_interval_seconds: int = DEFAULT_STATS_REFRESH_INTERVAL_SECONDS
    notify_on_server_crash: bool = DEFAULT_NOTIFY_ON_SERVER_CRASH
    restart_crashed_servers: bool = DEFAULT_RESTART_CRASHED_SERVERS

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize settings to a plain dict suitable for JSON storage.

        :return: JSON-compatible settings mapping
        """
        return {
            "stats_refresh_interval_seconds": self.stats_refresh_interval_seconds,
            "notify_on_server_crash": self.notify_on_server_crash,
            "restart_crashed_servers": self.restart_crashed_servers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        """
        Build settings from a dict previously produced by to_dict().

        :param data: Parsed JSON object
        :return: Validated application settings
        """
        raw_interval = data.get(
            "stats_refresh_interval_seconds",
            DEFAULT_STATS_REFRESH_INTERVAL_SECONDS,
        )
        try:
            interval = int(raw_interval)
        except (TypeError, ValueError):
            interval = DEFAULT_STATS_REFRESH_INTERVAL_SECONDS

        interval = max(MIN_STATS_REFRESH_INTERVAL_SECONDS, min(interval, MAX_STATS_REFRESH_INTERVAL_SECONDS))
        return cls(
            stats_refresh_interval_seconds=interval,
            notify_on_server_crash=_read_bool(
                data,
                "notify_on_server_crash",
                DEFAULT_NOTIFY_ON_SERVER_CRASH,
            ),
            restart_crashed_servers=_read_bool(
                data,
                "restart_crashed_servers",
                DEFAULT_RESTART_CRASHED_SERVERS,
            ),
        )


class AppSettingsManager:
    """Reads and writes application preferences on disk."""

    def __init__(self, path: Path = SETTINGS_FILE) -> None:
        self.path = path

    def load(self) -> AppSettings:
        """
        Load settings from disk, falling back to defaults when missing.

        :return: Current application settings
        """
        if not self.path.is_file():
            return AppSettings()

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppSettings()

        if not isinstance(raw, dict):
            return AppSettings()

        return AppSettings.from_dict(raw)

    def save(self, settings: AppSettings) -> None:
        """
        Persist the given settings, creating the config directory if needed.

        :param settings: Settings to write
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")

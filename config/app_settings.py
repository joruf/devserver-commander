"""Application-wide user preferences."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

SETTINGS_DIR = Path.home() / ".config" / "devserver-commander"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_STATS_REFRESH_INTERVAL_SECONDS = 5
MIN_STATS_REFRESH_INTERVAL_SECONDS = 1
MAX_STATS_REFRESH_INTERVAL_SECONDS = 300


@dataclass
class AppSettings:
    """Persisted preferences that are not part of the server list."""

    stats_refresh_interval_seconds: int = DEFAULT_STATS_REFRESH_INTERVAL_SECONDS

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize settings to a plain dict suitable for JSON storage.

        :return: JSON-compatible settings mapping
        """
        return {
            "stats_refresh_interval_seconds": self.stats_refresh_interval_seconds,
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
        return cls(stats_refresh_interval_seconds=interval)


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

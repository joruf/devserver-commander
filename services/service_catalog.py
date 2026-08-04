"""Curated catalog of database and cache services projects depend on.

The catalog is intentionally closed. There is no way to type an arbitrary unit
name, because this application is a development-server manager, not a systemd
front end. Only units from this list can be added, and only when they are
actually installed on the machine.
"""

import glob
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import SystemService
from services.systemd import UnitStatus, unit_status

MYSQL_CONFIG_GLOBS = (
    "/etc/mysql/my.cnf",
    "/etc/mysql/mariadb.cnf",
    "/etc/mysql/conf.d/*.cnf",
    "/etc/mysql/mariadb.conf.d/*.cnf",
    "/etc/my.cnf",
    "/etc/my.cnf.d/*.cnf",
)

POSTGRES_CONFIG_GLOBS = (
    "/etc/postgresql/*/*/postgresql.conf",
    "/var/lib/pgsql/data/postgresql.conf",
)

REDIS_CONFIG_GLOBS = (
    "/etc/redis/redis.conf",
    "/etc/redis.conf",
)


@dataclass(frozen=True)
class ServiceCandidate:
    """One catalog entry describing a supported service unit.

    :param unit: systemd unit name to look for
    :param display_name: Name shown in the server list
    :param port: Default TCP port the service listens on
    :param default_data_directory: Fallback data directory for this service
    :param config_globs: Config files that may override the data directory
    :param config_key: Config key holding the data directory
    """

    unit: str
    display_name: str
    port: int
    default_data_directory: str
    config_globs: Tuple[str, ...] = ()
    config_key: str = ""


SERVICE_CANDIDATES: Tuple[ServiceCandidate, ...] = (
    ServiceCandidate(
        unit="mariadb.service",
        display_name="MariaDB",
        port=3306,
        default_data_directory="/var/lib/mysql",
        config_globs=MYSQL_CONFIG_GLOBS,
        config_key="datadir",
    ),
    ServiceCandidate(
        unit="mysql.service",
        display_name="MySQL",
        port=3306,
        default_data_directory="/var/lib/mysql",
        config_globs=MYSQL_CONFIG_GLOBS,
        config_key="datadir",
    ),
    ServiceCandidate(
        unit="mysqld.service",
        display_name="MySQL",
        port=3306,
        default_data_directory="/var/lib/mysql",
        config_globs=MYSQL_CONFIG_GLOBS,
        config_key="datadir",
    ),
    ServiceCandidate(
        unit="postgresql.service",
        display_name="PostgreSQL",
        port=5432,
        default_data_directory="/var/lib/postgresql",
        config_globs=POSTGRES_CONFIG_GLOBS,
        config_key="data_directory",
    ),
    ServiceCandidate(
        unit="redis-server.service",
        display_name="Redis",
        port=6379,
        default_data_directory="/var/lib/redis",
        config_globs=REDIS_CONFIG_GLOBS,
        config_key="dir",
    ),
    ServiceCandidate(
        unit="redis.service",
        display_name="Redis",
        port=6379,
        default_data_directory="/var/lib/redis",
        config_globs=REDIS_CONFIG_GLOBS,
        config_key="dir",
    ),
)


@dataclass(frozen=True)
class DetectedService:
    """A catalog entry that is installed on this machine.

    :param candidate: Matching catalog entry
    :param status: Unit state read from systemd
    :param data_directory: Resolved data directory, empty when not found
    """

    candidate: ServiceCandidate
    status: UnitStatus
    data_directory: str

    @property
    def unit(self) -> str:
        """Return the unit name as resolved by systemd."""
        return self.status.unit or self.candidate.unit

    def to_service(self) -> SystemService:
        """
        Build the persistable service entry for this detection.

        :return: Service entry ready to be stored in the configuration
        """
        return SystemService(
            name=self.candidate.display_name,
            unit=self.unit,
            port=self.candidate.port,
            data_directory=self.data_directory,
        )


def parse_config_value(text: str, key: str) -> Optional[str]:
    """
    Read a ``key = value`` setting from an ini-style configuration file.

    Commented-out lines are ignored, and the last assignment wins, mirroring how
    MySQL and PostgreSQL read their own configuration.

    :param text: Full configuration file contents
    :param key: Setting name to look for
    :return: Assigned value with quotes stripped, or None when unset
    """
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", re.IGNORECASE)
    found: Optional[str] = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue

        match = pattern.match(line)
        if match is None:
            continue

        value = match.group(1).split("#", 1)[0].strip()
        value = value.strip('"').strip("'").strip()
        if value:
            found = value

    return found


def _read_config_value(candidate: ServiceCandidate) -> Optional[str]:
    """
    Search a candidate's configuration files for its data directory setting.

    :param candidate: Catalog entry whose configuration is inspected
    :return: Configured directory path, or None when nothing was found
    """
    if not candidate.config_key:
        return None

    for pattern in candidate.config_globs:
        for path in sorted(glob.glob(pattern)):
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            value = parse_config_value(text, candidate.config_key)
            if value:
                return value

    return None


def resolve_data_directory(candidate: ServiceCandidate) -> str:
    """
    Determine where a service stores its data files.

    The configured value takes precedence over the packaging default. A path is
    only reported when it exists, so the UI never offers to open a directory
    that is not there.

    :param candidate: Catalog entry to resolve
    :return: Existing directory path, or an empty string when undetermined
    """
    configured = _read_config_value(candidate)
    if configured and Path(configured).is_dir():
        return configured

    if candidate.default_data_directory and Path(candidate.default_data_directory).is_dir():
        return candidate.default_data_directory

    return configured or ""


def detect_available_services() -> List[DetectedService]:
    """
    Find catalog services that are installed on this machine.

    Units that are aliases of one another (``mysql.service`` pointing at
    ``mariadb.service``, for example) collapse into a single entry, and the
    metadata of the unit systemd actually resolved to wins.

    :return: Installed services, ordered by display name
    """
    by_resolved_unit: Dict[str, DetectedService] = {}

    for candidate in SERVICE_CANDIDATES:
        status = unit_status(candidate.unit)
        if not status.exists:
            continue

        resolved = status.unit or candidate.unit
        existing = by_resolved_unit.get(resolved)
        if existing is not None and existing.candidate.unit == resolved:
            # An exact match already described this unit; an alias must not override it.
            continue

        by_resolved_unit[resolved] = DetectedService(
            candidate=candidate,
            status=status,
            data_directory=resolve_data_directory(candidate),
        )

    return sorted(by_resolved_unit.values(), key=lambda item: (item.candidate.display_name, item.unit))


def detect_service_for_port(port: int) -> Optional[DetectedService]:
    """
    Find an installed catalog service that listens on the given port.

    Used by the port scanner: a database port must not be taken over as a
    development server, because such an entry could never launch the service.

    :param port: TCP port found listening
    :return: Matching installed service, or None
    """
    for detected in detect_available_services():
        if detected.candidate.port == port:
            return detected
    return None


def is_catalog_unit(unit: str) -> bool:
    """
    Check whether a unit name belongs to the curated catalog.

    Used as a guard so configuration files cannot smuggle in arbitrary units.

    :param unit: Unit name to verify
    :return: True when the unit is part of the catalog
    """
    return any(candidate.unit == unit for candidate in SERVICE_CANDIDATES)

"""
Which state of DevServer Commander is running, derived from the commit history.

Nobody raises this number by hand, so it cannot be forgotten and cannot lie. It
works the same way as in the other projects (Mint Cleaner, Branchly):

    major  raised by hand, and only for a release that genuinely justifies it
    minor  number of commits that added a new module under ui/ or services/
           (``__init__.py`` aside), which is where a new capability lands:
           a dialog, a port scanner, systemd services, notifications
    patch  commits since that last happened
    build  total number of commits

So "0.8.0 (24)" means: the 24th commit, the eighth time a module arrived, no
changes since then. Alongside it stand the short hash of the last commit and
its date, read from the same history, so a number in a bug report can be traced
back to an exact commit.

A new module is the threshold because it is a defensible one. Counting commits
whose title begins with "Add" runs away, because a title style that says "Add"
for a tooltip text as readily as for a new capability makes the second digit
rise every other day until it means nothing. A feature built over several
commits counts once, at the commit that brings its module, and several modules
in one commit count once as well. The anchor is the first commit: the initial
import brought the whole application and counts as the first arrival, so the
first working state is 0.1.x. Renamed modules are not new ones. Everything else
is the third digit, and two digits there are fine.

One source, three routes to it, tried in this order:

    DEVSERVER_COMMANDER_VERSION    a fixed value, for tests and for a one-off run
    git history                    a checkout, which is every development machine
    VERSION file                   an installation without .git, and the
                                   single-file executable, which carries it

The VERSION file is written whenever the history is read, and after every commit
by ``.githooks/post-commit``. It is not checked in: it is derived, and a
checked-in copy would be stale one commit later. The executable never reads git
and never writes the file: its copy was written by ``build-exe.py`` and lives in
a temporary directory.

There is deliberately no invented fallback such as 0.0.0. A made-up number looks
real and sends every bug report in the wrong direction, so an unknown version
says so.

This module deliberately imports nothing from DevServer Commander. The commit
hook runs it on its own, before anything else is importable, and the commands it
runs are fixed, read only, and only ever point at DevServer Commander's own
folder.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: ``True`` inside the single-file executable that ``build-exe.py`` produces.
FROZEN = bool(getattr(sys, "frozen", False))

# The executable unpacks the VERSION file next to its other data.
ROOT = Path(getattr(sys, "_MEIPASS", ".")) if FROZEN else Path(__file__).resolve().parent
VERSION_FILE = ROOT / "VERSION"
ENVIRONMENT_VARIABLE = "DEVSERVER_COMMANDER_VERSION"

UNKNOWN = "unknown"

# Raised by hand. DevServer Commander has not had the release that would justify a 1.
MAJOR = 0

# A new module, in the sense of "a new capability arrived". Package markers are
# not modules of their own.
MODULE_PATHSPECS = ("ui/*.py", "services/*.py", ":(exclude)*/__init__.py")

GIT_TIMEOUT = 10


@dataclass(frozen=True)
class Version:
    """
    The version in its parts.

    Attributes:
        name: The number, for example ``0.8.0``, or ``unknown``.
        build: Total number of commits, empty when not known.
        commit: Short hash of the newest commit, empty when not known.
        date: Day of the newest commit as ``YYYY-MM-DD``, empty when not known.
        marker: Identifies the state of the history the numbers belong to.
    """

    name: str
    build: str = ""
    commit: str = ""
    date: str = ""
    marker: str = ""

    @property
    def is_known(self) -> bool:
        """
        Reports whether any source could say which version this is.

        Returns:
            bool: False for the honest "unknown".
        """
        return self.name != UNKNOWN

    @property
    def label(self) -> str:
        """
        Returns the full form, for the About box and for bug reports.

        Returns:
            str: For example ``0.8.0 (24) · b536519 · 28.09.2026``.
        """
        if not self.is_known:
            return UNKNOWN
        parts = [f"{self.name} ({self.build})" if self.build else self.name]
        if self.commit:
            parts.append(self.commit)
        if self.date:
            parts.append(_day_first(self.date))
        return " · ".join(parts)

    def line(self) -> str:
        """
        Returns the form stored in the VERSION file.

        Returns:
            str: Five fields separated by spaces.
        """
        return " ".join((self.name, self.build, self.commit, self.date, self.marker)).strip()


_cache: Optional[Version] = None


def current(root: Path = ROOT) -> Version:
    """
    Returns the running version, working it out once per process.

    Args:
        root: DevServer Commander's own folder.

    Returns:
        Version: The version, or the honest unknown.
    """
    global _cache
    if _cache is not None and root == ROOT:
        return _cache

    found = _resolve(root)
    if root == ROOT:
        _cache = found
    return found


def name(root: Path = ROOT) -> str:
    """
    Returns the number alone.

    Args:
        root: DevServer Commander's own folder.

    Returns:
        str: For example ``0.8.0``, or ``unknown``.
    """
    return current(root).name


def label(root: Path = ROOT) -> str:
    """
    Returns the full form shown in the About box and by ``--version``.

    Args:
        root: DevServer Commander's own folder.

    Returns:
        str: For example ``0.8.0 (24) · b536519 · 28.09.2026``.
    """
    return current(root).label


def forget() -> None:
    """
    Drops the remembered value. Only tests need this.

    Returns:
        None
    """
    global _cache
    _cache = None


def write_file(root: Path = ROOT) -> Optional[Version]:
    """
    Writes the VERSION file from the history, which is what the commit hook does.

    Args:
        root: DevServer Commander's own folder.

    Returns:
        Version | None: What was written, or None when there is no history.
    """
    found = from_git(root, history_marker(root))
    if found is None:
        return None
    _write(root, found)
    return found


# ---------------------------------------------------------------------- routes


def _resolve(root: Path) -> Version:
    """
    Tries every source in order.

    Args:
        root: DevServer Commander's own folder.

    Returns:
        Version: The first answer any source gave, or unknown.
    """
    fixed = parse(os.environ.get(ENVIRONMENT_VARIABLE, ""))
    if fixed is not None:
        return fixed

    stored = from_file(root)
    if FROZEN or not (root / ".git").exists():
        # No history here, so the file is the only answer there can be.
        return stored or Version(UNKNOWN)

    marker = history_marker(root)
    # The file still describes the current commit, so the history does not have
    # to be read again. This is the normal case on every start.
    if stored is not None and marker and stored.marker == marker:
        return stored

    derived = from_git(root, marker)
    if derived is not None:
        _write(root, derived)
        return derived
    return stored or Version(UNKNOWN)


def parse(line: str, with_marker: bool = False) -> Optional[Version]:
    """
    Reads a stored version back.

    Args:
        line: The stored text, for example ``0.8.0 24 b536519 2026-09-28``.
        with_marker: Whether a fifth field, the marker, is expected.

    Returns:
        Version | None: The version, or None for an empty line.
    """
    parts = line.split()
    if not parts:
        return None
    return Version(
        name=parts[0],
        build=parts[1] if len(parts) > 1 else "",
        commit=parts[2] if len(parts) > 2 else "",
        date=parts[3] if len(parts) > 3 else "",
        marker=parts[4] if with_marker and len(parts) > 4 else "",
    )


def from_file(root: Path) -> Optional[Version]:
    """
    Reads the VERSION file.

    Args:
        root: DevServer Commander's own folder.

    Returns:
        Version | None: What the file says, or None when there is no usable file.
    """
    try:
        text = (root / VERSION_FILE.name).read_text(encoding="utf-8")
    except OSError:
        return None
    return parse(text, with_marker=True)


def from_git(root: Path, marker: str) -> Optional[Version]:
    """
    Derives the version from the commit history.

    Args:
        root: DevServer Commander's own folder.
        marker: Identifies the state of the history the numbers belong to.

    Returns:
        Version | None: The version, or None when there is no readable history.
    """
    history = _git(root, "log", "--reverse", "--format=%H")
    if not history:
        return None

    # Renames are followed, so a module that only moved does not count as new.
    arrivals = set(
        _git(root, "-c", "diff.renames=true", "log", "--diff-filter=A", "--format=%H",
             "--", *MODULE_PATHSPECS).split()
    )

    minor = patch = build = 0
    for commit in history.split():
        build += 1
        if commit in arrivals:
            minor += 1
            patch = 0
        else:
            patch += 1
    if build == 0:
        return None

    head = _git(root, "log", "-1", "--format=%h %cs").split()
    return Version(
        name=f"{MAJOR}.{minor}.{patch}",
        build=str(build),
        commit=head[0] if head else "",
        date=head[1] if len(head) > 1 else "",
        marker=marker,
    )


def history_marker(root: Path) -> str:
    """
    Identifies the state of the history without starting a process.

    An unchanged checkout then answers from the VERSION file alone. The reflog
    grows with every commit and the index is rewritten along with it, so either
    timestamp is enough to notice that the history moved on.

    Args:
        root: DevServer Commander's own folder.

    Returns:
        str: The marker, empty when neither file exists.
    """
    newest = 0
    for candidate in (root / ".git" / "logs" / "HEAD", root / ".git" / "index"):
        try:
            newest = max(newest, int(candidate.stat().st_mtime))
        except OSError:
            continue
    return str(newest) if newest else ""


def _write(root: Path, found: Version) -> None:
    """
    Stores a version in the VERSION file, never failing the caller.

    Args:
        root: DevServer Commander's own folder.
        found: What to store.

    Returns:
        None
    """
    try:
        (root / VERSION_FILE.name).write_text(found.line() + "\n", encoding="utf-8")
    except OSError:
        pass


def _git(root: Path, *args: str) -> str:
    """
    Runs one fixed, read-only git command in DevServer Commander's own folder.

    Args:
        root: DevServer Commander's own folder.
        *args: Arguments after ``git``.

    Returns:
        str: The output, empty when git is missing or the command failed.
    """
    executable = shutil.which("git")
    if executable is None:
        return ""
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    try:
        done = subprocess.run(
            [executable, "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _day_first(date: str) -> str:
    """
    Writes ``YYYY-MM-DD`` the way a German desktop writes dates.

    Args:
        date: The date as git reports it.

    Returns:
        str: ``DD.MM.YYYY``, or the input unchanged when it is not a date.
    """
    parts = date.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return date
    return f"{parts[2]}.{parts[1]}.{parts[0]}"


if __name__ == "__main__":
    # Lets the commit hook, and anybody curious, ask without starting the app.
    if len(sys.argv) > 1 and sys.argv[1] == "--write":
        written = write_file()
        print(written.label if written else UNKNOWN)
    else:
        print(current().label)

"""Command-line argument parsing for DevServer Commander."""

import argparse
from dataclasses import dataclass
from typing import Optional, Sequence

import paths
import version

TRAY_ARGUMENT = "--tray"
TRAY_ARGUMENT_ALIASES = ("--minimized", "--hidden")


@dataclass(frozen=True)
class CliOptions:
    """Parsed command-line options for a single application launch."""

    start_in_tray: bool = False


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser for the application.

    :return: Parser accepting the supported launch options
    """
    parser = argparse.ArgumentParser(
        # The single-file executable is started by its own name, not through run.py.
        prog=paths.executable().name if paths.IS_FROZEN else "run.py",
        description="Start, stop and restart local development servers.",
    )
    parser.add_argument(
        TRAY_ARGUMENT,
        *TRAY_ARGUMENT_ALIASES,
        dest="start_in_tray",
        action="store_true",
        help=(
            "Start without showing the main window; the application only appears "
            "in the system tray. Used by the login autostart entry."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"DevServer Commander {version.label()}",
        help="Print the version derived from the commit history and exit.",
    )
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> CliOptions:
    """
    Parse command-line arguments into launch options.

    :param argv: Argument list without the program name; defaults to sys.argv[1:]
    :return: Parsed launch options
    """
    namespace = build_parser().parse_args(argv)
    return CliOptions(start_in_tray=bool(namespace.start_in_tray))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Entry point for DevServer Commander."""

import sys

import paths

# --- what this application needs ----------------------------------------------------------------
# Checked before anything below is imported. Whatever is missing is installed in a window that
# shows the work as it happens; see bootstrap_ui.py. `--setup` opens that window even when nothing
# is missing, which is how to see what is installed.
from bootstrap_ui import Need, ensure  # noqa: E402

NEEDS = (
    Need(label="GTK 3 bindings for Python", module="gi",
         packages=("python3-gi", "gir1.2-gtk-3.0")),
    Need(label="PolicyKit helper", command="pkexec", packages=("policykit-1",)),
    Need(label="Process tools", command="fuser", packages=("psmisc",), optional=True,
         note="the port occupancy check is unavailable"),
    Need(label="Desktop opener", command="xdg-open", packages=("xdg-utils",), optional=True,
         note="links do not open in the browser"),
)

# The single-file executable carries PyGObject itself; only the external programs are the
# system's business there.
if paths.IS_FROZEN:
    NEEDS = tuple(need for need in NEEDS if need.module != "gi")

# Only when the application is actually being started. Importing this module — which the test
# suite does — should not check anything, let alone put an installer window on screen.
if __name__ == "__main__":
    # Answered before anything else, and before any GUI toolkit is imported, so it also works
    # headless — build-exe.py starts the finished executable this way.
    if "--version" in sys.argv[1:]:
        import version

        print(f"DevServer Commander {version.label()}")
        raise SystemExit(0)

    # Before anything spawns: children of the executable must not inherit its bundled libraries.
    paths.use_system_environment_for_children()
    paths.migrate_legacy_user_data()

    # Taken out of the arguments once it has been read, so the application's own parser does
    # not trip over a flag that was never meant for it.
    _SETUP = "--setup" in sys.argv

    if _SETUP:
        sys.argv.remove("--setup")

    if not ensure("DevServer Commander", NEEDS, force=_SETUP):
        raise SystemExit(1)


from ui.main_window import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

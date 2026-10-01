"""Tests for the single-file executable: its paths, launchers, children and build.

The executable itself is never started here - ``build-exe.py`` does that after
every build.  These tests pretend to be frozen and check that nothing in that
mode reaches for pip, a script or a Python interpreter that is not there, and
that nothing is written into the unpacked files.
"""

import importlib.util
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import bootstrap_ui
import paths
import version
from models import ServerProject
from services import cli_args
from services import process as process_module
from ui import desktop_setup

ROOT = Path(__file__).resolve().parent.parent


def _build_script():
    """Import ``build-exe.py`` (its name is not a module name)."""
    spec = importlib.util.spec_from_file_location("build_exe", str(ROOT / "build-exe.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrozenTestCase(unittest.TestCase):
    """Pretends to run as the executable, unpacked into a temporary directory."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        base = Path(self._temp_dir.name)
        self.bundle = base / "_MEIabc"
        self.bundle.mkdir()
        self.executable = base / "bin" / "devserver-commander-linux-x86_64-0.8.0-build24"
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"binary")
        self.data_dir = base / "data"
        for patcher in (
            mock.patch.object(paths, "IS_FROZEN", True),
            mock.patch.object(paths, "USER_DATA_DIR", self.data_dir),
            mock.patch.object(sys, "executable", str(self.executable)),
            mock.patch.object(sys, "_MEIPASS", str(self.bundle), create=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class ResourceRootTests(unittest.TestCase):
    """Where the read-only files are found."""

    def test_the_executable_finds_its_resources_in_the_unpacked_data(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", "/tmp/_MEIabc", create=True):
            self.assertEqual(paths._project_root(), Path("/tmp/_MEIabc"))

    def test_a_checkout_finds_its_resources_next_to_the_sources(self) -> None:
        self.assertEqual(paths._project_root(), ROOT)
        self.assertEqual(paths.ICON_FILE, ROOT / "resources" / "devserver-commander.png")

    def test_user_data_never_lives_in_the_project_root(self) -> None:
        """The unpacked files are deleted when the executable exits."""
        for user_file in (paths.CONFIG_FILE, paths.INIT_FILE):
            self.assertEqual(user_file.parent, paths.CONFIG_HOME / "devserver-commander")
            self.assertNotEqual(user_file.parent, paths.PROJECT_ROOT)


class ExecutableNameTests(unittest.TestCase):
    """The file name carries platform and version."""

    def test_the_name_carries_platform_and_version(self) -> None:
        cases = [
            (False, "x86_64", "devserver-commander-linux-x86_64-0.8.0-build24"),
            (False, "aarch64", "devserver-commander-linux-aarch64-0.8.0-build24"),
            (False, "AMD64", "devserver-commander-linux-x86_64-0.8.0-build24"),
            (True, "AMD64", "devserver-commander-windows-x86_64-0.8.0-build24.exe"),
        ]
        for windows, machine, expected in cases:
            with self.subTest(machine=machine, windows=windows), \
                    mock.patch.object(paths, "IS_WINDOWS", windows), \
                    mock.patch.object(paths, "IS_MACOS", False), \
                    mock.patch.object(paths.platform, "machine", return_value=machine):
                self.assertEqual(paths.executable_name("0.8.0", 24), expected)

    def test_the_name_defaults_to_this_version(self) -> None:
        found = version.current()
        expected = "{0}-build{1}".format(found.name, int(found.build or 0))
        self.assertTrue(paths.executable_name().endswith(expected))


class VersionTests(FrozenTestCase):
    """The executable reads its bundled VERSION file and nothing else."""

    def setUp(self) -> None:
        super().setUp()
        version.forget()
        self.addCleanup(version.forget)

    def test_the_bundled_file_is_the_answer_and_git_is_never_asked(self) -> None:
        (self.bundle / "VERSION").write_text("0.8.0 24 b536519 2026-09-28 1\n", encoding="utf-8")
        (self.bundle / ".git").mkdir()
        with mock.patch.object(version, "FROZEN", True), \
                mock.patch.object(version, "_git", side_effect=AssertionError("no git")), \
                mock.patch.object(version, "_write", side_effect=AssertionError("no write")):
            found = version.current(self.bundle)
        self.assertEqual(found.label, "0.8.0 (24) · b536519 · 28.09.2026")

    def test_the_parser_knows_the_flag_and_the_program_name(self) -> None:
        parser = cli_args.build_parser()
        self.assertEqual(parser.prog, self.executable.name)
        with mock.patch.object(paths, "IS_FROZEN", False):
            self.assertEqual(cli_args.build_parser().prog, "run.py")
        with mock.patch("sys.stdout"), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)


class VersionFlagTests(unittest.TestCase):
    """``--version`` answers before anything else happens."""

    def test_version_flag_answers_without_a_gui_toolkit(self) -> None:
        """build-exe.py checks the finished file this way, headless."""
        probe = (
            "import runpy, sys\n"
            "sys.argv = ['run.py', '--version']\n"
            "try:\n"
            "    runpy.run_path('run.py', run_name='__main__')\n"
            "except SystemExit:\n"
            "    assert 'tkinter' not in sys.modules and 'gi' not in sys.modules, 'GUI imported'\n"
            "    raise\n"
        )
        with tempfile.TemporaryDirectory() as home:
            completed = subprocess.run(
                [sys.executable, "-c", probe], cwd=str(ROOT), capture_output=True, text=True,
                timeout=60, env={"PATH": "/usr/bin:/bin", "HOME": home},
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("DevServer Commander " + version.label(ROOT), completed.stdout)


class LauncherTests(FrozenTestCase):
    """Desktop shortcut and autostart start the executable itself."""

    def test_the_shortcut_starts_the_executable(self) -> None:
        exec_lines = [line for line in desktop_setup.build_desktop_entry_content().splitlines()
                      if line.startswith("Exec=")]
        self.assertEqual(exec_lines, [f"Exec={self.executable.resolve()}"])

    def test_the_autostart_starts_the_executable_into_the_tray(self) -> None:
        content = desktop_setup.build_autostart_entry_content()
        exec_lines = [line for line in content.splitlines() if line.startswith("Exec=")]
        self.assertEqual(exec_lines, [f"Exec={self.executable.resolve()} --tray"])
        self.assertNotIn("python3", content)
        self.assertNotIn("Path=", content)

    def test_the_launcher_icon_outlives_the_unpacked_files(self) -> None:
        icon = desktop_setup.launcher_icon()
        self.assertEqual(icon.parent, self.data_dir)
        self.assertTrue(icon.is_file())
        icon_lines = [line for line in desktop_setup.build_desktop_entry_content().splitlines()
                      if line.startswith("Icon=")]
        self.assertEqual(icon_lines, [f"Icon={icon}"])

    def test_a_checkout_keeps_its_python3_launcher_and_icon(self) -> None:
        with mock.patch.object(paths, "IS_FROZEN", False):
            self.assertEqual(desktop_setup.build_exec_line(), f"Exec=python3 {paths.MAIN_SCRIPT}")
            self.assertEqual(desktop_setup.launcher_icon(), paths.ICON_FILE)


class NoInterpreterTests(FrozenTestCase):
    """``sys.executable`` is the program itself: ``-m pip`` would start it again."""

    def test_the_setup_window_never_runs_pip(self) -> None:
        need = bootstrap_ui.Need(label="Something", pip=("something",))
        progress = bootstrap_ui.Progress(needs=[need])
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(bootstrap_ui, "_run", side_effect=AssertionError("must not run")):
            self.assertFalse(bootstrap_ui._fetch(progress, need))

    def test_the_executable_does_not_ask_for_python_bindings(self) -> None:
        """PyGObject is built in; only the external programs remain to be checked."""
        spec = importlib.util.spec_from_file_location("run_frozen", str(ROOT / "run.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertNotIn("gi", [need.module for need in module.NEEDS])
        self.assertIn("pkexec", [need.command for need in module.NEEDS])

    def test_no_module_calls_the_interpreter_unguarded(self) -> None:
        sources = [ROOT / "run.py", ROOT / "paths.py", ROOT / "version.py", ROOT / "bootstrap_ui.py"]
        for package in ("config", "models", "services", "ui"):
            sources.extend(sorted((ROOT / package).glob("*.py")))
        offenders = [str(source.relative_to(ROOT)) for source in sources
                     if "sys.executable" in source.read_text(encoding="utf-8")
                     and source.name not in ("bootstrap_ui.py", "paths.py")]
        self.assertEqual(offenders, [])


class MigrationTests(unittest.TestCase):
    """User data moves out of the project root once, and the old file stays."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        base = Path(self._temp_dir.name)
        self.old = base / "checkout" / "servers.json"
        self.new = base / "config" / "devserver-commander" / "servers.json"
        self.old.parent.mkdir()

    def test_the_old_file_is_copied_when_the_new_one_is_missing(self) -> None:
        self.old.write_text('{"servers": []}', encoding="utf-8")
        paths.migrate_legacy_user_data(((self.old, self.new),))
        self.assertEqual(self.new.read_text(encoding="utf-8"), '{"servers": []}')
        self.assertTrue(self.old.is_file())

    def test_an_existing_new_file_is_never_overwritten(self) -> None:
        self.old.write_text("old", encoding="utf-8")
        self.new.parent.mkdir(parents=True)
        self.new.write_text("new", encoding="utf-8")
        paths.migrate_legacy_user_data(((self.old, self.new),))
        self.assertEqual(self.new.read_text(encoding="utf-8"), "new")

    def test_nothing_to_migrate_creates_nothing(self) -> None:
        paths.migrate_legacy_user_data(((self.old, self.new),))
        self.assertFalse(self.new.exists())

    def test_the_executable_has_nothing_to_migrate(self) -> None:
        self.old.write_text("old", encoding="utf-8")
        with mock.patch.object(paths, "IS_FROZEN", True):
            paths.migrate_legacy_user_data(((self.old, self.new),))
        self.assertFalse(self.new.exists())


class ChildEnvironmentTests(unittest.TestCase):
    """Children get the system's libraries, never the executable's."""

    def test_children_get_no_paths_into_the_unpacked_files(self) -> None:
        env = {
            "LD_LIBRARY_PATH": "/tmp/_MEIabc",
            "LD_LIBRARY_PATH_ORIG": "/opt/lib",
            "GI_TYPELIB_PATH": "/tmp/_MEIabc/gi_typelibs",
            "XDG_DATA_DIRS": "/tmp/_MEIabc/share:/usr/share",
            "_PYI_ARCHIVE_FILE": "/home/me/devserver-commander",
            "HOME": "/home/me",
        }
        with mock.patch.object(paths, "IS_FROZEN", True), \
                mock.patch.object(sys, "_MEIPASS", "/tmp/_MEIabc", create=True):
            self.assertEqual(paths.child_environment(env), {
                "LD_LIBRARY_PATH": "/opt/lib",
                "XDG_DATA_DIRS": "/usr/share",
                "HOME": "/home/me",
            })

    def test_without_an_original_the_library_path_is_dropped(self) -> None:
        with mock.patch.object(paths, "IS_FROZEN", True), \
                mock.patch.object(sys, "_MEIPASS", "/tmp/_MEIabc", create=True):
            self.assertNotIn("LD_LIBRARY_PATH",
                             paths.child_environment({"LD_LIBRARY_PATH": "/tmp/_MEIabc"}))

    def test_a_checkout_hands_its_environment_on_unchanged(self) -> None:
        env = {"LD_LIBRARY_PATH": "/x", "_PYI_X": "y"}
        self.assertEqual(paths.child_environment(env), env)

    def test_every_popen_gets_the_clean_environment(self) -> None:
        with mock.patch.object(subprocess, "Popen", subprocess.Popen), \
                mock.patch.object(paths, "IS_FROZEN", True), \
                mock.patch.object(sys, "_MEIPASS", "/tmp/_MEIabc", create=True), \
                mock.patch.dict("os.environ", {"DEVSERVER_PROBE": "/tmp/_MEIabc/lib"}):
            paths.use_system_environment_for_children()
            paths.use_system_environment_for_children()
            output = subprocess.run(
                [sys.executable, "-c", "import os; print(os.environ.get('DEVSERVER_PROBE'))"],
                stdout=subprocess.PIPE, check=True,
            ).stdout.decode().strip()
            self.assertEqual(output, "None")
            self.assertFalse(getattr(subprocess.Popen.__bases__[0], "_devserver_commander_clean_env", False),
                             "patched only once")

    def test_a_server_starts_without_the_bundled_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as log_dir, \
                mock.patch.object(process_module, "LOG_DIR", Path(log_dir)), \
                mock.patch.object(paths, "IS_FROZEN", True), \
                mock.patch.object(sys, "_MEIPASS", "/tmp/_MEIabc", create=True), \
                mock.patch.dict("os.environ", {"LD_LIBRARY_PATH": "/tmp/_MEIabc",
                                               "LD_LIBRARY_PATH_ORIG": "/opt/lib"}):
            project = ServerProject(
                name="probe", directory="/tmp",
                command="sh -c 'echo probe=$LD_LIBRARY_PATH; echo own=$OWN'", env={"OWN": "kept"},
            )
            server = process_module.ServerProcess(project)
            server.start()
            deadline = time.monotonic() + 5
            while server._popen.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            log = process_module.log_path_for(project).read_text(encoding="utf-8")
        self.assertIn("probe=/opt/lib", log)
        self.assertIn("own=kept", log)


class BuildScriptTests(unittest.TestCase):
    """The build script, without building."""

    def test_the_build_installs_only_pyinstaller(self) -> None:
        packages = _build_script().bundled_packages()
        self.assertEqual(len(packages), 1)
        self.assertTrue(packages[0].startswith("pyinstaller"))

    def test_the_spec_file_compiles_limits_gtk_and_carries_the_data(self) -> None:
        build = _build_script()
        text = build.spec_text(Path("/tmp/stage"))
        compile(text, "devserver-commander.spec", "exec")
        self.assertIn("'icons': []", text)
        self.assertIn("'themes': []", text)
        self.assertIn("'Gtk': '3.0'", text)
        self.assertIn("console=False", text)
        self.assertIn("name={0!r}".format(paths.executable_name()), text)
        self.assertIn("('/tmp/stage', '.')", text)
        self.assertIn(repr(str(ROOT / "run.py")), text)

    def test_every_data_file_exists(self) -> None:
        for relative in _build_script().DATA_FILES:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_build_output_is_not_checked_in(self) -> None:
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/build/", lines)
        self.assertIn("/dist/", lines)

    def test_the_workflow_tags_releases_with_version_and_build(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release-exe.yml").read_text(encoding="utf-8")
        self.assertIn('TAG="v${VERSION}-build${BUILD}"', workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("ubuntu-22.04", workflow)
        self.assertNotIn("windows", workflow)


if __name__ == "__main__":
    unittest.main()

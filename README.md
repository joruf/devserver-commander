# DevServer Commander

A desktop GUI to **start, stop and restart local development servers** — PHP built-in servers, Node.js apps, Mailpit, MailHog, or any custom command — from one window instead of juggling multiple terminal tabs.

## Features

- **Server list** — add, edit and remove projects with type, port, status, autostart, paths, CPU, and memory
- **Server type column** — see at a glance whether a project is PHP, Node.js, or a custom command
- **Server templates** — quick-start presets for PHP MVC, PHP, Node.js/npm, Vite, Python, MailHog, and Mailpit
- **PHP built-in server wizard** — pick installed PHP version, document root, router script, Xdebug and worker count
- **Node.js server wizard** — configure `npm run`, `npx`, or `node` commands with optional `PORT` environment variable
- **MailHog and Mailpit installer** — download and install mail testing tools with one click (no `sudo` required)
- **PHP package installer** — install missing PHP CLI versions via `apt` from the project dialog
- **Save-time validation** — checks directories, binaries, npm scripts, ports, and router files before saving
- **Custom directory picker** — browse project folders with an optional “show hidden files/folders” toggle
- **Start / Stop / Restart** — each server runs as a managed background process in its own process group
- **Autostart** — flagged servers launch automatically when the app opens
- **Live log view** — tail stdout/stderr of the selected server in the window
- **Save visible log output** — export the currently shown log text to a `.txt` file
- **System tray** — closing the window keeps the app running in the tray; use **File → Close and Exit** or the tray menu to quit
- **CPU and memory columns** — see per-server resource usage in the server list (refresh interval configurable in **Settings → Preferences**)
- **Context menu** — right-click a server for start, stop, restart, open website, edit, and remove
- **Edit running servers** — change configuration while a server is running; saving prompts to restart when needed
- **Port conflict details** — clear error messages with PID and process name when a port is already in use
- **Single instance** — only one application window; launching again brings the existing window to the front
- **Detects externally running servers** — shows "Running (unmanaged)" when a configured port is already in use
- **Desktop shortcut** — optional first-run prompt to create a launcher on your desktop
- **No pip dependencies** — Python standard library and tkinter only

## Screenshots

### Main window

Server list with type, status, CPU/memory usage, and live log output for the selected project.

![Main window](docs/screenshots/main-window.png)

### Context menu

Right-click a server for quick start, stop, restart, open website, edit, and remove actions.

![Context menu](docs/screenshots/context-menu.png)

### Add project — PHP template

Configure PHP version, document root, router script, Xdebug, workers, and preview the generated start command.

![PHP project dialog](docs/screenshots/project-dialog-php.png)

### Add project — Node.js template

Configure npm, npx, or node commands with optional `PORT` environment variable substitution.

![Node.js project dialog](docs/screenshots/project-dialog-node.png)

### Add project — Mailpit / MailHog

Use the Mailpit or MailHog template and install the binary directly from the dialog when it is missing.

![Mailpit project dialog](docs/screenshots/project-dialog-mailpit.png)

![MailHog project dialog](docs/screenshots/project-dialog-mailhog.png)

### Directory picker

Choose a working directory with an optional hidden-files toggle when browsing folders.

![Directory picker](docs/screenshots/directory-picker.png)

### Preferences

Configure how often CPU and memory values are refreshed in the server list.

![Preferences](docs/screenshots/preferences.png)

## Requirements

- Linux
- Python 3.10+ with tkinter (usually pre-installed; on Debian/Ubuntu: `sudo apt install python3-tk`)
- `fuser` from `psmisc` (used to stop servers that were not started by DevServer Commander; on Debian/Ubuntu: `sudo apt install psmisc`)
- Optional: GTK3 Python bindings for the system tray (on Debian/Ubuntu: `sudo apt install gir1.2-gtk-3.0`)
- Optional: ImageMagick `import` and `scrot` (only needed to regenerate README screenshots)

## Installation & Usage

```bash
git clone https://github.com/joruf/devserver-commander.git
cd devserver-commander
chmod +x devserver_commander.py installer.py
python3 installer.py
./devserver_commander.py
```

On first start you are asked once whether to create a desktop shortcut. You can also create it from **Help → Create Desktop Shortcut...**.

The installer checks Python, tkinter, and `fuser`, and sets the executable bit on the main script if needed.

## Project structure

```
devserver-commander/
├── devserver_commander.py          # Application entry point; starts the GUI
├── installer.py                    # Checks Python, tkinter, fuser, and GTK3; sets executable permissions
├── paths.py                        # Central path constants for config, icons, desktop files, and resources
├── servers.json                    # User-defined server list persisted as JSON
├── README.md                       # Project documentation
├── LICENSE                         # License terms
├── .gitignore                      # Git ignore rules for local and generated files
├── .gitattributes                  # Git line-ending and file attribute rules
│
├── config/                         # Configuration loading, validation, and app preferences
│   ├── __init__.py                 # Public exports for the config package
│   ├── manager.py                  # Loads and saves the server list from servers.json
│   ├── validation.py               # Validates ports, document roots, router scripts, and launch commands
│   ├── app_settings.py             # Loads and saves user preferences (e.g. stats refresh interval)
│   └── presets.py                  # Built-in server templates for the add-project dialog
│
├── models/                         # Data structures used across the application
│   ├── __init__.py                 # Public exports for the models package
│   └── server_project.py           # ServerProject dataclass: name, directory, command, port, env, autostart
│
├── services/                       # Business logic without UI dependencies
│   ├── __init__.py                 # Public exports for the services package
│   ├── process.py                  # Starts, stops, restarts processes; manages log file paths
│   ├── php.py                      # PHP version detection, command building, and install helpers
│   ├── node.py                     # Node.js command building and npm/npx/node detection helpers
│   ├── server_types.py             # Detects whether a stored command is PHP, Node.js, or custom
│   ├── dev_tools.py                # One-click download/install helpers for MailHog and Mailpit
│   ├── stats.py                    # CPU and memory usage via /proc; port-to-PID lookup
│   ├── port_info.py                # Describes which process is using a TCP port
│   ├── ports.py                    # Low-level TCP port availability checks
│   ├── single_instance.py          # Prevents multiple application instances from running
│   └── instance_ipc.py             # Unix socket used to raise the existing window on relaunch
│
├── ui/                             # Tkinter windows, dialogs, and desktop integration
│   ├── __init__.py                 # Public exports for the UI package
│   ├── main_window.py              # Main window: server list, toolbar, log view, menus, polling
│   ├── project_dialog.py           # Add/Edit dialog for PHP, Node.js, and custom server commands
│   ├── directory_picker.py         # Custom directory chooser with hidden-folder support
│   ├── preferences_dialog.py     # Preferences dialog for application-wide settings
│   ├── desktop_setup.py            # First-run prompt and desktop shortcut creation
│   ├── window_icon.py              # Applies the application icon to windows and dialogs
│   ├── tray.py                     # GTK3 system tray icon with show and exit actions
│   └── startup_notify.py           # Clears the desktop busy cursor after launch
│
├── scripts/                        # Maintenance helpers
│   └── generate_screenshots.py     # Regenerates README screenshots from the live UI
│
├── resources/                      # Static assets shipped with the application
│   ├── devserver-commander.desktop # Template for the Linux desktop launcher
│   └── devserver-commander.png     # Application icon for window, tray, and desktop shortcut
│
└── docs/                           # Documentation assets
    └── screenshots/                # README screenshots
        ├── main-window.png         # Main application window
        ├── context-menu.png        # Server list context menu
        ├── project-dialog-php.png  # Add project dialog with PHP template
        ├── project-dialog-node.png # Add project dialog with Node.js template
        ├── project-dialog-mailpit.png
        ├── project-dialog-mailhog.png
        ├── directory-picker.png    # Directory chooser dialog
        └── preferences.png         # Preferences dialog
```

### Runtime files (not in the repository)

| Path | Purpose |
|------|---------|
| `~/.config/devserver-commander/settings.json` | Persisted application preferences |
| `~/.local/state/devserver-commander/logs/` | Per-server stdout/stderr log files |
| `~/.local/state/devserver-commander/instance.lock` | Single-instance lock file while the app is running |
| `~/.local/state/devserver-commander/control.sock` | Control socket used to raise the existing window on relaunch |
| `~/.local/share/devserver-commander/bin/` | Downloaded MailHog and Mailpit binaries |
| `.initialized` | Marker file in the project root; skips the first-run desktop shortcut prompt |

## Configuration

All servers are stored in `servers.json` in the project directory:

```json
{
  "servers": [
    {
      "name": "My App",
      "directory": "/path/to/project",
      "command": "/usr/bin/php8.4 -S localhost:{port} -t public/ public/index.php",
      "port": 8001,
      "env": {
        "XDEBUG_SESSION": "1",
        "PHP_CLI_SERVER_WORKERS": "6"
      },
      "autostart": false
    }
  ]
}
```

- `{port}` in the command is replaced with the configured port number
- `-t public/` sets the document root (web root folder)
- `public/index.php` is an optional router script that handles all requests
- `PHP_CLI_SERVER_WORKERS` is omitted when set to `0` in the GUI

Log files are written to `~/.local/state/devserver-commander/logs/` and persist even when the GUI is closed.

## Server templates

When adding a project, choose a template to pre-fill the dialog:

| Template | Type | Typical port |
|----------|------|--------------|
| PHP MVC (router) | PHP | 8001 |
| PHP (document root only) | PHP | 8002 |
| Node.js (npm run dev) | Node.js | 3000 |
| Vite (npx) | Node.js | 5173 |
| Python HTTP server | Custom | 8080 |
| MailHog | Custom | 8025 |
| Mailpit | Custom | 8025 |

MailHog and Mailpit are installed to `~/.local/share/devserver-commander/bin/` when you click **Install...** in the project dialog.

## Usage tips

| Action | How |
|--------|-----|
| Add server | **Add** button, then choose a **Template** preset |
| Edit server | Select entry, then **Edit**, double-click, or right-click **Edit...** |
| Start / stop / restart | Toolbar buttons or right-click context menu |
| Open website | **Open Website** button or right-click context menu |
| Save visible log | **View → Save Visible Log Output...** |
| Hide to tray | Close the window or **File → Close** |
| Quit completely | **File → Close and Exit** or tray menu **Exit** |
| CPU/memory refresh | **Settings → Preferences...** |
| Install PHP | In the project dialog: **Install...** next to the PHP version dropdown |
| Install MailHog / Mailpit | In the project dialog: **Install...** next to the custom command field |
| Browse with hidden folders | **Browse...** in the project dialog, then enable the checkbox |

Edit and Remove are disabled until a server is selected. Running servers can be edited; saving while a server is running asks whether to restart it. Remove still requires the server to be stopped first.

## Regenerating screenshots

If you change the UI and want to refresh the README images:

```bash
python3 scripts/generate_screenshots.py
```

Requires a running X11 desktop session plus `import` (ImageMagick) and `scrot`.

## License

See [LICENSE](LICENSE).

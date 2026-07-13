"""Built-in server configuration templates for the project dialog."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ServerPreset:
    """Predefined values for quickly creating a new server entry."""

    label: str
    server_type: str
    suggested_name: str
    port: Optional[int]
    command: str
    env: Dict[str, str] = field(default_factory=dict)
    docroot: str = "public/"
    router: str = ""
    node_mode: str = "npm run"
    node_target: str = ""
    use_port_env: bool = False
    directory_hint: str = ""
    dev_tool_id: str = ""


SERVER_PRESETS: List[ServerPreset] = [
    ServerPreset(
        label="PHP MVC (router)",
        server_type="php",
        suggested_name="My PHP App",
        port=8001,
        command="",
        docroot="public/",
        router="public/index.php",
    ),
    ServerPreset(
        label="PHP (document root only)",
        server_type="php",
        suggested_name="My PHP App",
        port=8002,
        command="",
        docroot="public/",
    ),
    ServerPreset(
        label="Node.js (npm run dev)",
        server_type="node",
        suggested_name="My Node App",
        port=3000,
        command="npm run dev",
        node_mode="npm run",
        node_target="dev",
        use_port_env=True,
    ),
    ServerPreset(
        label="Vite (npx)",
        server_type="node",
        suggested_name="Vite App",
        port=5173,
        command="npx vite --port {port} --host localhost",
        node_mode="npx",
        node_target="vite --port {port} --host localhost",
        use_port_env=False,
    ),
    ServerPreset(
        label="Python HTTP server",
        server_type="custom",
        suggested_name="Python Static Server",
        port=8080,
        command="python3 -m http.server {port}",
    ),
    ServerPreset(
        label="MailHog",
        server_type="custom",
        suggested_name="MailHog",
        port=8025,
        command="",
        dev_tool_id="mailhog",
    ),
    ServerPreset(
        label="Mailpit",
        server_type="custom",
        suggested_name="Mailpit",
        port=8025,
        command="",
        dev_tool_id="mailpit",
    ),
]


DEFAULT_PRESET_LABEL = "PHP MVC (router)"


def preset_labels() -> List[str]:
    """
    Return preset labels for the template dropdown.

    :return: Preset labels with a leading empty option
    """
    return ["(none)"] + [preset.label for preset in SERVER_PRESETS]


def find_preset(label: str) -> Optional[ServerPreset]:
    """
    Find a preset by its label.

    :param label: Preset label from the template dropdown
    :return: Matching preset or None
    """
    for preset in SERVER_PRESETS:
        if preset.label == label:
            return preset
    return None

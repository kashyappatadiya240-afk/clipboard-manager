"""Keeps Klipora running across logins by installing a session autostart entry.

A clipboard manager can only capture history while its process is alive, so
Klipora registers itself in ~/.config/autostart to start hidden at login.
Set KLIPORA_NO_AUTOSTART=1 to opt out.
"""

import logging
import os
import pathlib
import sys

logger = logging.getLogger(__name__)

AUTOSTART_FILE_NAME = "com.kashyap.Klipora.desktop"

AUTOSTART_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Klipora
Comment=Clipboard history manager (runs in the background)
Exec={exec_line} --background
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def _exec_line() -> str:
    """Picks the most stable launcher command for the autostart entry."""
    launcher = pathlib.Path.home() / ".local" / "bin" / "klipora"
    if launcher.is_file():
        return str(launcher)

    app_py = pathlib.Path(__file__).resolve().parent.parent / "app.py"
    if app_py.is_file():
        return f'"{sys.executable}" "{app_py}"'

    return "klipora"


def _system_autostart_exists() -> bool:
    """True when a system-wide autostart entry (e.g. from a deb) already exists."""
    config_dirs = os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg")
    for base in config_dirs.split(":"):
        if (pathlib.Path(base) / "autostart" / AUTOSTART_FILE_NAME).is_file():
            return True
    return False


def ensure_autostart() -> None:
    """Creates the autostart entry unless it already exists or is disabled."""
    if os.environ.get("KLIPORA_NO_AUTOSTART") == "1":
        logger.debug("Autostart disabled via KLIPORA_NO_AUTOSTART")
        return

    autostart_dir = (
        pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config"))
        / "autostart"
    )
    entry = autostart_dir / AUTOSTART_FILE_NAME

    if entry.is_file():
        return
    if _system_autostart_exists():
        return

    try:
        autostart_dir.mkdir(parents=True, exist_ok=True)
        entry.write_text(AUTOSTART_TEMPLATE.format(exec_line=_exec_line()), encoding="utf-8")
        entry.chmod(0o644)
        logger.info("Installed autostart entry: %s", entry)
    except Exception as e:
        logger.warning("Could not install autostart entry: %s", e)

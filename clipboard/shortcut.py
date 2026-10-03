"""GNOME / Wayland global keyboard shortcut manager for Ubuntu Clipboard."""

import logging
import os
import pathlib
import sys
from typing import List, Optional

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

logger = logging.getLogger(__name__)

MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_KEYBINDING_SCHEMA = (
    "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
)
CUSTOM_PATH = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ubuntu-clipboard/"
)
SHELL_KEYBINDINGS_SCHEMA = "org.gnome.shell.keybindings"
MESSAGE_TRAY_KEY = "toggle-message-tray"
TARGET_SHORTCUT = "<Super>v"
SHORTCUT_NAME = "Ubuntu Clipboard History"


def get_default_app_command() -> str:
    """Returns the default executable command line to activate Ubuntu Clipboard."""
    project_root = pathlib.Path(__file__).resolve().parent.parent
    app_path = project_root / "app.py"
    python_bin = sys.executable
    return f"{python_bin} {app_path}"


def is_gnome_environment() -> bool:
    """Checks whether the current session is GNOME."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    session = os.environ.get("DESKTOP_SESSION", "").upper()
    return "GNOME" in desktop or "GNOME" in session or "UBUNTU" in desktop


def register_global_shortcut(
    command: Optional[str] = None,
    shortcut: str = TARGET_SHORTCUT,
) -> bool:
    """Registers the Super+V global shortcut in GNOME media-keys."""
    try:
        source = Gio.SettingsSchemaSource.get_default()
        if not source or not source.lookup(MEDIA_KEYS_SCHEMA, True):
            logger.warning(
                "GSettings schema %s not available in this environment",
                MEDIA_KEYS_SCHEMA,
            )
            return False

        if command is None:
            command = get_default_app_command()

        # 1. Configure the custom keybinding entry
        binding_settings = Gio.Settings.new_with_path(
            CUSTOM_KEYBINDING_SCHEMA, CUSTOM_PATH
        )
        binding_settings.set_string("name", SHORTCUT_NAME)
        binding_settings.set_string("binding", shortcut)
        binding_settings.set_string("command", command)
        binding_settings.apply()

        # 2. Add to custom-keybindings list in media-keys if not present
        media_settings = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
        current_bindings: List[str] = list(
            media_settings.get_strv("custom-keybindings")
        )
        if CUSTOM_PATH not in current_bindings:
            current_bindings.append(CUSTOM_PATH)
            media_settings.set_strv("custom-keybindings", current_bindings)
            media_settings.apply()

        # 3. Free up <Super>v in gnome-shell toggle-message-tray if bound there
        if source.lookup(SHELL_KEYBINDINGS_SCHEMA, True):
            shell_settings = Gio.Settings.new(SHELL_KEYBINDINGS_SCHEMA)
            tray_bindings = list(shell_settings.get_strv(MESSAGE_TRAY_KEY))
            # Case-insensitive comparison for shortcut string
            has_conflict = any(
                b.lower() == shortcut.lower() for b in tray_bindings
            )
            if has_conflict:
                updated_tray = [
                    b for b in tray_bindings if b.lower() != shortcut.lower()
                ]
                shell_settings.set_strv(MESSAGE_TRAY_KEY, updated_tray)
                shell_settings.apply()
                logger.info(
                    "Reallocated %s from GNOME toggle-message-tray to Ubuntu Clipboard",
                    shortcut,
                )

        logger.info(
            "Registered global shortcut '%s' -> '%s'", shortcut, command
        )
        return True
    except Exception as e:
        logger.error("Failed to register global shortcut: %s", e)
        return False


def unregister_global_shortcut() -> bool:
    """Removes the Ubuntu Clipboard global shortcut from GNOME media-keys."""
    try:
        source = Gio.SettingsSchemaSource.get_default()
        if not source or not source.lookup(MEDIA_KEYS_SCHEMA, True):
            return False

        media_settings = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
        current_bindings = list(media_settings.get_strv("custom-keybindings"))
        if CUSTOM_PATH in current_bindings:
            current_bindings.remove(CUSTOM_PATH)
            media_settings.set_strv("custom-keybindings", current_bindings)
            media_settings.apply()

        binding_settings = Gio.Settings.new_with_path(
            CUSTOM_KEYBINDING_SCHEMA, CUSTOM_PATH
        )
        binding_settings.reset("name")
        binding_settings.reset("binding")
        binding_settings.reset("command")
        binding_settings.apply()

        logger.info("Unregistered global shortcut")
        return True
    except Exception as e:
        logger.error("Failed to unregister global shortcut: %s", e)
        return False


def is_shortcut_registered() -> bool:
    """Checks if the Ubuntu Clipboard global shortcut is currently registered."""
    try:
        source = Gio.SettingsSchemaSource.get_default()
        if not source or not source.lookup(MEDIA_KEYS_SCHEMA, True):
            return False

        media_settings = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
        current_bindings = list(media_settings.get_strv("custom-keybindings"))
        if CUSTOM_PATH not in current_bindings:
            return False

        binding_settings = Gio.Settings.new_with_path(
            CUSTOM_KEYBINDING_SCHEMA, CUSTOM_PATH
        )
        return (
            binding_settings.get_string("binding").lower()
            == TARGET_SHORTCUT.lower()
        )
    except Exception:
        return False

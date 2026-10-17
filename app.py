#!/usr/bin/env python3
import ctypes
import logging
import os
import signal
import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

try:
    from gi.repository import GLibUnix
except ImportError:
    GLibUnix = None

from clipboard.autostart import ensure_autostart
from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import ClipboardMonitor
from clipboard.screenshot_monitor import ScreenshotMonitor
from clipboard.picker_service import PickerDBusService
from clipboard.shortcut import register_global_shortcut
from ui.window import ClipboardWindow

logging.basicConfig(
    level=os.environ.get("KLIPORA_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("klipora")


def set_process_title(title: str = "klipora") -> None:
    """Sets the process title and system process name so ps aux and pgrep can identify it."""
    try:
        import setproctitle

        setproctitle.setproctitle(title)
    except Exception:
        pass

    try:
        libc = ctypes.CDLL(None)
        # PR_SET_NAME = 15
        libc.prctl(15, title.encode("utf-8"), 0, 0, 0)
    except Exception:
        pass


class ClipboardApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="com.kashyap.Klipora",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
            | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.window = None
        self.database = ClipboardDatabase()
        self.monitor = None
        self.screenshot_monitor = None
        self.picker_service = None
        self._is_held = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        logger.info("Application starting up...")
        self.database.initialize()
        ensure_autostart()
        self.monitor = ClipboardMonitor(
            database=self.database,
            on_new_item=self._on_new_clipboard_item,
        )
        self.monitor.start()

        self.screenshot_monitor = ScreenshotMonitor(
            database=self.database,
            on_new_item=self._on_new_clipboard_item,
            clipboard_monitor=self.monitor,
        )
        self.screenshot_monitor.start()

        # Start D-Bus Picker service for GNOME Shell Extension integration
        self.picker_service = PickerDBusService(
            database=self.database,
            monitor=self.monitor,
        )
        self.picker_service.start()

        # Hold application so it persists in the background when the launcher window hides
        self.hold()
        self._is_held = True

        # Register GNOME global keyboard shortcut (Super + V)
        register_global_shortcut()

        # Application GIO actions
        show_action = Gio.SimpleAction.new("show-history", None)
        show_action.connect("activate", lambda a, p: self.show_clipboard_history())
        self.add_action(show_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda a, p: self.quit())
        self.add_action(quit_action)

        # Handle SIGINT and SIGTERM gracefully
        if GLibUnix:
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_signal)
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._on_signal)
        else:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_signal)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._on_signal)

    def do_activate(self):
        logger.info("Application activated, presenting clipboard history window...")
        self.show_clipboard_history()

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Handles command line; --background starts the monitor without showing the window."""
        args = command_line.get_arguments()
        if not any(arg in ("--background", "-b") for arg in args[1:]):
            self.activate()
        return 0

    def show_clipboard_history(self):
        """Ensures the launcher window exists and brings it to foreground with keyboard focus."""
        if not self.window:
            logger.info("Creating new ClipboardWindow...")
            self.window = ClipboardWindow(
                application=self,
                database=self.database,
                monitor=self.monitor,
            )
        self.window.present_history()

    def _on_new_clipboard_item(self, item: ClipboardItem):
        if self.window:
            self.window.add_clipboard_item(item)

    def _on_signal(self):
        logger.info("Termination signal received, shutting down...")
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_shutdown(self):
        logger.info("Application shutting down...")
        if self._is_held:
            self.release()
            self._is_held = False
        if self.picker_service:
            self.picker_service.stop()
            self.picker_service = None
        if self.screenshot_monitor:
            self.screenshot_monitor.stop()
            self.screenshot_monitor = None
        if self.monitor:
            self.monitor.stop()
            self.monitor = None
        self.database.close()
        Adw.Application.do_shutdown(self)


def main():
    set_process_title("klipora")
    GLib.set_application_name("Klipora")
    GLib.set_prgname("com.kashyap.Klipora")
    app = ClipboardApp()
    app.register(None)
    if app.get_is_remote():
        print("Klipora is already running. Showing existing window.")
    else:
        print("Klipora started. Press Super+V to open clipboard history.")
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

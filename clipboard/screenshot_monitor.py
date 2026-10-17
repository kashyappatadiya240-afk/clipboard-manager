import hashlib
import io
import logging
import os
import pathlib
import time
from datetime import datetime, timezone
from typing import Callable, Optional, Set

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib
from PIL import Image

from clipboard.database import ClipboardDatabase
from clipboard.image_utils import process_image_data
from clipboard.models import ClipboardItem

logger = logging.getLogger(__name__)

# Safety and dimension limits matching monitor.py
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_WIDTH = 8192
MAX_IMAGE_HEIGHT = 8192
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def get_screenshots_directory() -> pathlib.Path:
    """Detects the standard GNOME / Ubuntu screenshot storage directory."""
    try:
        pictures_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    except Exception:
        pictures_dir = None

    if pictures_dir:
        sc_dir = pathlib.Path(pictures_dir) / "Screenshots"
    else:
        sc_dir = pathlib.Path.home() / "Pictures" / "Screenshots"

    return sc_dir


class ScreenshotMonitor:
    """Monitors the GNOME / Ubuntu Screenshots directory to automatically capture screenshots.

    Even when the Klipora window is closed, not focused, or minimized, this monitor detects
    new screenshots written to ~/Pictures/Screenshots via inotify (Gio.FileMonitor) and
    imports them directly into the clipboard history.
    """

    def __init__(
        self,
        database: ClipboardDatabase,
        on_new_item: Optional[Callable[[ClipboardItem], None]] = None,
        screenshots_dir: Optional[pathlib.Path] = None,
        clipboard_monitor=None,
    ):
        self.database = database
        self.on_new_item = on_new_item
        self.screenshots_dir = (
            screenshots_dir if screenshots_dir is not None else get_screenshots_directory()
        )
        self.clipboard_monitor = clipboard_monitor
        self._file_monitor: Optional[Gio.FileMonitor] = None
        self._pending_files: dict[str, int] = {}
        self._last_imported_hash: Optional[str] = None
        self._seen_hashes: Set[str] = set()

    def start(self) -> None:
        """Starts real-time monitoring and scans for any recent screenshots taken while closed."""
        try:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("Could not ensure screenshots directory exists: %s", e)

        if not self.screenshots_dir.is_dir():
            logger.warning("Screenshots directory %s does not exist", self.screenshots_dir)
            return

        try:
            gfile = Gio.File.new_for_path(str(self.screenshots_dir))
            self._file_monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._file_monitor.connect("changed", self._on_directory_changed)
            logger.info("Screenshot monitor started on %s", self.screenshots_dir)
        except Exception as e:
            logger.error("Failed to start directory monitor on %s: %s", self.screenshots_dir, e)

        # Initial catch-up scan for screenshots taken while Klipora was not running / closed
        self.scan_recent_screenshots()

    def stop(self) -> None:
        """Cancels directory monitoring and clears pending timeouts."""
        for timeout_id in self._pending_files.values():
            try:
                GLib.source_remove(timeout_id)
            except Exception:
                pass
        self._pending_files.clear()

        if self._file_monitor:
            self._file_monitor.cancel()
            self._file_monitor = None

        logger.info("Screenshot monitor stopped")

    def _on_directory_changed(
        self,
        monitor: Gio.FileMonitor,
        file: Gio.File,
        other_file: Optional[Gio.File],
        event_type: Gio.FileMonitorEvent,
    ) -> None:
        """Callback triggered when files in ~/Pictures/Screenshots are created or modified."""
        # Focus on creation or write-finished hints
        if event_type not in (
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
        ):
            return

        file_path_str = file.get_path()
        if not file_path_str:
            return

        path = pathlib.Path(file_path_str)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return

        # Cancel any existing pending timer for this path to debounce rapid write events
        if file_path_str in self._pending_files:
            try:
                GLib.source_remove(self._pending_files[file_path_str])
            except Exception:
                pass

        # Wait 150ms to ensure the screenshot tool has finished writing and flushing the file
        def _deferred_process():
            self._pending_files.pop(file_path_str, None)
            self._process_screenshot_file(path)
            return False

        self._pending_files[file_path_str] = GLib.timeout_add(150, _deferred_process)

    def _process_screenshot_file(self, path: pathlib.Path) -> Optional[ClipboardItem]:
        """Reads, validates, normalizes, and stores a screenshot file into the database."""
        if not path.is_file():
            return None

        try:
            raw_bytes = path.read_bytes()
            if not raw_bytes:
                return None

            processed = process_image_data(raw_bytes)
            if not processed:
                return None
            png_data, img_hash, width, height = processed

            # Deduplication checks
            if img_hash == self._last_imported_hash or img_hash in self._seen_hashes:
                return None

            if self.database.has_image_hash(img_hash) or self.database.is_deleted_hash(img_hash):
                self._seen_hashes.add(img_hash)
                if self.clipboard_monitor:
                    self.clipboard_monitor._last_image_hash = img_hash
                return None

            # Use file's last modified time for accurate chronological ordering
            try:
                mtime = path.stat().st_mtime
                created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except Exception:
                created_at = datetime.now(timezone.utc).isoformat()

            item = self.database.add_image_item(
                png_data=png_data,
                image_hash=img_hash,
                is_pinned=False,
                created_at=created_at,
            )

            if item:
                self._last_imported_hash = img_hash
                self._seen_hashes.add(img_hash)
                if self.clipboard_monitor:
                    self.clipboard_monitor._last_image_hash = img_hash
                logger.info(
                    "Screenshot captured: %s (%dx%d, %d bytes, hash=%s...)",
                    path.name,
                    width,
                    height,
                    len(png_data),
                    img_hash[:10],
                )
                if self.on_new_item:
                    GLib.idle_add(self.on_new_item, item)
                return item

        except Exception as e:
            logger.debug("Could not process screenshot candidate %s: %s", path.name, e)

        return None

    def scan_recent_screenshots(self, max_files: int = 15) -> int:
        """Scans the screenshots folder and imports any recent screenshots not yet in the database.

        Only screenshots created after the last recorded scan time are considered.
        Previously deleted screenshots or existing records are strictly ignored.
        """
        if not self.screenshots_dir.is_dir():
            return 0

        now = time.time()
        last_scan_str = self.database.get_setting("last_screenshot_scan_time")
        if last_scan_str:
            try:
                min_mtime = float(last_scan_str)
            except ValueError:
                min_mtime = now - 60.0
        else:
            # First initialization: allow screenshots created up to 10s prior to startup
            min_mtime = now - 10.0
            self.database.set_setting("last_screenshot_scan_time", str(now))

        imported_count = 0
        try:
            candidates = []
            for entry in self.screenshots_dir.iterdir():
                if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                    try:
                        stat = entry.stat()
                        # Only consider files created/modified after the last scan marker
                        if stat.st_mtime >= min_mtime:
                            candidates.append((stat.st_mtime, entry))
                    except OSError:
                        pass

            # Sort descending by mtime (newest screenshots first)
            candidates.sort(key=lambda x: x[0], reverse=True)

            # Process candidates up to max_files
            for _, path in candidates[:max_files]:
                item = self._process_screenshot_file(path)
                if item:
                    imported_count += 1

            # Update marker to current time
            self.database.set_setting("last_screenshot_scan_time", str(now))

            if imported_count > 0:
                logger.info("Imported %d screenshot(s) from %s", imported_count, self.screenshots_dir)
        except Exception as e:
            logger.error("Error scanning recent screenshots: %s", e)

        return imported_count

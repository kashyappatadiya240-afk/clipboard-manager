import hashlib
import logging
import pathlib
from typing import Callable, Optional

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem

logger = logging.getLogger(__name__)

# Safety and dimension limits for image clipboard processing
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB safety limit
MAX_IMAGE_WIDTH = 8192              # Max supported pixel width (8K)
MAX_IMAGE_HEIGHT = 8192             # Max supported pixel height (8K)


class ClipboardMonitor:
    """Monitors the Wayland/GTK clipboard for text and image changes asynchronously."""

    def __init__(
        self,
        database: ClipboardDatabase,
        on_new_item: Optional[Callable[[ClipboardItem], None]] = None,
    ):
        self.database = database
        self.on_new_item = on_new_item
        self._clipboard = None
        self._changed_handler_id: Optional[int] = None
        self._poll_timer_id: Optional[int] = None
        self._is_reading: bool = False
        self._cancellable: Optional[Gio.Cancellable] = None
        self._last_content: Optional[str] = None
        self._last_image_hash: Optional[str] = None

    def start(self) -> None:
        """Initializes the clipboard monitor, hooks signals, and sets up polling fallback."""
        latest = self.database.get_latest()
        if latest:
            if latest.content_type == "image":
                self._last_image_hash = latest.image_hash
                self._last_content = None
            else:
                self._last_content = latest.content
                self._last_image_hash = None

        display = Gdk.Display.get_default()
        if not display:
            logger.error("No default GDK display available for clipboard monitor")
            return

        self._clipboard = display.get_clipboard()
        if not self._clipboard:
            logger.error("No GDK clipboard available")
            return

        # 1. Primary event-driven detection using GDK changed signal
        self._changed_handler_id = self._clipboard.connect("changed", self._on_clipboard_changed)

        # 2. Polling fallback (1 second interval) to maintain sync across Wayland window switches
        self._poll_timer_id = GLib.timeout_add(1000, self._on_poll)

        logger.info("Clipboard monitor started")

        # Initial check to capture any existing clipboard content
        self.check_clipboard()

    def stop(self) -> None:
        """Stops the clipboard monitor and disconnects signal handlers."""
        if self._cancellable:
            self._cancellable.cancel()
            self._cancellable = None

        if self._poll_timer_id:
            GLib.source_remove(self._poll_timer_id)
            self._poll_timer_id = None

        if self._changed_handler_id and self._clipboard:
            self._clipboard.disconnect(self._changed_handler_id)
            self._changed_handler_id = None

        self._clipboard = None
        logger.info("Clipboard monitor stopped")

    def _on_poll(self) -> bool:
        """Periodic callback to check clipboard."""
        self.check_clipboard()
        return True

    def _on_clipboard_changed(self, clipboard: Gdk.Clipboard) -> None:
        """Callback invoked when GDK signals that the clipboard content has changed."""
        self.check_clipboard()

    def check_clipboard(self, force: bool = False) -> None:
        """Asynchronously reads clipboard content (image or text) if not already reading."""
        if not self._clipboard:
            display = Gdk.Display.get_default()
            if display:
                self._clipboard = display.get_clipboard()

        if not self._clipboard:
            return

        # If forced (e.g. window presented or focused), cancel any prior in-flight read
        if force:
            if self._cancellable:
                self._cancellable.cancel()
                self._cancellable = None
            self._is_reading = False

        if self._is_reading:
            import time

            if time.time() - getattr(self, "_read_start_time", 0) > 3.0:
                logger.debug("Stale async clipboard read detected; resetting reading lock")
                if self._cancellable:
                    self._cancellable.cancel()
                    self._cancellable = None
                self._is_reading = False
            else:
                return

        formats = self._clipboard.get_formats()
        mime_types = formats.get_mime_types()
        if not mime_types and not force:
            return

        # Format Priority: Prefer genuine image representations over text
        has_image = formats.contain_gtype(Gdk.Texture) or any(
            m.startswith("image/") for m in mime_types
        )

        import time

        self._read_start_time = time.time()
        self._is_reading = True
        self._cancellable = Gio.Cancellable()

        if has_image:
            self._clipboard.read_texture_async(self._cancellable, self._on_read_texture_finish)
        else:
            self._clipboard.read_text_async(self._cancellable, self._on_read_text_finish)

    def _on_read_texture_finish(self, clipboard: Gdk.Clipboard, result) -> None:
        """Callback for completed async texture read operation."""
        self._is_reading = False
        try:
            texture = clipboard.read_texture_finish(result)
        except Exception as e:
            logger.debug("Clipboard texture read skipped or error: %s", e)
            # Fallback to text read if clipboard also offers text
            formats = clipboard.get_formats()
            if formats.contain_gtype(GObject.TYPE_STRING) or any(
                "text" in m for m in formats.get_mime_types()
            ):
                self._is_reading = True
                self._cancellable = Gio.Cancellable()
                clipboard.read_text_async(self._cancellable, self._on_read_text_finish)
            return

        if texture is None:
            return

        # 1. Dimension limit checks
        width = texture.get_width()
        height = texture.get_height()
        if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
            logger.warning(
                "Clipboard image dimensions (%dx%d) exceed maximum allowed limits (%dx%d)",
                width,
                height,
                MAX_IMAGE_WIDTH,
                MAX_IMAGE_HEIGHT,
            )
            return

        # 2. Normalize texture into PNG bytes
        try:
            png_glib_bytes = texture.save_to_png_bytes()
        except Exception as e:
            logger.error("Failed to convert clipboard texture to normalized PNG: %s", e)
            return

        # 3. Payload size check
        png_bytes_len = png_glib_bytes.get_size()
        if png_bytes_len > MAX_IMAGE_BYTES:
            logger.warning(
                "Clipboard image size (%d bytes) exceeds maximum limit (%d bytes)",
                png_bytes_len,
                MAX_IMAGE_BYTES,
            )
            return

        png_data = png_glib_bytes.get_data()
        from clipboard.image_utils import compute_image_pixel_hash
        img_hash = compute_image_pixel_hash(png_data)
        if not img_hash:
            img_hash = hashlib.sha256(png_data).hexdigest()

        # 4. Duplicate prevention: ignore duplicate image content across memory and database
        if img_hash == self._last_image_hash or self.database.has_image_hash(img_hash):
            self._last_image_hash = img_hash
            return

        logger.info(
            "Clipboard image captured: %dx%d (%d bytes, hash=%s...)",
            width,
            height,
            png_bytes_len,
            img_hash[:10],
        )
        self._last_image_hash = img_hash
        self._last_content = None

        item = self.database.add_image_item(png_data=png_data, image_hash=img_hash)
        if item and self.on_new_item:
            GLib.idle_add(self.on_new_item, item)

    def _on_read_text_finish(self, clipboard: Gdk.Clipboard, result) -> None:
        """Callback for completed async text read operation."""
        self._is_reading = False
        try:
            text = clipboard.read_text_finish(result)
        except Exception as e:
            logger.debug("Clipboard text read skipped or error: %s", e)
            return

        if text is None:
            return

        # Ignore empty or whitespace-only content
        if not text.strip():
            return

        # Duplicate prevention: ignore consecutive duplicate content
        if text == self._last_content:
            return

        logger.info("Clipboard item captured: %d characters", len(text))
        self._last_content = text
        self._last_image_hash = None

        item = self.database.add_item(content=text, content_type="text")
        if item and self.on_new_item:
            GLib.idle_add(self.on_new_item, item)

    def copy_text(self, text: str) -> None:
        """Copies text to the system clipboard and marks it as internal to prevent creating a duplicate record."""
        if not self._clipboard:
            display = Gdk.Display.get_default()
            if display:
                self._clipboard = display.get_clipboard()

        if not self._clipboard:
            logger.error("No GDK clipboard available to copy text")
            return

        # Cancel any in-flight async read to avoid stale results
        if self._cancellable:
            self._cancellable.cancel()
        self._cancellable = Gio.Cancellable()

        self._last_content = text
        self._last_image_hash = None
        self._clipboard.set(text)
        logger.info("Copied text item to clipboard: %d characters", len(text))

    def copy_image(self, image_path: str) -> None:
        """Copies the original stored PNG image to the system clipboard using GDK ContentProvider."""
        if not self._clipboard:
            display = Gdk.Display.get_default()
            if display:
                self._clipboard = display.get_clipboard()

        if not self._clipboard:
            logger.error("No GDK clipboard available to copy image")
            return

        p = pathlib.Path(image_path)
        if not p.exists():
            logger.error("Stored image file not found for copying: %s", image_path)
            return

        try:
            with open(p, "rb") as f:
                png_bytes = f.read()

            from clipboard.image_utils import compute_image_pixel_hash
            img_hash = compute_image_pixel_hash(png_bytes) or hashlib.sha256(png_bytes).hexdigest()

            # Cancel any in-flight async read to prevent race conditions
            if self._cancellable:
                self._cancellable.cancel()
            self._cancellable = Gio.Cancellable()

            self._last_image_hash = img_hash
            self._last_content = None

            # Provide both raw image/png bytes and native GdkTexture for comprehensive Wayland compatibility
            gbytes = GLib.Bytes.new(png_bytes)
            texture = Gdk.Texture.new_from_bytes(gbytes)

            cp_bytes = Gdk.ContentProvider.new_for_bytes("image/png", gbytes)
            val = GObject.Value(Gdk.Texture, texture)
            cp_val = Gdk.ContentProvider.new_for_value(val)
            cp_union = Gdk.ContentProvider.new_union([cp_bytes, cp_val])

            self._clipboard.set_content(cp_union)
            logger.info("Copied original image to clipboard: %s (%d bytes)", image_path, len(png_bytes))
        except Exception as e:
            logger.error("Failed to copy image to clipboard: %s", e)

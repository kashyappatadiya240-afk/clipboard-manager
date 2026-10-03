import hashlib
import io
import os
import pathlib
import sys
import unittest
from PIL import Image

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import ClipboardMonitor
from ui.clipboard_row import (
    ClipboardRow,
    get_thumbnail_texture,
    clear_thumbnail_cache,
    _THUMBNAIL_CACHE,
)
from ui.window import ClipboardWindow


def make_png(width: int, height: int, color: tuple = (100, 150, 200, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPhase9ImageFix(unittest.TestCase):
    def setUp(self):
        clear_thumbnail_cache()
        self.test_dir = pathlib.Path("/tmp/test_phase9_image_fix")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.test_dir / "test.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.db = ClipboardDatabase(db_path=self.db_path)
        self.db.initialize()

    def tearDown(self):
        clear_thumbnail_cache()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_image_file_storage_and_database(self):
        """Verifies PNG storage on disk and database image_path."""
        png_data = make_png(400, 300, (255, 0, 0, 255))
        img_hash = hashlib.sha256(png_data).hexdigest()
        item = self.db.add_image_item(png_data, img_hash)

        self.assertIsNotNone(item)
        self.assertEqual(item.content_type, "image")
        self.assertTrue(pathlib.Path(item.image_path).exists())

        # Verify database record
        items = self.db.get_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content_type, "image")
        self.assertEqual(items[0].image_path, item.image_path)
        self.assertEqual(items[0].image_hash, img_hash)

    def test_gdk_texture_creation_and_caching(self):
        """Verifies Gdk.Texture creation, aspect ratio capping, and caching."""
        # 800x400 image (2:1 aspect ratio)
        png_data = make_png(800, 400, (0, 255, 0, 255))
        img_hash = hashlib.sha256(png_data).hexdigest()
        item = self.db.add_image_item(png_data, img_hash)

        texture1 = get_thumbnail_texture(item.image_path, max_width=360, max_height=160)
        self.assertIsNotNone(texture1)
        self.assertIsInstance(texture1, Gdk.Texture)
        # 800x400 scaled down with max_w=360, max_h=160 -> 320x160
        self.assertEqual(texture1.get_width(), 320)
        self.assertEqual(texture1.get_height(), 160)

        # Cache check
        texture2 = get_thumbnail_texture(item.image_path)
        self.assertIs(texture1, texture2)

        # Cache eviction
        clear_thumbnail_cache(item.image_path)
        self.assertNotIn(item.image_path, _THUMBNAIL_CACHE)

    def test_gtk_picture_rendering_and_allocation(self):
        """Verifies Gtk.Picture configuration, non-zero size, and paintable assignment."""
        png_data = make_png(500, 250, (0, 0, 255, 255))
        img_hash = hashlib.sha256(png_data).hexdigest()
        item = self.db.add_image_item(png_data, img_hash)

        row = ClipboardRow(item)

        # Verify row attributes
        self.assertIsNotNone(row.picture)
        self.assertIsNotNone(row.texture)
        self.assertIs(row.picture.get_paintable(), row.texture)
        self.assertFalse(row.picture.get_can_shrink())

        # Preferred size must be non-zero
        min_sz, nat_sz = row.picture.get_preferred_size()
        self.assertGreater(min_sz.width, 0)
        self.assertGreater(min_sz.height, 0)
        self.assertEqual(min_sz.width, row.texture.get_width())
        self.assertEqual(min_sz.height, row.texture.get_height())

        # Verify real GTK allocation inside window
        win = Gtk.Window()
        list_box = Gtk.ListBox()
        list_box.append(row)
        win.set_child(list_box)
        win.set_default_size(540, 680)

        loop = GLib.MainLoop()

        def on_idle():
            w = row.picture.get_width()
            h = row.picture.get_height()
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertEqual(w, row.texture.get_width())
            self.assertEqual(h, row.texture.get_height())
            loop.quit()

        GLib.idle_add(on_idle)
        win.present()
        loop.run()
        win.destroy()

    def test_real_image_copy_behavior(self):
        """Verifies that activating an image row copies the original full-resolution image."""
        png_data = make_png(600, 600, (120, 120, 120, 255))
        img_hash = hashlib.sha256(png_data).hexdigest()
        item = self.db.add_image_item(png_data, img_hash)

        copied_images = []

        class DummyMonitor:
            def copy_image(self, path):
                copied_images.append(path)

            def copy_text(self, text):
                pass

        app = Adw.Application(
            application_id="com.kashyap.TestPhase9ImageCopy",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )

        dummy_monitor = DummyMonitor()
        win = ClipboardWindow(application=app, database=self.db, monitor=dummy_monitor)

        row = win.list_box.get_row_at_index(0)
        self.assertIsNotNone(row)
        self.assertEqual(row.item.content_type, "image")

        # Activate row (equivalent to clicking or Enter)
        win._on_row_activated(win.list_box, row)
        self.assertEqual(len(copied_images), 1)
        self.assertEqual(copied_images[0], item.image_path)

        # Verify original file content is unaltered
        with open(copied_images[0], "rb") as f:
            read_bytes = f.read()
        self.assertEqual(read_bytes, png_data)


if __name__ == "__main__":
    unittest.main()

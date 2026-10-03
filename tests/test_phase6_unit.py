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
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_HEIGHT,
    MAX_IMAGE_WIDTH,
    ClipboardMonitor,
)
from ui.clipboard_row import (
    ClipboardRow,
    clear_thumbnail_cache,
    get_thumbnail_texture,
)
from ui.window import ClipboardWindow


def create_test_png_bytes(
    width: int = 100,
    height: int = 80,
    color: tuple = (255, 100, 50, 255),
) -> bytes:
    """Helper to generate valid PNG bytes with specific dimensions and color."""
    img = Image.new("RGBA", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Phase6UnitTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = pathlib.Path("/tmp/test_phase6_unit")
        if self.test_dir.exists():
            import shutil

            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)
        self.db_path = self.test_dir / "clipboard.db"
        self.db = ClipboardDatabase(db_path=self.db_path)
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        clear_thumbnail_cache()

    def test_database_initialization_and_schema(self):
        """Verify schema has image_path, image_hash, and is_pinned."""
        cols = [
            c["name"]
            for c in self.db._conn.execute(
                "PRAGMA table_info(clipboard_items)"
            ).fetchall()
        ]
        self.assertIn("image_path", cols)
        self.assertIn("image_hash", cols)
        self.assertIn("is_pinned", cols)
        self.assertIn("content", cols)
        self.assertIn("content_type", cols)

    def test_add_image_item_lifecycle(self):
        """Verify image persistence saves file, updates DB, and populates ClipboardItem."""
        png_data = create_test_png_bytes(60, 40, (10, 20, 30, 255))
        img_hash = hashlib.sha256(png_data).hexdigest()

        item = self.db.add_image_item(png_data=png_data, image_hash=img_hash)
        self.assertIsNotNone(item)
        self.assertEqual(item.content_type, "image")
        self.assertIsNone(item.content)
        self.assertEqual(item.image_hash, img_hash)
        self.assertTrue(pathlib.Path(item.image_path).exists())

        # Verify saved file content matches original
        with open(item.image_path, "rb") as f:
            saved_bytes = f.read()
        self.assertEqual(saved_bytes, png_data)

    def test_image_ordering(self):
        """Verify pinned images/texts appear before unpinned in chronological order."""
        t1 = self.db.add_item("Text Normal 1")
        png1 = create_test_png_bytes(50, 50, (1, 1, 1, 255))
        i1 = self.db.add_image_item(png1, hashlib.sha256(png1).hexdigest())

        t2 = self.db.add_item("Text Normal 2")
        png2 = create_test_png_bytes(50, 50, (2, 2, 2, 255))
        i2 = self.db.add_image_item(
            png2, hashlib.sha256(png2).hexdigest(), is_pinned=True
        )

        items = self.db.get_items()
        self.assertEqual(len(items), 4)
        # Pinned item i2 must be first
        self.assertEqual(items[0].id, i2.id)
        self.assertTrue(items[0].is_pinned)
        # Remaining unpinned items ordered by id DESC
        self.assertEqual([it.id for it in items[1:]], [t2.id, i1.id, t1.id])

    def test_image_delete(self):
        """Verify deleting an image record removes both database entry and image file."""
        png_data = create_test_png_bytes(50, 50)
        img_hash = hashlib.sha256(png_data).hexdigest()
        item = self.db.add_image_item(png_data, img_hash)
        file_path = pathlib.Path(item.image_path)
        self.assertTrue(file_path.exists())

        deleted = self.db.delete_item(item.id)
        self.assertTrue(deleted)
        self.assertFalse(file_path.exists())
        self.assertEqual(len(self.db.get_items()), 0)

    def test_clear_history_preserves_pinned_image(self):
        """Verify Clear History keeps pinned text and pinned image while purging unpinned."""
        png_pinned = create_test_png_bytes(50, 50, (10, 10, 10, 255))
        i_pinned = self.db.add_image_item(
            png_pinned,
            hashlib.sha256(png_pinned).hexdigest(),
            is_pinned=True,
        )

        png_unpinned = create_test_png_bytes(50, 50, (20, 20, 20, 255))
        i_unpinned = self.db.add_image_item(
            png_unpinned,
            hashlib.sha256(png_unpinned).hexdigest(),
            is_pinned=False,
        )

        t_pinned = self.db.add_item("Pinned Text", is_pinned=True)
        t_unpinned = self.db.add_item("Unpinned Text", is_pinned=False)

        path_pinned = pathlib.Path(i_pinned.image_path)
        path_unpinned = pathlib.Path(i_unpinned.image_path)
        self.assertTrue(path_pinned.exists())
        self.assertTrue(path_unpinned.exists())

        deleted_count = self.db.clear_history()
        self.assertEqual(deleted_count, 2)

        # Unpinned image file must be deleted
        self.assertFalse(path_unpinned.exists())
        # Pinned image file must remain intact
        self.assertTrue(path_pinned.exists())

        remaining = self.db.get_items()
        self.assertEqual(len(remaining), 2)
        remaining_ids = {it.id for it in remaining}
        self.assertEqual(remaining_ids, {i_pinned.id, t_pinned.id})

    def test_orphan_cleanup(self):
        """Verify startup orphan cleanup removes unreferenced PNG files."""
        # Create an orphaned file in images dir
        orphan_file = self.db.images_dir / "9999_orphan.png"
        with open(orphan_file, "wb") as f:
            f.write(b"fake png data")
        self.assertTrue(orphan_file.exists())

        cleaned = self.db.cleanup_orphaned_images()
        self.assertEqual(cleaned, 1)
        self.assertFalse(orphan_file.exists())

    def test_thumbnail_generation_and_caching(self):
        """Verify thumbnail generation bounds aspect ratio and caches textures."""
        png_data = create_test_png_bytes(1920, 1080)
        img_hash = hashlib.sha256(png_data).hexdigest()
        item = self.db.add_image_item(png_data, img_hash)

        # 1. Generate thumbnail
        tex1 = get_thumbnail_texture(item.image_path, max_width=360, max_height=160)
        self.assertIsNotNone(tex1)
        self.assertEqual(tex1.get_height(), 160)
        self.assertEqual(tex1.get_width(), 284)

        # 2. Verify cached texture returned on subsequent lookup
        tex2 = get_thumbnail_texture(item.image_path, max_width=360, max_height=160)
        self.assertIs(tex1, tex2)

        # 3. Verify eviction
        clear_thumbnail_cache(item.image_path)
        tex3 = get_thumbnail_texture(item.image_path, max_width=360, max_height=160)
        self.assertIsNotNone(tex3)
        self.assertIsNot(tex1, tex3)

    def test_image_row_creation(self):
        """Verify ClipboardRow renders image thumbnail without raising errors."""
        png_data = create_test_png_bytes(100, 100)
        item = self.db.add_image_item(png_data, hashlib.sha256(png_data).hexdigest())
        row = ClipboardRow(item=item)
        self.assertEqual(row.type_label.get_text(), "IMAGE")
        self.assertFalse(hasattr(row, "preview_label"))


if __name__ == "__main__":
    unittest.main()

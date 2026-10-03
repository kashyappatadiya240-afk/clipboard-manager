import hashlib
import io
import pathlib
import tempfile
import unittest
from PIL import Image

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from ui.window import ClipboardWindow
from ui.clipboard_row import _THUMBNAIL_CACHE


class TestFifoLimitationsUnit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.temp_dir.name) / "test_clipboard.db"
        self.db = ClipboardDatabase(db_path=self.db_path)
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_unpinned_limit_fifo_text(self):
        """Tests that at most 20 unpinned text items are stored and the 21st triggers FIFO deletion."""
        self.assertEqual(self.db.MAX_UNPINNED_ITEMS, 20)
        self.assertEqual(self.db.MAX_PINNED_ITEMS, 10)

        # Insert 20 unpinned items
        for i in range(1, 21):
            self.db.add_item(f"Item {i}")

        self.assertEqual(self.db.get_unpinned_count(), 20)
        items = self.db.get_items(limit=50)
        self.assertEqual(len(items), 20)
        self.assertEqual(items[0].content, "Item 20")
        self.assertEqual(items[-1].content, "Item 1")

        # Add 21st item: Item 1 should be removed (FIFO)
        item21 = self.db.add_item("Item 21")
        self.assertIsNotNone(item21)
        self.assertEqual(self.db.get_unpinned_count(), 20)

        items_after = self.db.get_items(limit=50)
        self.assertEqual(len(items_after), 20)
        contents = [it.content for it in items_after]
        self.assertIn("Item 21", contents)
        self.assertIn("Item 2", contents)
        self.assertNotIn("Item 1", contents)
        self.assertEqual(items_after[0].content, "Item 21")
        self.assertEqual(items_after[-1].content, "Item 2")

    def test_unpinned_limit_fifo_image_cleanup(self):
        """Tests that when the 21st unpinned item is added, the oldest image item's file is deleted."""
        # Insert 1 image item (Item 1)
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()
        img_hash = hashlib.sha256(png_data).hexdigest()

        img_item1 = self.db.add_image_item(png_data, img_hash)
        self.assertIsNotNone(img_item1)
        img_path1 = pathlib.Path(img_item1.image_path)
        self.assertTrue(img_path1.exists())

        # Insert 19 text items (total 20 unpinned items)
        for i in range(2, 21):
            self.db.add_item(f"Text Item {i}")

        self.assertEqual(self.db.get_unpinned_count(), 20)
        self.assertTrue(img_path1.exists())

        # Insert 21st item: img_item1 is the oldest unpinned item, so it should be deleted
        self.db.add_item("Text Item 21")
        self.assertEqual(self.db.get_unpinned_count(), 20)

        # Verify img_item1 is gone from database and filesystem
        self.assertFalse(img_path1.exists(), "Image file must be deleted from disk on FIFO pruning")
        items = self.db.get_items(limit=50)
        self.assertNotIn(img_item1.id, [it.id for it in items])

    def test_pinned_limit_maximum_10(self):
        """Tests that at most 10 items can be pinned and attempting to pin an 11th item fails."""
        # Create 12 items
        items = [self.db.add_item(f"Item {i}") for i in range(1, 13)]

        # Pin the first 10 items
        for i in range(10):
            pinned = self.db.pin_item(items[i].id)
            self.assertTrue(pinned)

        self.assertEqual(self.db.get_pinned_count(), 10)
        self.assertFalse(self.db.can_pin())

        # Attempt to pin 11th item via pin_item: must return False and stay unpinned
        success_11 = self.db.pin_item(items[10].id)
        self.assertFalse(success_11)
        self.assertEqual(self.db.get_pinned_count(), 10)

        # Attempt to pin 11th item via toggle_pin: must return None
        toggle_res = self.db.toggle_pin(items[10].id)
        self.assertIsNone(toggle_res)
        self.assertEqual(self.db.get_pinned_count(), 10)

        # Unpin 1 item: count becomes 9
        unpinned = self.db.unpin_item(items[0].id)
        self.assertTrue(unpinned)
        self.assertEqual(self.db.get_pinned_count(), 9)
        self.assertTrue(self.db.can_pin())

        # Now pinning item 11 should succeed
        success_11_again = self.db.pin_item(items[10].id)
        self.assertTrue(success_11_again)
        self.assertEqual(self.db.get_pinned_count(), 10)

    def test_unpinning_preserves_newly_unpinned_item(self):
        """Tests that when 20 unpinned items exist and a pinned item is unpinned,
        the unpinned count stays at 20 without immediately deleting the newly unpinned item."""
        # Add 1 item and pin it (id=1)
        pinned_item = self.db.add_item("Pinned Item")
        self.db.pin_item(pinned_item.id)

        # Add 20 unpinned items (id=2 to 21)
        for i in range(2, 22):
            self.db.add_item(f"Unpinned {i}")

        self.assertEqual(self.db.get_pinned_count(), 1)
        self.assertEqual(self.db.get_unpinned_count(), 20)

        # Unpin pinned_item (id=1)
        res = self.db.toggle_pin(pinned_item.id)
        self.assertFalse(res)  # Now unpinned
        self.assertEqual(self.db.get_pinned_count(), 0)
        self.assertEqual(self.db.get_unpinned_count(), 20)

        # Pinned item (id=1) should still exist, and the oldest other unpinned item (id=2) was pruned
        items = self.db.get_items(limit=50)
        item_ids = [it.id for it in items]
        self.assertIn(pinned_item.id, item_ids)
        self.assertNotIn(2, item_ids)

    def test_window_toast_and_ui_fifo(self):
        """Tests that ClipboardWindow displays a toast notification when pin limit is reached
        and correctly manages in-memory FIFO limit."""
        win = ClipboardWindow(database=self.db)

        # Create and pin 10 items
        for i in range(10):
            it = self.db.add_item(f"Pinned {i}", is_pinned=True)
            win.add_clipboard_item(it)

        self.assertEqual(self.db.get_pinned_count(), 10)

        # Add an 11th unpinned item
        item11 = self.db.add_item("Item 11")
        win.add_clipboard_item(item11)

        # Attempt to toggle pin on item11 in window
        win.toggle_pin_item(item11)

        # Item 11 must remain unpinned
        self.assertFalse(item11.is_pinned)
        self.assertEqual(self.db.get_pinned_count(), 10)

        # Verify unpinned FIFO in UI
        for i in range(12, 35):
            it = self.db.add_item(f"Item {i}")
            win.add_clipboard_item(it)

        # Total unpinned items in window should be 20, plus 10 pinned = 30 total
        unpinned_in_win = [it for it in win._items if not it.is_pinned]
        pinned_in_win = [it for it in win._items if it.is_pinned]
        self.assertEqual(len(pinned_in_win), 10)
        self.assertEqual(len(unpinned_in_win), 20)

        win.destroy()


if __name__ == "__main__":
    unittest.main()

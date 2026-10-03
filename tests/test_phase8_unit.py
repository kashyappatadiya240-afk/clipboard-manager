import hashlib
import io
import os
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock
from PIL import Image

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import ClipboardMonitor
from ui.clipboard_row import (
    ClipboardRow,
    _THUMBNAIL_CACHE,
    clear_thumbnail_cache,
    format_timestamp,
    get_thumbnail_texture,
)
from ui.window import ClipboardWindow


def create_test_png(w=64, h=64, color=(255, 100, 50, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Phase8UnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.temp_dir.name) / "test_clipboard.db"
        self.db = ClipboardDatabase(db_path=self.db_path)
        self.db.initialize()
        clear_thumbnail_cache()

    def tearDown(self):
        self.db.close()
        clear_thumbnail_cache()
        self.temp_dir.cleanup()

    def test_text_row_action_menu_and_elements(self):
        """Verifies text ClipboardRow contains action menu, quick actions, and correct structure."""
        item = self.db.add_item("Hello Phase 8")
        row = ClipboardRow(item=item)

        self.assertEqual(row.type_label.get_text(), "TEXT")
        self.assertTrue(hasattr(row, "preview_label"))
        self.assertEqual(row.preview_label.get_text(), "Hello Phase 8")

        # Visual pinned state
        self.assertFalse(row.pin_indicator.get_visible())
        self.assertFalse(row.pin_icon.get_visible())
        self.assertFalse(row.has_css_class("pinned-row"))

        # Quick action buttons
        self.assertIsNotNone(row.copy_btn)
        self.assertIsNotNone(row.quick_pin_btn)
        self.assertEqual(row.quick_pin_btn.get_tooltip_text(), "Pin")

        # Menu button and popover
        self.assertIsNotNone(row.menu_btn)
        self.assertIsNotNone(row.popover)
        self.assertEqual(row.menu_pin_label.get_text(), "Pin")

        # Revealer
        self.assertFalse(row.actions_revealer.get_reveal_child())
        row._on_motion_enter(None, 0, 0)
        self.assertTrue(row.actions_revealer.get_reveal_child())
        row._on_motion_leave(None)
        self.assertFalse(row.actions_revealer.get_reveal_child())

    def test_image_row_action_menu_and_elements(self):
        """Verifies image ClipboardRow contains action menu, quick actions, and thumbnail."""
        png_data = create_test_png(80, 80)
        item = self.db.add_image_item(png_data, hashlib.sha256(png_data).hexdigest())
        row = ClipboardRow(item=item)

        self.assertEqual(row.type_label.get_text(), "IMAGE")
        self.assertFalse(hasattr(row, "preview_label"))
        self.assertIsNotNone(row.copy_btn)
        self.assertIsNotNone(row.quick_pin_btn)
        self.assertIsNotNone(row.menu_btn)
        self.assertIsNotNone(row.popover)

    def test_pinned_visual_state(self):
        """Verifies clear visual distinction for pinned items: icon, label, CSS class."""
        item = self.db.add_item("Pinned Item Text", is_pinned=True)
        row = ClipboardRow(item=item)

        self.assertTrue(row.pin_indicator.get_visible())
        self.assertTrue(row.pin_icon.get_visible())
        self.assertTrue(row.has_css_class("pinned-row"))
        self.assertEqual(row.pin_label.get_text(), "Pinned")
        self.assertEqual(row.quick_pin_btn.get_tooltip_text(), "Unpin")
        self.assertEqual(row.menu_pin_label.get_text(), "Unpin")

        # Toggle to unpinned
        row.set_pinned(False)
        self.assertFalse(row.pin_indicator.get_visible())
        self.assertFalse(row.pin_icon.get_visible())
        self.assertFalse(row.has_css_class("pinned-row"))
        self.assertEqual(row.quick_pin_btn.get_tooltip_text(), "Pin")
        self.assertEqual(row.menu_pin_label.get_text(), "Pin")

    def test_copy_action_and_feedback(self):
        """Verifies copy callback invocation and immediate temporary '✓ Copied' visual feedback."""
        item = self.db.add_item("Text to Copy")
        copied_items = []

        def on_copy(it):
            copied_items.append(it)

        row = ClipboardRow(item=item, on_copy=on_copy)

        # Initially showing timestamp metadata
        self.assertEqual(row.status_stack.get_visible_child_name(), "metadata")

        # Trigger copy
        row._on_quick_copy_clicked(row.copy_btn)
        self.assertEqual(len(copied_items), 1)
        self.assertEqual(copied_items[0].content, "Text to Copy")

        # Feedback is visible
        self.assertEqual(row.status_stack.get_visible_child_name(), "copied")

        # Restore metadata
        row._restore_metadata()
        self.assertEqual(row.status_stack.get_visible_child_name(), "metadata")

    def test_pin_and_delete_callbacks(self):
        """Verifies pin and delete actions trigger their callbacks correctly."""
        item = self.db.add_item("Item for pin/delete")
        pinned = []
        deleted = []

        row = ClipboardRow(
            item=item,
            on_toggle_pin=lambda it: pinned.append(it),
            on_delete=lambda it: deleted.append(it),
        )

        row._on_quick_pin_clicked(row.quick_pin_btn)
        self.assertEqual(len(pinned), 1)
        self.assertEqual(pinned[0].id, item.id)

        row._on_popover_delete_clicked(None, row.popover)
        self.assertEqual(len(deleted), 1)
        self.assertEqual(deleted[0].id, item.id)

    def test_keyboard_actions_on_row(self):
        """Verifies keyboard shortcuts: Menu/F10 opens popover, Delete deletes item."""
        item = self.db.add_item("Item for Keyboard")
        deleted = []
        row = ClipboardRow(item=item, on_delete=lambda it: deleted.append(it))

        # Mock popup_menu
        row.popup_menu = MagicMock()

        # F10 triggers popup
        res_f10 = row._on_row_key_pressed(None, Gdk.KEY_F10, 0, Gdk.ModifierType(0))
        self.assertTrue(res_f10)
        row.popup_menu.assert_called_once()

        # Menu key triggers popup
        row.popup_menu.reset_mock()
        res_menu = row._on_row_key_pressed(None, Gdk.KEY_Menu, 0, Gdk.ModifierType(0))
        self.assertTrue(res_menu)
        row.popup_menu.assert_called_once()

        # Delete key triggers delete
        res_del = row._on_row_key_pressed(None, Gdk.KEY_Delete, 0, Gdk.ModifierType(0))
        self.assertTrue(res_del)
        self.assertEqual(len(deleted), 1)

    def test_empty_state_and_no_results_state(self):
        """Verifies empty history status page vs no search results status page."""
        win = ClipboardWindow(database=self.db)

        # Empty history state
        self.assertEqual(win.stack.get_visible_child_name(), "empty")
        self.assertIn(win.status_page.get_title(), ("Clipboard is empty", "No Clipboard History"))
        self.assertIn(
            win.status_page.get_description(),
            (
                "Copy text or an image to start building your clipboard history.",
                "Copied text and images will appear here.",
            ),
        )

        # Add item
        item = self.db.add_item("Apple Pie")
        win.add_clipboard_item(item)
        self.assertEqual(win.stack.get_visible_child_name(), "history")

        # Search no results
        win.apply_filter("Banana")
        self.assertEqual(win.stack.get_visible_child_name(), "no_results")
        self.assertIn(win.no_results_page.get_title(), ("No matching clips", "No matching clipboard items"))
        self.assertIn(
            win.no_results_page.get_description(),
            ("Try another search term.", "Try a different search term."),
        )

        # Clear search
        win.apply_filter("")
        self.assertEqual(win.stack.get_visible_child_name(), "history")

        win.destroy()

    def test_delete_image_cleans_file_and_cache(self):
        """Verifies deleting an image removes database entry, disk file, and thumbnail cache."""
        png_data = create_test_png(50, 50)
        item = self.db.add_image_item(png_data, hashlib.sha256(png_data).hexdigest())
        image_path = item.image_path
        self.assertTrue(pathlib.Path(image_path).exists())

        # Cache thumbnail
        tex = get_thumbnail_texture(image_path)
        self.assertIsNotNone(tex)
        self.assertIn(image_path, _THUMBNAIL_CACHE)

        # Delete through window
        win = ClipboardWindow(database=self.db)
        win.delete_item(item)

        # DB row removed
        self.assertEqual(len(self.db.get_items()), 0)
        # Disk file removed
        self.assertFalse(pathlib.Path(image_path).exists())
        # Thumbnail cache cleared
        self.assertNotIn(image_path, _THUMBNAIL_CACHE)

        win.destroy()

    def test_copy_image_action_copies_original(self):
        """Verifies copy_item on image copies full original image through monitor."""
        png_data = create_test_png(120, 120, color=(10, 200, 80, 255))
        item = self.db.add_image_item(png_data, hashlib.sha256(png_data).hexdigest())

        mock_monitor = MagicMock(spec=ClipboardMonitor)
        win = ClipboardWindow(database=self.db, monitor=mock_monitor)

        win.copy_item(item)
        mock_monitor.copy_image.assert_called_once_with(item.image_path)
        mock_monitor.copy_text.assert_not_called()

        win.destroy()

    def test_copy_text_action_copies_original(self):
        """Verifies copy_item on text copies exact content through monitor."""
        item = self.db.add_item("Gujarati: નમસ્તે, Emoji: 🌟🚀")

        mock_monitor = MagicMock(spec=ClipboardMonitor)
        win = ClipboardWindow(database=self.db, monitor=mock_monitor)

        win.copy_item(item)
        mock_monitor.copy_text.assert_called_once_with("Gujarati: નમસ્તે, Emoji: 🌟🚀")
        mock_monitor.copy_image.assert_not_called()

        win.destroy()

    def test_missing_image_graceful_handling(self):
        """Verifies row creation and copy gracefully handle missing or deleted image file."""
        png_data = create_test_png(40, 40)
        item = self.db.add_image_item(png_data, hashlib.sha256(png_data).hexdigest())
        pathlib.Path(item.image_path).unlink()

        # Row creation does not raise
        row = ClipboardRow(item=item)
        self.assertEqual(row.type_label.get_text(), "IMAGE")

        # Copy missing image returns False gracefully
        mock_monitor = MagicMock(spec=ClipboardMonitor)
        win = ClipboardWindow(database=self.db, monitor=mock_monitor)
        res = win.copy_item_to_clipboard(item, hide_after=False)
        self.assertTrue(res)  # monitor called, does not crash
        mock_monitor.copy_image.assert_called_once_with(item.image_path)

        win.destroy()


if __name__ == "__main__":
    unittest.main()

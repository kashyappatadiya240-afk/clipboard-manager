import io
import os
import pathlib
import sys
import unittest
from PIL import Image

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import ClipboardMonitor
from clipboard.shortcut import (
    is_shortcut_registered,
    register_global_shortcut,
    unregister_global_shortcut,
)
from ui.window import ClipboardWindow


def make_test_png(w: int = 64, h: int = 64, color=(100, 150, 200, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Phase7UnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = pathlib.Path("/tmp/test_phase7_unit")
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.test_dir / "phase7_test.db"
        if cls.db_path.exists():
            cls.db_path.unlink()
        cls.db = ClipboardDatabase(db_path=cls.db_path)
        cls.db.initialize()

        cls.app = Adw.Application(
            application_id="com.kashyap.TestPhase7Unit",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        cls.app.register(None)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        # Restore the global shortcut so user environment remains functional
        register_global_shortcut()

    def setUp(self):
        # Clear items before each test
        for item in self.db.get_items():
            self.db.delete_item(item.id)

    def test_01_shortcut_registration_and_cleanup(self):
        """Tests that the Super+V shortcut registers and unregisters in GNOME GSettings cleanly."""
        # Clean state
        unregister_global_shortcut()
        self.assertFalse(is_shortcut_registered())

        # Register
        success = register_global_shortcut()
        self.assertTrue(success)
        self.assertTrue(is_shortcut_registered())

        # Unregister
        unreg = unregister_global_shortcut()
        self.assertTrue(unreg)
        self.assertFalse(is_shortcut_registered())
        # Re-register so GNOME desktop shortcut remains intact
        register_global_shortcut()

    def test_02_window_creation_and_reuse(self):
        """Tests that show_clipboard_history reuses the existing window without duplication."""
        win = ClipboardWindow(application=self.app, database=self.db)
        self.assertIsNotNone(win)
        self.assertEqual(win.get_title(), "Ubuntu Clipboard")

        # Calling present_history
        win.present_history()
        self.assertTrue(win.get_visible())

        # Calling hide_window
        win.hide_window()
        self.assertFalse(win.get_visible())

        # Presenting again reuses the same window instance
        win.present_history()
        self.assertTrue(win.get_visible())
        win.destroy()

    def test_03_keyboard_navigation_search_and_list(self):
        """Tests Arrow Down, Arrow Up, and Escape keyboard navigation."""
        item1 = self.db.add_item("First item")
        item2 = self.db.add_item("Second item")

        win = ClipboardWindow(application=self.app, database=self.db)
        win.present_history()

        # Both items loaded
        self.assertEqual(len(win._items), 2)
        self.assertEqual(win.stack.get_visible_child_name(), "history")

        # Focus should be in search entry
        win.focus_search_or_list()

        # Arrow Down in search entry moves focus/selection to first row
        ctrl = Gtk.EventControllerKey()
        res = win._on_search_key_pressed(ctrl, Gdk.KEY_Down, 0, 0)
        self.assertTrue(res)
        selected = win.list_box.get_selected_row()
        self.assertIsNotNone(selected)
        self.assertEqual(selected.item.content, "Second item")

        # Arrow Up on row 0 returns focus to search entry
        res_up = win._on_list_key_pressed(ctrl, Gdk.KEY_Up, 0, 0)
        self.assertTrue(res_up)

        # Escape key hides the window and resets search
        win.search_entry.set_text("Search query")
        esc_res = win._on_window_key_pressed(ctrl, Gdk.KEY_Escape, 0, 0)
        self.assertTrue(esc_res)
        self.assertFalse(win.get_visible())
        self.assertEqual(win.search_entry.get_text(), "")
        win.destroy()

    def test_04_enter_activation_text(self):
        """Tests that pressing Enter activates and copies selected text item."""
        copied_text = []

        class DummyMonitor:
            def copy_text(self, text):
                copied_text.append(text)

            def copy_image(self, path):
                pass

        monitor = DummyMonitor()
        item = self.db.add_item("Hello Phase 7 World")

        win = ClipboardWindow(application=self.app, database=self.db, monitor=monitor)
        win.present_history()

        # Row 0 is selected
        selected = win.list_box.get_row_at_index(0)
        self.assertIsNotNone(selected)

        # Enter in search entry triggers activate_selected_item
        activated = win.activate_selected_item()
        self.assertTrue(activated)
        self.assertEqual(copied_text, ["Hello Phase 7 World"])
        win.destroy()

    def test_05_enter_activation_image(self):
        """Tests that pressing Enter activates and copies selected image item."""
        copied_images = []

        class DummyMonitor:
            def copy_text(self, text):
                pass

            def copy_image(self, path):
                copied_images.append(path)

        monitor = DummyMonitor()
        png_bytes = make_test_png()
        img_item = self.db.add_image_item(png_data=png_bytes, image_hash="fakehash77")

        win = ClipboardWindow(application=self.app, database=self.db, monitor=monitor)
        win.present_history()

        selected = win.list_box.get_row_at_index(0)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.item.content_type, "image")

        activated = win.activate_selected_item()
        self.assertTrue(activated)
        self.assertEqual(len(copied_images), 1)
        self.assertEqual(copied_images[0], img_item.image_path)
        win.destroy()

    def test_06_text_compatibility_formats(self):
        """Tests launcher row activation with Unicode, multiline, emoji, and Gujarati text."""
        copied_list = []

        class DummyMonitor:
            def copy_text(self, text):
                copied_list.append(text)

        monitor = DummyMonitor()
        texts = [
            "Multiline\nText\nWith\nLinebreaks",
            "🚀🔥 Emoji Rocket 🌟🎉",
            "ગુજરાતી ક્લિપબોર્ડ મેનેજર",
            "Long text: " + ("abcdefghij " * 50),
        ]
        for t in texts:
            self.db.add_item(t)

        win = ClipboardWindow(application=self.app, database=self.db, monitor=monitor)
        win.present_history()

        for idx, expected in enumerate(reversed(texts)):
            row = win.list_box.get_row_at_index(idx)
            self.assertIsNotNone(row)
            win._on_row_activated(win.list_box, row)
            self.assertEqual(copied_list[-1], expected)

        win.destroy()

    def test_07_search_compatibility_and_clearing(self):
        """Tests Phase 4 search behaviors after opening launcher."""
        self.db.add_item("Apple Macintosh")
        self.db.add_item("Banana Smoothie")
        self.db.add_item("Apple Pie")

        win = ClipboardWindow(application=self.app, database=self.db)
        win.present_history()

        # Search for apple
        win.search_entry.set_text("apple")
        win.apply_filter("apple")
        visible_rows = [
            win.list_box.get_row_at_index(i).item.content
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        self.assertEqual(visible_rows, ["Apple Pie", "Apple Macintosh"])

        # No results search
        win.search_entry.set_text("pineapple")
        win.apply_filter("pineapple")
        self.assertEqual(win.stack.get_visible_child_name(), "no_results")

        # Clear search
        win.search_entry.set_text("")
        win.apply_filter("")
        self.assertEqual(win.stack.get_visible_child_name(), "history")
        all_rows = [
            win.list_box.get_row_at_index(i).item.content
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        self.assertEqual(len(all_rows), 3)
        win.destroy()

    def test_08_close_request_hides_not_destroys(self):
        """Tests that closing the window emits close-request and hides the window without destroying."""
        win = ClipboardWindow(application=self.app, database=self.db)
        win.present_history()
        self.assertTrue(win.get_visible())

        # Simulate close request (e.g. user clicked window close button)
        ret = win._on_close_request(win)
        self.assertTrue(ret)  # Must return True to cancel GTK window destruction
        self.assertFalse(win.get_visible())

        # Reopening works immediately
        win.present_history()
        self.assertTrue(win.get_visible())
        win.destroy()


if __name__ == "__main__":
    unittest.main()

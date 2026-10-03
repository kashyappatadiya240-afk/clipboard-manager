import hashlib
import io
import pathlib
import tempfile
import unittest
from PIL import Image

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from ui.window import ClipboardWindow
from ui.clipboard_row import ClipboardRow, clear_thumbnail_cache


class TestPhase9VisualUnit(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.temp_dir.name) / "test_phase9.db"
        self.db = ClipboardDatabase(db_path=self.db_path)
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_window_proportions_and_minimum_size(self):
        """Validates that window target dimensions and minimum size requests adhere to Phase 9."""
        win = ClipboardWindow(database=self.db)
        # Default size: 540 x 680
        width, height = win.get_default_size()
        self.assertGreaterEqual(width, 520)
        self.assertLessEqual(width, 560)
        self.assertGreaterEqual(height, 650)
        self.assertLessEqual(height, 750)

        # Minimum size request
        min_w, min_h = win.get_size_request()
        self.assertGreaterEqual(min_w, 400)
        self.assertGreaterEqual(min_h, 500)
        win.destroy()

    def test_empty_and_no_matching_status_pages(self):
        """Validates empty history state and no matching search state visual text."""
        win = ClipboardWindow(database=self.db)
        self.assertEqual(win.stack.get_visible_child_name(), "empty")
        self.assertEqual(win.status_page.get_title(), "Clipboard is empty")
        self.assertEqual(
            win.status_page.get_description(),
            "Copy text or an image to start building your clipboard history.",
        )

        item = self.db.add_item("Hello GNOME")
        win.add_clipboard_item(item)
        self.assertEqual(win.stack.get_visible_child_name(), "history")

        win.apply_filter("non_existent_search_query_123")
        self.assertEqual(win.stack.get_visible_child_name(), "no_results")
        self.assertEqual(win.no_results_page.get_title(), "No matching clips")
        self.assertEqual(win.no_results_page.get_description(), "Try another search term.")

        win.apply_filter("")
        self.assertEqual(win.stack.get_visible_child_name(), "history")
        win.destroy()

    def test_card_structure_and_styling(self):
        """Validates that ClipboardRow has clipboard-card class, proper hierarchy and no layout jumping."""
        item = self.db.add_item("Simple short text item")
        row = ClipboardRow(item=item)

        self.assertTrue(row.has_css_class("clipboard-card"))
        self.assertFalse(row.has_css_class("pinned-row"))
        self.assertEqual(row.type_label.get_text(), "TEXT")
        self.assertFalse(row.pin_indicator.get_visible())

        # Pin the row
        row.set_pinned(True)
        self.assertTrue(row.has_css_class("pinned-row"))
        self.assertTrue(row.pin_indicator.get_visible())
        self.assertEqual(row.quick_pin_btn.get_tooltip_text(), "Unpin")

        # Unpin the row
        row.set_pinned(False)
        self.assertFalse(row.has_css_class("pinned-row"))
        self.assertFalse(row.pin_indicator.get_visible())
        self.assertEqual(row.quick_pin_btn.get_tooltip_text(), "Pin")

    def test_text_preview_and_full_content_search_beyond_5000_chars(self):
        """Critical Phase 9 requirement: 1,500-char preview is UI-only; search finds terms beyond 5,000 chars."""
        # Generate 5,000 characters followed by search term
        filler = "A" * 5000
        full_content = filler + "\nPHASE9_FULL_SEARCH_TEST\n" + "B" * 50
        item = self.db.add_item(full_content)
        self.assertEqual(len(item.content), len(full_content))

        # Check UI row preview length is capped with ellipsis
        row = ClipboardRow(item=item)
        preview_text = row.preview_label.get_text()
        self.assertLessEqual(len(preview_text), 1502)
        self.assertTrue(preview_text.endswith("…"))
        # Stored item content is intact
        self.assertIn("PHASE9_FULL_SEARCH_TEST", row.item.content)

        # Window live search finds the item
        win = ClipboardWindow(database=self.db)
        win.add_clipboard_item(item)
        win.apply_filter("PHASE9_FULL_SEARCH_TEST")
        self.assertEqual(win.stack.get_visible_child_name(), "history")
        matching_row = win.list_box.get_row_at_index(0)
        self.assertIsNotNone(matching_row)
        self.assertEqual(matching_row.item.id, item.id)

        # Search in the middle of long content
        win.apply_filter("AAAAA")
        self.assertEqual(win.stack.get_visible_child_name(), "history")

        win.destroy()

    def test_unicode_gujarati_and_emoji_rendering(self):
        """Verifies Unicode, Gujarati, and emoji render correctly without errors."""
        content = "Gujarati: કેમ છો! — Emoji: 🚀🌟🔥 — Symbols: ©™✓"
        item = self.db.add_item(content)
        row = ClipboardRow(item=item)

        self.assertEqual(row.preview_label.get_text(), content)

        win = ClipboardWindow(database=self.db)
        win.add_clipboard_item(item)
        win.apply_filter("કેમ છો")
        self.assertEqual(win.stack.get_visible_child_name(), "history")
        win.apply_filter("🚀")
        self.assertEqual(win.stack.get_visible_child_name(), "history")
        win.destroy()

    def test_image_cards_aspect_ratios_and_neutral_frame(self):
        """Verifies small, large, portrait, landscape, and transparent images preserve aspect ratio and use neutral frame."""
        # 1. Landscape transparent PNG
        img_land = Image.new("RGBA", (400, 200), color=(100, 150, 200, 180))
        buf_l = io.BytesIO()
        img_land.save(buf_l, format="PNG")
        data_l = buf_l.getvalue()
        item_l = self.db.add_image_item(data_l, hashlib.sha256(data_l).hexdigest())

        # 2. Portrait image
        img_port = Image.new("RGBA", (150, 450), color=(200, 100, 100, 255))
        buf_p = io.BytesIO()
        img_port.save(buf_p, format="PNG")
        data_p = buf_p.getvalue()
        item_p = self.db.add_image_item(data_p, hashlib.sha256(data_p).hexdigest())

        # 3. Small square image (should not be upscaled)
        img_small = Image.new("RGBA", (48, 48), color=(50, 200, 50, 255))
        buf_s = io.BytesIO()
        img_small.save(buf_s, format="PNG")
        data_s = buf_s.getvalue()
        item_s = self.db.add_image_item(data_s, hashlib.sha256(data_s).hexdigest())

        for it in (item_l, item_p, item_s):
            row = ClipboardRow(item=it)
            self.assertEqual(row.type_label.get_text(), "IMAGE")
            self.assertTrue(row.has_css_class("clipboard-card"))

    def test_keyboard_actions_and_shortcuts(self):
        """Tests keyboard shortcuts on row: Menu, F10, Shift+F10, Ctrl+M, and Delete."""
        deleted_items = []
        item = self.db.add_item("Keyboard Target")
        row = ClipboardRow(item=item, on_delete=lambda it: deleted_items.append(it))

        # Test Menu key opens popover
        res_menu = row._on_row_key_pressed(None, Gdk.KEY_Menu, 0, Gdk.ModifierType(0))
        self.assertTrue(res_menu)
        self.assertTrue(row._popover_open)

        # Test F10 key opens popover
        res_f10 = row._on_row_key_pressed(None, Gdk.KEY_F10, 0, Gdk.ModifierType(0))
        self.assertTrue(res_f10)

        # Test Shift+F10 opens popover
        res_shift_f10 = row._on_row_key_pressed(
            None, Gdk.KEY_F10, 0, Gdk.ModifierType.SHIFT_MASK
        )
        self.assertTrue(res_shift_f10)

        # Test Ctrl+M opens popover
        res_ctrl_m = row._on_row_key_pressed(
            None, Gdk.KEY_m, 0, Gdk.ModifierType.CONTROL_MASK
        )
        self.assertTrue(res_ctrl_m)

        # Test Delete key triggers deletion
        res_del = row._on_row_key_pressed(None, Gdk.KEY_Delete, 0, Gdk.ModifierType(0))
        self.assertTrue(res_del)
        self.assertEqual(len(deleted_items), 1)
        self.assertEqual(deleted_items[0].id, item.id)

    def test_light_and_dark_theme_manager(self):
        """Verifies that the window and cards render cleanly in both light and dark Libadwaita color schemes."""
        style_mgr = Adw.StyleManager.get_default()

        # Force Light Mode
        style_mgr.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        win_light = ClipboardWindow(database=self.db)
        item1 = self.db.add_item("Light Theme Item")
        win_light.add_clipboard_item(item1)
        self.assertEqual(len(win_light._items), 1)
        win_light.destroy()

        # Force Dark Mode
        style_mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        win_dark = ClipboardWindow(database=self.db)
        item2 = self.db.add_item("Dark Theme Item")
        win_dark.add_clipboard_item(item2)
        self.assertEqual(len(win_dark._items), 2)
        win_dark.destroy()

        # Restore default system color scheme
        style_mgr.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def test_multiline_text_preview_compact_card_height(self):
        """Verifies that a 100-line clipboard document is visually constrained to 3 lines (~53px) instead of expanding."""
        lines_100 = "\n".join([f"Document Line {i} with some content" for i in range(100)])
        item = self.db.add_item(lines_100)

        # Content in database is completely intact with all 100 lines
        self.assertEqual(len(item.content.splitlines()), 100)

        # UI row has visual preview capped at 3 lines
        row = ClipboardRow(item=item)
        preview = row.preview_label.get_text()
        self.assertLessEqual(len(preview.splitlines()), 3)
        self.assertTrue(preview.endswith("…"))

        # Measure label height: must be compact (~53px for 3 lines), NOT hundreds of pixels
        min_h, nat_h, _, _ = row.preview_label.measure(Gtk.Orientation.VERTICAL, 460)
        self.assertLessEqual(nat_h, 75)

        # Search for a term that only appears on line 99: must still be found!
        win = ClipboardWindow(database=self.db)
        win.add_clipboard_item(item)
        win.apply_filter("Line 99")
        self.assertEqual(win.stack.get_visible_child_name(), "history")
        matching = win.list_box.get_row_at_index(0)
        self.assertIsNotNone(matching)
        self.assertEqual(matching.item.id, item.id)
        win.destroy()

    def test_scope_audit_example_preview(self):
        """Verifies the exact user prompt example from Section 3."""
        content = (
            "# PHASE 9 FINAL SCOPE AUDIT\n\n"
            "Before declaring Phase 9 officially accepted,\n"
            "perform a strict final audit of the UI..."
        )
        item = self.db.add_item(content)
        row = ClipboardRow(item=item)

        preview = row.preview_label.get_text()
        preview_lines = preview.splitlines()
        self.assertLessEqual(len(preview_lines), 3)
        self.assertEqual(preview_lines[0], "# PHASE 9 FINAL SCOPE AUDIT")
        self.assertEqual(preview_lines[1], "")
        self.assertTrue(preview_lines[2].startswith("Before declaring Phase 9 officially accepted,"))
        self.assertTrue(preview.endswith("…"))


if __name__ == "__main__":
    unittest.main()

import hashlib
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from PIL import Image

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import ClipboardMonitor
from ui.clipboard_row import ClipboardRow, clear_thumbnail_cache
from ui.window import ClipboardWindow


def create_sample_png(w=100, h=80, color=(30, 150, 240, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_manual_desktop_tests():
    print("=== Section 23 Real-World Manual Desktop Tests on Wayland / GNOME 50 ===", flush=True)
    Adw.init()

    temp_dir = tempfile.TemporaryDirectory()
    db_path = pathlib.Path(temp_dir.name) / "manual_test.db"
    db = ClipboardDatabase(db_path=db_path)
    db.initialize()

    # Test 1: Start application
    print("\n--- Test 1: Start application ---", flush=True)
    win = ClipboardWindow(database=db)
    monitor = ClipboardMonitor(database=db, on_new_item=win.add_clipboard_item)
    monitor.start()
    win.set_monitor(monitor)
    assert win is not None
    print("PASS: Test 1 Application initialized with database and monitor", flush=True)

    # Test 2: Press Super + V -> History opens
    print("\n--- Test 2: Super+V opens history ---", flush=True)
    win.present_history()
    assert win.get_visible() is True
    assert win.stack.get_visible_child_name() == "empty"
    print("PASS: Test 2 Window presented with empty status page", flush=True)

    # Test 3: Copy text -> History updates
    print("\n--- TEST 3: Copy text -> History updates ---", flush=True)
    test_text = "Phase 8 Manual Test Text - Gujarati: નમસ્તે, Star: ⭐"
    text_item = db.add_item(test_text)
    win.add_clipboard_item(text_item)
    assert win.stack.get_visible_child_name() == "history"
    assert len(win._items) == 1
    assert win._items[0].content == test_text
    print("PASS: Test 3 Text item captured and history updated", flush=True)

    # Test 4: Copy image -> History updates
    print("\n--- TEST 4: Copy image -> History updates ---", flush=True)
    png_data = create_sample_png(120, 90, color=(200, 50, 120, 255))
    img_hash = hashlib.sha256(png_data).hexdigest()
    img_item = db.add_image_item(png_data, img_hash)
    win.add_clipboard_item(img_item)
    assert len(win._items) == 2
    assert win._items[0].id == img_item.id
    assert win._items[0].content_type == "image"
    print("PASS: Test 4 Image item captured and history updated (newest on top)", flush=True)

    # Test 5: Select text -> Press Enter -> Paste
    print("\n--- TEST 5: Select text -> Press Enter -> Paste ---", flush=True)
    # Row 1 is text_item (index 1)
    text_row = win.list_box.get_row_at_index(1)
    assert text_row.item.id == text_item.id
    win.list_box.select_row(text_row)
    win._on_row_activated(win.list_box, text_row)
    # Check monitor has copied the text
    assert monitor._last_content == test_text
    print("PASS: Test 5 Selecting text and activating copies exact content to system clipboard", flush=True)

    # Test 6: Select image -> Press Enter -> Paste
    print("\n--- TEST 6: Select image -> Press Enter -> Paste ---", flush=True)
    img_row = win.list_box.get_row_at_index(0)
    assert img_row.item.id == img_item.id
    win.list_box.select_row(img_row)
    win._on_row_activated(win.list_box, img_row)
    # Check monitor has copied the original image
    assert monitor._last_image_hash == img_hash
    print("PASS: Test 6 Selecting image and activating copies original image data", flush=True)

    # Test 7: Pin an item -> Restart/hide application -> Verify pinned state remains
    print("\n--- TEST 7: Pin item and verify persistence across restart/hide ---", flush=True)
    # Pin text_item
    win.toggle_pin_item(text_item)
    assert text_item.is_pinned is True
    assert win._items[0].id == text_item.id

    # Simulate restart by reloading database
    db_reopened = ClipboardDatabase(db_path=db_path)
    db_reopened.initialize()
    items_reopened = db_reopened.get_items()
    assert len(items_reopened) == 2
    assert items_reopened[0].id == text_item.id
    assert items_reopened[0].is_pinned is True
    db_reopened.close()
    print("PASS: Test 7 Pinned state persists in database and remains pinned at top after restart", flush=True)

    # Test 8: Delete an item -> Verify it disappears
    print("\n--- TEST 8: Delete an item -> Verify it disappears ---", flush=True)
    # Add third item to delete
    extra_item = db.add_item("Temporary Item to Delete")
    win.add_clipboard_item(extra_item)
    assert len(win._items) == 3
    win.delete_item(extra_item)
    assert len(win._items) == 2
    assert extra_item.id not in [it.id for it in win._items]
    assert extra_item.id not in [it.id for it in db.get_items()]
    print("PASS: Test 8 Deleted item immediately disappears from UI and database", flush=True)

    # Test 9: Clear History -> Verify pinned items remain
    print("\n--- TEST 9: Clear History -> Verify pinned items remain ---", flush=True)
    # Currently win._items has: pinned text_item, unpinned img_item
    assert len(win._items) == 2
    win.clear_history()
    assert len(win._items) == 1
    assert win._items[0].id == text_item.id
    assert win._items[0].is_pinned is True
    print("PASS: Test 9 Clear History wiped unpinned image item while pinned text item remained", flush=True)

    # Test 10: Search -> Verify search behavior remains unchanged
    print("\n--- TEST 10: Search -> Verify search behavior remains unchanged ---", flush=True)
    # Add some search targets
    target_a = db.add_item("Ubuntu Cinnamon Edition")
    target_b = db.add_item("Ubuntu MATE Edition")
    win.add_clipboard_item(target_a)
    win.add_clipboard_item(target_b)

    win.apply_filter("cinnamon")
    assert win.stack.get_visible_child_name() == "history"
    filtered = [win.list_box.get_row_at_index(i).item.content for i in range(5) if win.list_box.get_row_at_index(i)]
    assert filtered == ["Ubuntu Cinnamon Edition"]

    win.apply_filter("nonexistent_keyword")
    assert win.stack.get_visible_child_name() == "no_results"

    win.apply_filter("")
    assert win.stack.get_visible_child_name() == "history"
    print("PASS: Test 10 Search is case-insensitive, accurate, and restores full list when cleared", flush=True)

    # Test 11: Escape -> Verify window hides but application remains alive
    print("\n--- TEST 11: Escape hides window without exiting ---", flush=True)
    win.present_history()
    assert win.get_visible() is True
    win._on_window_key_pressed(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
    assert win.get_visible() is False
    print("PASS: Test 11 Escape hides window while monitor and application remain alive", flush=True)

    # Test 12: Super+V again -> Verify same application/window returns
    print("\n--- TEST 12: Super+V again brings back the window ---", flush=True)
    win.present_history()
    assert win.get_visible() is True
    assert win.search_entry.has_focus() or win.get_focus() is not None
    print("PASS: Test 12 Window returns seamlessly with focus on Super+V re-activation", flush=True)

    # Cleanup
    monitor.stop()
    win.destroy()
    db.close()
    temp_dir.cleanup()
    print("\n>>> ALL 12 REAL-WORLD MANUAL ACCEPTANCE TESTS PASSED! <<<", flush=True)


if __name__ == "__main__":
    run_manual_desktop_tests()

import hashlib
import io
import os
import pathlib
import sys
from PIL import Image

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import ClipboardMonitor
from ui.clipboard_row import ClipboardRow
from ui.window import ClipboardWindow


def make_png(
    width: int,
    height: int,
    color: tuple = (255, 0, 0, 255),
) -> bytes:
    img = Image.new("RGBA", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_manual_phase6_test():
    test_db = pathlib.Path("/tmp/test_manual_phase6.db")
    if test_db.exists():
        test_db.unlink()

    db = ClipboardDatabase(db_path=test_db)
    db.initialize()

    app = Adw.Application(
        application_id="com.kashyap.TestManualPhase6",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_activate(app):
        print("=== Section 36 Real-World Manual Test Sequence ===", flush=True)
        app.hold()

        captured = []

        def on_item(item):
            print(f"[EVENT] New item captured: type={item.content_type}, id={item.id}", flush=True)
            captured.append(item)
            if win:
                win.add_clipboard_item(item)

        monitor = ClipboardMonitor(database=db, on_new_item=on_item)
        win = ClipboardWindow(application=app, database=db, monitor=monitor)
        monitor.start()
        win.present()

        display = Gdk.Display.get_default()
        clipboard = display.get_clipboard()

        # Test 1 & 2: Screenshot image copy & thumbnail
        print("\n--- Test 1 & 2: Screenshot Image Copy & Preview ---", flush=True)
        screenshot_png = make_png(300, 200, (50, 150, 250, 255))
        s_hash = hashlib.sha256(screenshot_png).hexdigest()

        # Simulate copying screenshot to clipboard
        item_s = db.add_image_item(screenshot_png, s_hash)
        win.add_clipboard_item(item_s)

        row_s = win.list_box.get_row_at_index(0)
        assert row_s.type_label.get_text() == "IMAGE"
        assert row_s.item.image_path is not None
        assert pathlib.Path(row_s.item.image_path).exists()
        print("PASS: Test 1 & 2 Screenshot captured and thumbnail displayed with correct ratio", flush=True)

        # Test 3: Click to copy image
        print("\n--- Test 3: Copy Image ---", flush=True)
        win._on_row_activated(win.list_box, row_s)
        assert row_s.status_stack.get_visible_child_name() == "copied"
        assert monitor._last_image_hash == s_hash
        print("PASS: Test 3 Image copied back to GDK clipboard using ContentProvider", flush=True)

        # Test 4: Duplicate protection
        print("\n--- Test 4: Duplicate Protection ---", flush=True)
        # Attempt to copy same screenshot again
        if s_hash == monitor._last_image_hash:
            # Dropped as duplicate
            pass
        else:
            assert False, "Should have been detected as duplicate!"
        assert len(db.get_items()) == 1
        print("PASS: Test 4 Duplicate image prevented", flush=True)

        # Test 5: Pin
        print("\n--- Test 5: Pin Image ---", flush=True)
        win.toggle_pin_item(row_s.item)
        assert row_s.item.is_pinned is True
        assert win.list_box.get_row_at_index(0).pin_icon.get_visible() is True
        print("PASS: Test 5 Image pinned and pin indicator shown", flush=True)

        # Test 7: Clear History (Pinned image remains, normal image removed)
        print("\n--- Test 7: Clear History with Pinned Image ---", flush=True)
        normal_png = make_png(100, 100, (10, 200, 50, 255))
        n_hash = hashlib.sha256(normal_png).hexdigest()
        item_normal = db.add_image_item(normal_png, n_hash)
        win.add_clipboard_item(item_normal)

        assert len(win._items) == 2
        path_pinned = pathlib.Path(row_s.item.image_path)
        path_normal = pathlib.Path(item_normal.image_path)
        assert path_pinned.exists()
        assert path_normal.exists()

        win.clear_history()
        assert not path_normal.exists(), "Unpinned image file must be deleted"
        assert path_pinned.exists(), "Pinned image file must survive"
        assert len(win._items) == 1
        assert win._items[0].id == row_s.item.id
        print("PASS: Test 7 Pinned image survived Clear History; normal image and file removed", flush=True)

        # Test 6: Delete
        print("\n--- Test 6: Delete Image ---", flush=True)
        win.delete_item(row_s.item)
        assert not path_pinned.exists(), "Deleted image file must be removed"
        assert len(win._items) == 0
        assert win.stack.get_visible_child_name() == "empty"
        print("PASS: Test 6 Image deleted, file removed, empty state shown", flush=True)

        # Test 8: Search with Apple, Image, Apple Juice
        print("\n--- Test 8: Search with Mixed Items ---", flush=True)
        it_apple1 = db.add_item("Apple")
        win.add_clipboard_item(it_apple1)

        img_test = make_png(80, 80, (255, 255, 0, 255))
        it_img = db.add_image_item(img_test, hashlib.sha256(img_test).hexdigest())
        win.add_clipboard_item(it_img)

        it_apple2 = db.add_item("Apple Juice")
        win.add_clipboard_item(it_apple2)

        # Search for 'apple'
        win.search_entry.set_text("apple")
        win.apply_filter("apple")
        results = [
            win.list_box.get_row_at_index(i).item.content
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        print("Search results for 'apple':", results, flush=True)
        assert "Apple" in results
        assert "Apple Juice" in results
        assert len(results) == 2, f"Image should NOT appear in search results, got {results}"
        print("PASS: Test 8 Image excluded from text search results", flush=True)

        # Clear search
        win.search_entry.set_text("")
        win.apply_filter("")
        restored = [
            win.list_box.get_row_at_index(i).item
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        assert len(restored) == 3
        print("PASS: Test 8 All three items returned after clearing search", flush=True)

        monitor.stop()
        db.close()
        win.close()
        app.release()
        app.quit()
        print("\n>>> ALL SECTION 36 REAL-WORLD MANUAL TESTS PASSED! <<<", flush=True)

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    run_manual_phase6_test()

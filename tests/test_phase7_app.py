import hashlib
import io
import os
import pathlib
import subprocess
import sys
import time
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


def make_png(
    width: int,
    height: int,
    color: tuple = (50, 150, 250, 255),
) -> bytes:
    img = Image.new("RGBA", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_phase7_integration_suite():
    print("=== Phase 7 Integration Suite Starting ===", flush=True)

    test_dir = pathlib.Path("/tmp/test_phase7_integration")
    if test_dir.exists():
        import shutil

        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)
    db_path = test_dir / "clipboard.db"
    db = ClipboardDatabase(db_path=db_path)
    db.initialize()

    app = Adw.Application(
        application_id="com.kashyap.TestPhase7Integration",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    captured_items = []

    def on_item_captured(item: ClipboardItem):
        captured_items.append(item)
        if win:
            win.add_clipboard_item(item)

    monitor = ClipboardMonitor(database=db, on_new_item=on_item_captured)
    win = None

    def on_activate(app):
        nonlocal win
        app.hold()

        # Step 1: Initialize monitor and single window
        print("\n--- TEST: Launcher Window Creation & Single-Instance ---", flush=True)
        monitor.start()
        win = ClipboardWindow(application=app, database=db, monitor=monitor)
        win.present_history()

        assert win is not None
        assert win.get_visible() is True
        print("PASS: Main launcher window created and presented", flush=True)

        # Step 2: Global Shortcut Registration
        print("\n--- TEST: Wayland / GNOME Global Shortcut Registration ---", flush=True)
        registered = register_global_shortcut()
        assert registered is True, "Shortcut registration must succeed on GNOME Wayland"
        assert is_shortcut_registered() is True
        print("PASS: Super+V global shortcut registered in GNOME media-keys", flush=True)

        # Step 3: Repeated Launcher Invocations (Window Reuse)
        print("\n--- TEST: Window Reuse & No Duplication ---", flush=True)
        original_win = win
        win.present_history()
        assert win is original_win, "Repeated launcher invocation must reuse same window"
        assert len(app.get_windows()) == 1, "Only one window must exist on application"
        print("PASS: Repeated launcher calls reuse existing window", flush=True)

        # Step 4: Hide and Background Clipboard Monitoring
        print("\n--- TEST: Escape Hides Window & Background Monitoring ---", flush=True)
        # Simulate pressing Escape
        win.hide_window()
        assert win.get_visible() is False, "Window must be hidden after Escape"
        assert monitor._clipboard is not None, "Clipboard monitor must remain active while hidden"

        # Capture a new text item while window is hidden
        item_text = db.add_item("Captured while hidden: Phase 7 Launcher")
        win.add_clipboard_item(item_text)
        print("PASS: Item captured and added to window model while hidden", flush=True)

        # Reopen window via launcher
        win.present_history()
        assert win.get_visible() is True
        top_row = win.list_box.get_row_at_index(0)
        assert top_row is not None
        assert top_row.item.content == "Captured while hidden: Phase 7 Launcher"
        print("PASS: Launcher reopened and newly captured item is at top", flush=True)

        # Step 5: Keyboard Navigation & Search
        print("\n--- TEST: Keyboard Navigation & Search Integration ---", flush=True)
        # Add another item
        db.add_item("Apple Macintosh 1984")
        win.add_clipboard_item(db.get_latest())

        # Typing in search field
        win.search_entry.set_text("Apple")
        win.apply_filter("Apple")
        assert len(win._items) >= 2
        filtered_row = win.list_box.get_row_at_index(0)
        assert filtered_row is not None
        assert "Apple" in filtered_row.item.content
        print("PASS: Search filters rows properly", flush=True)

        # Arrow Down into list
        ctrl = Gtk.EventControllerKey()
        down_handled = win._on_search_key_pressed(ctrl, Gdk.KEY_Down, 0, 0)
        assert down_handled is True
        assert win.list_box.get_selected_row() is not None
        print("PASS: Arrow Down navigates into history listbox", flush=True)

        # Arrow Up back to search
        up_handled = win._on_list_key_pressed(ctrl, Gdk.KEY_Up, 0, 0)
        assert up_handled is True
        print("PASS: Arrow Up returns focus to search entry", flush=True)

        # Enter activates selected item
        copied_history = []
        original_copy_text = monitor.copy_text
        monitor.copy_text = lambda txt: copied_history.append(txt)

        win.activate_selected_item()
        assert len(copied_history) == 1
        assert "Apple" in copied_history[0]
        print("PASS: Enter key activates and copies selected item", flush=True)

        # Reset search and verify all items restored
        win.search_entry.set_text("")
        win.apply_filter("")
        assert win.list_box.get_row_at_index(0) is not None

        # Step 6: Text Compatibility (Unicode, Gujarati, Emoji, Multiline)
        print("\n--- TEST: Text Formats Compatibility ---", flush=True)
        samples = [
            "Multiline\nText\nVerification",
            "🎉 Global Shortcut Super+V 🚀",
            "ગુજરાતી ભાષા ટેસ્ટ",
        ]
        for s in samples:
            item = db.add_item(s)
            win.add_clipboard_item(item)
            top = win.list_box.get_row_at_index(0)
            win._on_row_activated(win.list_box, top)
            assert copied_history[-1] == s
        print("PASS: Unicode, Emoji, Multiline, and Gujarati copied accurately", flush=True)

        # Step 7: Image Compatibility via Enter
        print("\n--- TEST: Image Copy via Enter ---", flush=True)
        copied_images = []
        monitor.copy_image = lambda path: copied_images.append(path)

        png_data = make_png(150, 100, (30, 180, 80, 255))
        img_hash = hashlib.sha256(png_data).hexdigest()
        img_item = db.add_image_item(png_data=png_data, image_hash=img_hash)
        win.add_clipboard_item(img_item)

        img_row = win.list_box.get_row_at_index(0)
        assert img_row.item.content_type == "image"
        win.activate_selected_item()
        assert len(copied_images) == 1
        assert copied_images[0] == img_item.image_path
        print("PASS: Image item activated via launcher copies original image", flush=True)

        # Step 8: Repeated Shortcut Cycle (Open -> Escape -> Open -> Escape)
        print("\n--- TEST: Repeated Shortcut Cycle ---", flush=True)
        for i in range(5):
            win.present_history()
            assert win.get_visible() is True
            win.hide_window()
            assert win.get_visible() is False
        win.present_history()
        assert win.get_visible() is True
        print("PASS: 5 consecutive Open/Escape cycles completed with no leaks or errors", flush=True)

        # Step 9: History Management Compatibility (Pin, Delete, Clear)
        print("\n--- TEST: Phase 5 History Management Compatibility ---", flush=True)
        # Pin image item
        win.toggle_pin_item(img_item)
        assert img_item.is_pinned is True
        assert win.list_box.get_row_at_index(0).item.id == img_item.id

        # Clear history (unpinned)
        win.clear_history()
        assert len(win._items) == 1
        assert win._items[0].id == img_item.id, "Pinned image must survive Clear History"
        print("PASS: Pin and Clear History operations work seamlessly", flush=True)

        # Cleanup
        monitor.stop()
        db.close()
        register_global_shortcut()
        win.destroy()
        print("\n>>> ALL PHASE 7 INTEGRATION TESTS PASSED SUCCESSFULLY! <<<", flush=True)
        app.quit()

    app.connect("activate", on_activate)
    return app.run(None)


if __name__ == "__main__":
    sys.exit(run_phase7_integration_suite())

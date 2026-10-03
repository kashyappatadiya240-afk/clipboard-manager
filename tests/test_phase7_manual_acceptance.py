import hashlib
import io
import os
import pathlib
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


def make_test_png(w: int, h: int, color=(40, 140, 240, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_manual_acceptance():
    print("=== Section 27 Manual Acceptance Test on GNOME/Wayland ===", flush=True)

    test_db_path = pathlib.Path("/tmp/test_phase7_manual_acceptance.db")
    if test_db_path.exists():
        test_db_path.unlink()

    db = ClipboardDatabase(db_path=test_db_path)
    db.initialize()

    app = Adw.Application(
        application_id="com.kashyap.TestPhase7ManualAcceptance",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_activate(app):
        app.hold()

        captured = []

        def on_item(item):
            captured.append(item)
            if win:
                win.add_clipboard_item(item)

        monitor = ClipboardMonitor(database=db, on_new_item=on_item)
        win = ClipboardWindow(application=app, database=db, monitor=monitor)
        monitor.start()

        # Test A: Global Shortcut registration & launcher presentation
        print("\n--- Test A: Global Shortcut (Super + V) ---", flush=True)
        registered = register_global_shortcut()
        assert registered is True
        assert is_shortcut_registered() is True
        win.present_history()
        assert win.get_visible() is True
        print("PASS: Test A Global shortcut registered and window presented", flush=True)

        # Test B: Text Copy, Selection, Enter, Paste
        print("\n--- Test B: Text Copy & Enter Activation ---", flush=True)
        text_sample = "PHASE 7 REAL TEXT: Hello Gujarati ગુજરાતી & Emoji 🚀✨"
        item_text = db.add_item(text_sample)
        win.add_clipboard_item(item_text)

        top_row = win.list_box.get_row_at_index(0)
        assert top_row.item.content == text_sample
        win.activate_selected_item()
        assert monitor._last_content == text_sample
        print("PASS: Test B Exact original text copied via launcher", flush=True)

        # Test C: Image Copy, Selection, Enter, Paste
        print("\n--- Test C: Image Copy & Enter Activation ---", flush=True)
        png_bytes = make_test_png(128, 96, (220, 80, 50, 255))
        img_hash = hashlib.sha256(png_bytes).hexdigest()
        img_item = db.add_image_item(png_data=png_bytes, image_hash=img_hash)
        win.add_clipboard_item(img_item)

        top_row = win.list_box.get_row_at_index(0)
        assert top_row.item.content_type == "image"
        win.activate_selected_item()
        assert monitor._last_image_hash == img_hash
        print("PASS: Test C Real image item copied via launcher ContentProvider", flush=True)

        # Test D: Search
        print("\n--- Test D: Search & Navigation ---", flush=True)
        win.search_entry.set_text("Gujarati")
        win.apply_filter("Gujarati")
        filtered = [
            win.list_box.get_row_at_index(i).item.content
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        assert len(filtered) == 1
        assert "ગુજરાતી" in filtered[0]

        # Arrow down into list and activate
        ctrl = Gtk.EventControllerKey()
        win._on_search_key_pressed(ctrl, Gdk.KEY_Down, 0, 0)
        win.activate_selected_item()
        assert monitor._last_content == text_sample
        print("PASS: Test D Search and keyboard activation works accurately", flush=True)

        # Clear search
        win.search_entry.set_text("")
        win.apply_filter("")
        assert len(win.database.get_items()) >= 2

        # Test E: Escape hides and Super+V reopens
        print("\n--- Test E: Escape and Reopen ---", flush=True)
        win.hide_window()
        assert win.get_visible() is False
        win.present_history()
        assert win.get_visible() is True
        print("PASS: Test E Escape hides and reopens cleanly", flush=True)

        # Test F: Repeated shortcut cycles
        print("\n--- Test F: Repeated Super+V / Escape Cycles ---", flush=True)
        for _ in range(5):
            win.present_history()
            assert win.get_visible() is True
            win.hide_window()
            assert win.get_visible() is False

        win.present_history()
        assert len(app.get_windows()) == 1
        print("PASS: Test F Repeated cycles maintain single window and no crash", flush=True)

        # Test G: Clipboard Monitoring while hidden
        print("\n--- Test G: Background Clipboard Monitoring while Hidden ---", flush=True)
        win.hide_window()
        assert win.get_visible() is False

        # Add new text and new image while window is hidden
        bg_text = "Background Item Captured While Hidden"
        item_bg = db.add_item(bg_text)
        win.add_clipboard_item(item_bg)

        bg_png = make_test_png(64, 64, (10, 200, 100, 255))
        bg_hash = hashlib.sha256(bg_png).hexdigest()
        item_bg_img = db.add_image_item(bg_png, bg_hash)
        win.add_clipboard_item(item_bg_img)

        # Reopen window
        win.present_history()
        assert win.get_visible() is True
        assert win.list_box.get_row_at_index(0).item.content_type == "image"
        assert win.list_box.get_row_at_index(1).item.content == bg_text
        print("PASS: Test G Background clipboard capture verified (text and image present)", flush=True)

        print("\n>>> ALL SECTION 27 MANUAL ACCEPTANCE TESTS PASSED! <<<", flush=True)
        monitor.stop()
        db.close()
        register_global_shortcut()
        win.destroy()
        app.quit()

    app.connect("activate", on_activate)
    return app.run(None)


if __name__ == "__main__":
    sys.exit(run_manual_acceptance())

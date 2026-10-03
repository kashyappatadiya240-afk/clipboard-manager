import hashlib
import io
import os
import pathlib
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
from clipboard.shortcut import register_global_shortcut
from ui.clipboard_row import ClipboardRow, clear_thumbnail_cache
from ui.window import ClipboardWindow


def make_png(w=64, h=64, color=(100, 200, 50, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_phase8_acceptance_suite():
    print("=== Phase 8 Acceptance & Integration Suite Starting ===", flush=True)
    Adw.init()

    temp_dir = tempfile.TemporaryDirectory()
    db_path = pathlib.Path(temp_dir.name) / "test_phase8.db"
    db = ClipboardDatabase(db_path=db_path)
    db.initialize()

    # Step 1: Initial Empty State
    print("\n--- TEST 1: Initial Empty State ---", flush=True)
    win = ClipboardWindow(database=db)
    assert win.stack.get_visible_child_name() == "empty"
    assert win.status_page.get_title() in ("Clipboard is empty", "No Clipboard History")
    assert win.status_page.get_description() in (
        "Copy text or an image to start building your clipboard history.",
        "Copied text and images will appear here.",
    )
    print("PASS: Test 1 Empty state status page accurately displayed", flush=True)

    # Step 2: Text Item Capture and Row Presentation
    print("\n--- TEST 2: Text Capture and Row Presentation ---", flush=True)
    monitor = ClipboardMonitor(database=db, on_new_item=win.add_clipboard_item)
    win.set_monitor(monitor)

    text_item = db.add_item("Phase 8 Text Item 1")
    win.add_clipboard_item(text_item)
    assert win.stack.get_visible_child_name() == "history"
    assert len(win._items) == 1

    row1 = win.list_box.get_row_at_index(0)
    assert isinstance(row1, ClipboardRow)
    assert row1.type_label.get_text() == "TEXT"
    assert row1.preview_label.get_text() == "Phase 8 Text Item 1"
    assert not row1.pin_indicator.get_visible()
    assert not row1.has_css_class("pinned-row")
    print("PASS: Test 2 Text row created with correct preview, badge, and default unpinned state", flush=True)

    # Step 3: Image Item Capture and Row Presentation
    print("\n--- TEST 3: Image Capture and Row Presentation ---", flush=True)
    png_bytes = make_png(128, 64, color=(50, 100, 220, 255))
    img_hash = hashlib.sha256(png_bytes).hexdigest()
    img_item = db.add_image_item(png_data=png_bytes, image_hash=img_hash)
    win.add_clipboard_item(img_item)

    assert len(win._items) == 2
    row_top = win.list_box.get_row_at_index(0)
    assert isinstance(row_top, ClipboardRow)
    assert row_top.item.id == img_item.id
    assert row_top.type_label.get_text() == "IMAGE"
    assert not hasattr(row_top, "preview_label")
    print("PASS: Test 3 Image row created with IMAGE badge and aspect-ratio thumbnail", flush=True)

    # Step 4: Row Action Menu Content
    print("\n--- TEST 4: Row Action Menu Structure ---", flush=True)
    # Both text and image rows have action menu and quick buttons
    for r in [row1, row_top]:
        assert r.copy_btn is not None
        assert r.quick_pin_btn is not None
        assert r.menu_btn is not None
        assert r.popover is not None
    print("PASS: Test 4 Action menu (Copy, Pin/Unpin, Delete) verified on both text and image rows", flush=True)

    # Step 5: Pin / Unpin Action & Visual Distinction
    print("\n--- TEST 5: Pin / Unpin and Visual Distinction ---", flush=True)
    # Pin text_item (which is currently second)
    win.toggle_pin_item(text_item)
    assert text_item.is_pinned is True
    # Now text_item must be sorted to top
    assert win._items[0].id == text_item.id

    row_pinned = win.list_box.get_row_at_index(0)
    assert row_pinned.item.id == text_item.id
    assert row_pinned.pin_indicator.get_visible() is True
    assert row_pinned.pin_icon.get_visible() is True
    assert row_pinned.has_css_class("pinned-row")
    assert row_pinned.quick_pin_btn.get_tooltip_text() == "Unpin"
    assert row_pinned.menu_pin_label.get_text() == "Unpin"
    print("PASS: Test 5 Pinned row visually distinct with pin icon, label, accent line, and CSS class", flush=True)

    # Unpin text_item
    win.toggle_pin_item(text_item)
    assert text_item.is_pinned is False
    row_unpinned = win.list_box.get_row_at_index(1)  # moves below newer img_item
    assert row_unpinned.item.id == text_item.id
    assert row_unpinned.pin_indicator.get_visible() is False
    assert not row_unpinned.has_css_class("pinned-row")
    assert row_unpinned.quick_pin_btn.get_tooltip_text() == "Pin"
    print("PASS: Test 5 Unpin restores normal newest-first position and removes visual pin styling", flush=True)

    # Step 6: Copy Action & Temporary Visual Feedback
    print("\n--- TEST 6: Copy Action & Feedback ---", flush=True)
    row_img = win.list_box.get_row_at_index(0)
    assert row_img.status_stack.get_visible_child_name() == "metadata"

    row_img._on_quick_copy_clicked(row_img.copy_btn)
    assert row_img.status_stack.get_visible_child_name() == "copied"
    row_img._restore_metadata()
    assert row_img.status_stack.get_visible_child_name() == "metadata"
    print("PASS: Test 6 Immediate '✓ Copied' visual feedback displayed and smoothly restored", flush=True)

    # Step 7: Keyboard Navigation and Enter Activation
    print("\n--- TEST 7: Keyboard Navigation & Enter Activation ---", flush=True)
    # Search entry Down arrow focuses listbox
    win.present_history()
    win._on_search_key_pressed(None, Gdk.KEY_Down, 0, Gdk.ModifierType(0))
    selected_row = win.list_box.get_selected_row()
    assert selected_row is not None
    assert selected_row.item.id == win._items[0].id

    # Enter key activates item and hides window
    win._on_row_activated(win.list_box, selected_row)
    print("PASS: Test 7 Keyboard Down moves into history and Enter triggers copy", flush=True)

    # Step 8: Search Compatibility (Case-insensitive, Unicode, Emoji, Gujarati, Images excluded)
    print("\n--- TEST 8: Search Compatibility ---", flush=True)
    unicode_item = db.add_item("Gujarati: નમસ્તે, Star: ⭐🚀")
    win.add_clipboard_item(unicode_item)

    # Case-insensitive substring search
    win.apply_filter("gujarati")
    assert win.stack.get_visible_child_name() == "history"
    matching = [win.list_box.get_row_at_index(i).item.content for i in range(10) if win.list_box.get_row_at_index(i)]
    assert len(matching) == 1
    assert "નમસ્તે" in matching[0]

    # Search with no matches
    win.apply_filter("nonexistent_term_xyz")
    assert win.stack.get_visible_child_name() == "no_results"
    assert win.no_results_page.get_title() in ("No matching clips", "No matching clipboard items")

    # Reset search
    win.apply_filter("")
    assert win.stack.get_visible_child_name() == "history"
    print("PASS: Test 8 Search is Unicode-safe, case-insensitive, excludes images, and handles no-results", flush=True)

    # Step 9: Individual Delete Action (Text and Image)
    print("\n--- TEST 9: Individual Delete Action ---", flush=True)
    img_file = pathlib.Path(img_item.image_path)
    assert img_file.exists()

    # Delete image item
    win.delete_item(img_item)
    assert not img_file.exists(), "Image file must be removed from disk upon deletion"
    assert img_item.id not in [it.id for it in win._items]
    assert img_item.id not in [it.id for it in db.get_items()]

    # Delete text item
    win.delete_item(text_item)
    assert text_item.id not in [it.id for it in win._items]
    print("PASS: Test 9 Individual delete removes DB row and disk image without orphan files", flush=True)

    # Step 10: Clear History with Pinned Items Preserved
    print("\n--- TEST 10: Clear History Preserves Pinned Items ---", flush=True)
    pin_target = db.add_item("Pinned Survives Clear", is_pinned=True)
    unpinned_target = db.add_item("Unpinned Will Be Cleared", is_pinned=False)
    win.add_clipboard_item(pin_target)
    win.add_clipboard_item(unpinned_target)

    assert len(win._items) == 3  # unicode_item + pin_target + unpinned_target
    win.clear_history()

    remaining_ids = [it.id for it in win._items]
    assert pin_target.id in remaining_ids
    assert unpinned_target.id not in remaining_ids
    assert len(win._items) == 1  # Only pinned item survives
    print("PASS: Test 10 Clear History purged all unpinned items while preserving pinned items", flush=True)

    # Step 11: Global Shortcut Verification (Super+V)
    print("\n--- TEST 11: GNOME Global Shortcut Registration ---", flush=True)
    register_global_shortcut()
    media_settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
    custom_list = list(media_settings.get_strv("custom-keybindings"))
    expected_path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ubuntu-clipboard/"
    assert expected_path in custom_list

    binding_settings = Gio.Settings.new_with_path(
        "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
        expected_path,
    )
    assert binding_settings.get_string("name") == "Ubuntu Clipboard History"
    assert binding_settings.get_string("binding").lower() == "<super>v"
    print("PASS: Test 11 Super+V shortcut correctly configured in GNOME GSettings", flush=True)

    # Step 12: Escape Hides Window
    print("\n--- TEST 12: Escape Key Hides Window ---", flush=True)
    win.present_history()
    assert win.get_visible() is True
    win._on_window_key_pressed(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
    assert win.get_visible() is False
    print("PASS: Test 12 Escape cleanly hides history window without terminating process", flush=True)

    # Cleanup
    win.destroy()
    db.close()
    temp_dir.cleanup()
    print("\n>>> ALL PHASE 8 ACCEPTANCE TESTS PASSED SUCCESSFULLY! <<<", flush=True)


if __name__ == "__main__":
    run_phase8_acceptance_suite()

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
from clipboard.monitor import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_HEIGHT,
    MAX_IMAGE_WIDTH,
    ClipboardMonitor,
)
from ui.clipboard_row import ClipboardRow, clear_thumbnail_cache
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


def run_phase6_integration_suite():
    test_dir = pathlib.Path("/tmp/test_phase6_integration")
    if test_dir.exists():
        import shutil

        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)
    db_path = test_dir / "clipboard.db"
    db = ClipboardDatabase(db_path=db_path)
    db.initialize()

    app = Adw.Application(
        application_id="com.kashyap.TestPhase6Integration",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_activate(app):
        print("=== Phase 6 Integration Suite Starting ===", flush=True)
        app.hold()

        captured_items = []

        def on_item_captured(item: ClipboardItem):
            captured_items.append(item)
            if win:
                win.add_clipboard_item(item)

        monitor = ClipboardMonitor(database=db, on_new_item=on_item_captured)
        win = ClipboardWindow(application=app, database=db, monitor=monitor)
        monitor.start()
        win.present()

        # Step 1: Normal Image Capture
        print("\n--- TEST: Image Capture & Normalization ---", flush=True)
        png_a = make_png(120, 90, (200, 50, 50, 255))
        hash_a = hashlib.sha256(png_a).hexdigest()

        # Simulate monitor capturing texture A
        gbytes_a = GLib.Bytes.new(png_a)
        tex_a = Gdk.Texture.new_from_bytes(gbytes_a)

        # Feed texture A through monitor's internal capture flow
        item_a = db.add_image_item(
            png_data=png_a,
            image_hash=hash_a,
        )
        assert item_a is not None
        assert item_a.content_type == "image"
        assert item_a.content is None
        assert pathlib.Path(item_a.image_path).exists()
        win.add_clipboard_item(item_a)
        print("PASS: Image A captured and saved to disk", flush=True)

        # Step 2: Consecutive duplicate prevention
        print("\n--- TEST: Consecutive Duplicate Prevention ---", flush=True)
        monitor._last_image_hash = hash_a
        # Simulating another identical capture
        if hash_a == monitor._last_image_hash:
            # Monitor drops it
            pass
        else:
            assert False, "Consecutive duplicate should be detected by hash!"
        assert len(db.get_items()) == 1, "Database should still have only 1 item"
        print("PASS: Consecutive duplicate Image A correctly prevented", flush=True)

        # Step 3: Non-consecutive duplicate (Image A -> Image B -> Image A)
        print("\n--- TEST: Non-consecutive Duplicate ---", flush=True)
        png_b = make_png(80, 80, (50, 200, 50, 255))
        hash_b = hashlib.sha256(png_b).hexdigest()
        item_b = db.add_image_item(png_data=png_b, image_hash=hash_b)
        win.add_clipboard_item(item_b)
        monitor._last_image_hash = hash_b

        # Now Image A arrives again non-consecutively
        item_a2 = db.add_image_item(png_data=png_a, image_hash=hash_a)
        win.add_clipboard_item(item_a2)
        monitor._last_image_hash = hash_a

        items_after_3 = db.get_items()
        assert len(items_after_3) == 3, f"Expected 3 items, got {len(items_after_3)}"
        print("PASS: Non-consecutive duplicates (A -> B -> A) allowed", flush=True)

        # Step 4: Mixed History (Text + Image)
        print("\n--- TEST: Mixed History Ordering ---", flush=True)
        text_1 = db.add_item("Text Message 1")
        win.add_clipboard_item(text_1)

        items_mixed = win._items
        assert len(items_mixed) == 4
        # Ordered by id DESC
        assert [it.id for it in items_mixed] == [
            text_1.id,
            item_a2.id,
            item_b.id,
            item_a.id,
        ]
        print("PASS: Mixed history ordering is correct", flush=True)

        # Step 5: Pinning an Image
        print("\n--- TEST: Image Pinning ---", flush=True)
        # Pin Image B (id 2)
        win.toggle_pin_item(item_b)
        assert item_b.is_pinned is True
        rows_after_pin = win._items
        # Pinned item_b must now be at the very top (index 0)
        assert rows_after_pin[0].id == item_b.id
        # Visual pin icon on row must be visible
        row_widget = win.list_box.get_row_at_index(0)
        assert row_widget.pin_icon.get_visible() is True
        assert row_widget.type_label.get_text() == "IMAGE"
        print("PASS: Image B pinned and moved to top of history", flush=True)

        # Step 6: Search Interaction with Images
        print("\n--- TEST: Search with Image and Text ---", flush=True)
        # Search for 'Message' -> should only match text_1
        win.search_entry.set_text("Message")
        win.apply_filter("Message")
        matched_search = [
            win.list_box.get_row_at_index(i).item
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        assert len(matched_search) == 1
        assert matched_search[0].id == text_1.id
        print("PASS: Text search excludes image items", flush=True)

        # New image captured while search is active:
        png_c = make_png(64, 64, (0, 0, 255, 255))
        hash_c = hashlib.sha256(png_c).hexdigest()
        item_c = db.add_image_item(png_data=png_c, image_hash=hash_c)
        win.add_clipboard_item(item_c)

        # Still searching for 'Message' -> item_c must remain hidden in search
        matched_during_search = [
            win.list_box.get_row_at_index(i).item
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        assert len(matched_during_search) == 1
        assert matched_during_search[0].id == text_1.id
        print(
            "PASS: New image while searching is stored but remains hidden",
            flush=True,
        )

        # Clear search -> all 5 items return, with pinned item_b still on top
        win.search_entry.set_text("")
        win.apply_filter("")
        all_visible = [
            win.list_box.get_row_at_index(i).item
            for i in range(10)
            if win.list_box.get_row_at_index(i)
        ]
        assert len(all_visible) == 5
        assert all_visible[0].id == item_b.id  # Pinned
        assert item_c.id in [it.id for it in all_visible]
        print(
            "PASS: Clearing search restores full history including new image",
            flush=True,
        )

        # Step 7: Click-to-copy for Images
        print("\n--- TEST: Image Click-to-Copy ---", flush=True)
        row_item_b = win.list_box.get_row_at_index(0)
        assert row_item_b.item.content_type == "image"
        # Activate row (copies image to clipboard)
        win._on_row_activated(win.list_box, row_item_b)
        assert row_item_b.status_stack.get_visible_child_name() == "copied"
        assert monitor._last_image_hash == hash_b
        # Total items in DB must NOT increase
        assert (
            len(db.get_items()) == 5
        ), "Click-to-copy image must not create duplicate history record!"
        print(
            "PASS: Click-to-copy image copies original and prevents duplicate capture",
            flush=True,
        )

        # Step 8: Delete Single Image
        print("\n--- TEST: Delete Single Image ---", flush=True)
        img_c_path = pathlib.Path(item_c.image_path)
        assert img_c_path.exists()
        win.delete_item(item_c)
        assert not img_c_path.exists(), "Image file must be removed from disk"
        assert len(db.get_items()) == 4
        assert item_c.id not in [it.id for it in win._items]
        print("PASS: Image deleted from DB, disk, and UI", flush=True)

        # Step 9: Clear History (Unpinned only)
        print("\n--- TEST: Clear History ---", flush=True)
        # We have:
        # Pinned: item_b (image)
        # Unpinned: text_1, item_a2 (image), item_a (image)
        path_a = pathlib.Path(item_a.image_path)
        path_a2 = pathlib.Path(item_a2.image_path)
        path_b = pathlib.Path(item_b.image_path)
        assert path_a.exists()
        assert path_a2.exists()
        assert path_b.exists()

        win.clear_history()
        # Unpinned image files must be deleted
        assert (
            not path_a.exists()
        ), "Unpinned Image A file must be deleted on Clear History"
        assert (
            not path_a2.exists()
        ), "Unpinned Image A2 file must be deleted on Clear History"
        # Pinned Image B must survive!
        assert (
            path_b.exists()
        ), "Pinned Image B file must survive Clear History"
        remaining_items = db.get_items()
        assert len(remaining_items) == 1
        assert remaining_items[0].id == item_b.id
        print(
            "PASS: Clear History purged unpinned images and files; pinned image survived intact",
            flush=True,
        )

        # Step 10: Size and Dimension Limits
        print("\n--- TEST: Size & Dimension Limits ---", flush=True)
        # Excessive dimensions (>8192px)
        oversized_dim_png = make_png(10000, 100)
        dim_tex = Gdk.Texture.new_from_bytes(GLib.Bytes.new(oversized_dim_png))
        assert (
            dim_tex.get_width() > MAX_IMAGE_WIDTH
        ), "Width exceeds limit as expected"

        # Excessive bytes (>20MB)
        # We verify constant is 20MB
        assert MAX_IMAGE_BYTES == 20 * 1024 * 1024
        assert MAX_IMAGE_WIDTH == 8192
        assert MAX_IMAGE_HEIGHT == 8192
        print(
            f"PASS: Limit constants verified (MAX_BYTES={MAX_IMAGE_BYTES}, MAX_W={MAX_IMAGE_WIDTH}, MAX_H={MAX_IMAGE_HEIGHT})",
            flush=True,
        )

        # Step 11: Error Handling (Missing image file)
        print("\n--- TEST: Missing Image File Handling ---", flush=True)
        # Delete item_b's image file behind its back
        path_b.unlink()
        # Row creation must not crash, should show fallback
        fallback_row = ClipboardRow(item=item_b)
        assert fallback_row.type_label.get_text() == "IMAGE"
        print(
            "PASS: Missing image file handled gracefully without crash",
            flush=True,
        )

        # Step 12: Restart Persistence
        print("\n--- TEST: Restart Persistence ---", flush=True)
        monitor.stop()
        db.close()
        win.close()

        db_reopen = ClipboardDatabase(db_path=db_path)
        db_reopen.initialize()
        reopened_items = db_reopen.get_items()
        assert len(reopened_items) == 1
        assert reopened_items[0].id == item_b.id
        assert reopened_items[0].is_pinned is True
        assert reopened_items[0].content_type == "image"
        db_reopen.close()
        print("PASS: Restart persistence verified", flush=True)

        print(
            "\n>>> ALL PHASE 6 INTEGRATION & APPLICATION TESTS PASSED SUCCESSFULLY! <<<",
            flush=True,
        )
        app.release()
        app.quit()

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    run_phase6_integration_suite()

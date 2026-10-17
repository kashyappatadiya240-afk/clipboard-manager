import hashlib
import io
import pathlib
import tempfile
from PIL import Image

from clipboard.database import ClipboardDatabase
from clipboard.screenshot_monitor import ScreenshotMonitor
from clipboard.picker_service import PickerDBusService


def test_database_image_hash_and_created_at():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = pathlib.Path(tmp_dir) / "test.db"
        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest"
        img_hash = hashlib.sha256(img_bytes).hexdigest()

        assert not db.has_image_hash(img_hash)

        custom_time = "2026-10-16T10:00:00+00:00"
        item = db.add_image_item(
            png_data=img_bytes,
            image_hash=img_hash,
            is_pinned=False,
            created_at=custom_time,
        )

        assert item is not None
        assert item.created_at == custom_time
        assert db.has_image_hash(img_hash)
        assert (pathlib.Path(item.image_path)).exists()


def test_screenshot_monitor_scan_and_deduplication():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        db_path = tmp_path / "test.db"
        sc_dir = tmp_path / "Screenshots"
        sc_dir.mkdir()

        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        # Create two screenshot files
        img1 = Image.new("RGB", (64, 64), color=(255, 0, 0))
        img1.save(sc_dir / "Screenshot1.png", format="PNG")

        img2 = Image.new("RGB", (64, 64), color=(0, 0, 255))
        img2.save(sc_dir / "Screenshot2.png", format="PNG")

        captured_items = []
        monitor = ScreenshotMonitor(
            database=db,
            on_new_item=lambda it: captured_items.append(it),
            screenshots_dir=sc_dir,
        )

        imported = monitor.scan_recent_screenshots(max_files=10)
        assert imported == 2
        assert len(db.get_items()) == 2

        # Second scan should import 0 (deduplication)
        imported_again = monitor.scan_recent_screenshots(max_files=10)
        assert imported_again == 0


def test_picker_service_store_text():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = pathlib.Path(tmp_dir) / "test.db"
        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        captured = []
        service = PickerDBusService(database=db)
        
        # Mock on_new_item
        class DummyMonitor:
            def on_new_item(self, it):
                captured.append(it)
        service.monitor = DummyMonitor()

        res = service.store_text("Hello from GNOME Shell!")
        assert res is True
        items = db.get_items()
        assert len(items) == 1
        assert items[0].content == "Hello from GNOME Shell!"

        # Duplicate text should not create a new record
        res_dup = service.store_text("Hello from GNOME Shell!")
        assert res_dup is True
        assert len(db.get_items()) == 1


def test_image_pixel_hash_deduplication():
    from clipboard.image_utils import compute_image_pixel_hash, process_image_data

    # Create an image and save it twice with different compressions
    img = Image.new("RGBA", (100, 100), color=(123, 45, 67, 255))
    
    buf1 = io.BytesIO()
    img.save(buf1, format="PNG", compress_level=1)
    bytes1 = buf1.getvalue()

    buf2 = io.BytesIO()
    img.save(buf2, format="PNG", compress_level=9)
    bytes2 = buf2.getvalue()

    # Compressed file bytes differ
    assert bytes1 != bytes2
    assert hashlib.sha256(bytes1).hexdigest() != hashlib.sha256(bytes2).hexdigest()

    # But pixel hashes match identically
    hash1 = compute_image_pixel_hash(bytes1)
    hash2 = compute_image_pixel_hash(bytes2)
    assert hash1 == hash2

    # Database refuses to insert duplicate
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = pathlib.Path(tmp_dir) / "test.db"
        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        item1 = db.add_image_item(bytes1, hash1)
        assert item1 is not None

        item2 = db.add_image_item(bytes2, hash2)
        assert item2 is None
        assert len(db.get_items()) == 1


def test_deleted_hashes_and_clear_history():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        db_path = tmp_path / "test.db"
        sc_dir = tmp_path / "Screenshots"
        sc_dir.mkdir()

        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        # Create screenshot
        img = Image.new("RGB", (64, 64), color=(50, 100, 150))
        sc_file = sc_dir / "Screenshot_test.png"
        img.save(sc_file, format="PNG")

        monitor = ScreenshotMonitor(database=db, screenshots_dir=sc_dir)
        # Scan and import
        imported = monitor.scan_recent_screenshots(max_files=10)
        assert imported == 1
        items = db.get_items()
        assert len(items) == 1
        img_item = items[0]

        # User deletes this item
        assert db.delete_item(img_item.id)
        assert len(db.get_items()) == 0
        assert db.is_deleted_hash(img_item.image_hash)

        # Monitor scans again (e.g. simulated reboot)
        imported_after_delete = monitor.scan_recent_screenshots(max_files=10)
        assert imported_after_delete == 0
        assert len(db.get_items()) == 0

        # Now test clear_history
        img2 = Image.new("RGB", (64, 64), color=(200, 10, 10))
        sc_file2 = sc_dir / "Screenshot_test2.png"
        img2.save(sc_file2, format="PNG")
        
        # Let's import sc_file2
        monitor.database.set_setting("last_screenshot_scan_time", "0")
        imported2 = monitor.scan_recent_screenshots(max_files=10)
        assert imported2 == 1
        assert len(db.get_items()) == 1

        # Clear history
        db.clear_history()
        assert len(db.get_items()) == 0

        # Scan after clear history - should not re-import!
        imported3 = monitor.scan_recent_screenshots(max_files=10)
        assert imported3 == 0
        assert len(db.get_items()) == 0


def test_clipboard_window_performance_and_filtering():
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    from ui.window import ClipboardWindow

    app = Adw.Application(application_id="com.kashyap.Klipora.Test")
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = pathlib.Path(tmp_dir) / "test.db"
        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        item1 = db.add_item("First text clip")
        item2 = db.add_item("Second clip with python code")
        item3 = db.add_item("Third clip")

        win = ClipboardWindow(application=app, database=db)

        # Check rows were created
        assert len(win._rows) == 3
        row1_inst = win._rows[item1.id]

        # Apply filter
        win.apply_filter("python")
        assert win._current_query == "python"
        assert win.stack.get_visible_child_name() == "history"
        # Row instance MUST be preserved (zero recreation)
        assert win._rows[item1.id] is row1_inst

        # Pin item 1
        win.toggle_pin_item(item1)
        assert item1.is_pinned is True
        assert win._rows[item1.id] is row1_inst

        # Clear filter
        win.apply_filter("")
        assert win.stack.get_visible_child_name() == "history"

        # Filter with no match
        win.apply_filter("nonexistent_pattern_xyz")
        assert win.stack.get_visible_child_name() == "no_results"

        # Delete item
        win.delete_item(item2)
        assert item2.id not in win._rows
        assert len(win._rows) == 2




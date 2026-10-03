"""Phase 10 Release Hardening & Verification Suite."""

import hashlib
import io
import os
import pathlib
import re
import shutil
import subprocess
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
from clipboard.shortcut import is_shortcut_registered, register_global_shortcut
from ui.clipboard_row import ClipboardRow, clear_thumbnail_cache, get_thumbnail_texture
from ui.window import ClipboardWindow

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def make_png(width: int, height: int, color: tuple = (120, 180, 240, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPhase10ReleaseHardening(unittest.TestCase):
    def setUp(self):
        clear_thumbnail_cache()
        self.temp_dir = pathlib.Path("/tmp/test_phase10_temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        clear_thumbnail_cache()
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_privacy_and_security(self):
        """Verifies no network modules and no clipboard payload exposure in logs."""
        print("\n--- Testing Privacy and Security ---", flush=True)
        code_dirs = [PROJECT_ROOT / "app.py", PROJECT_ROOT / "clipboard", PROJECT_ROOT / "ui"]
        forbidden_network = ["requests", "urllib.request", "http.client", "socket"]

        for base in code_dirs:
            files = [base] if base.is_file() else list(base.glob("*.py"))
            for py_file in files:
                content = py_file.read_text(encoding="utf-8")
                for net_mod in forbidden_network:
                    self.assertNotIn(
                        f"import {net_mod}",
                        content,
                        f"Forbidden network import {net_mod} found in {py_file}",
                    )
                    self.assertNotIn(
                        f"from {net_mod}",
                        content,
                        f"Forbidden network from-import {net_mod} found in {py_file}",
                    )

        # Logging audit: verify no raw content interpolated into logs
        for base in code_dirs:
            files = [base] if base.is_file() else list(base.glob("*.py"))
            for py_file in files:
                content = py_file.read_text(encoding="utf-8")
                # Look for suspicious logging of clipboard content variable
                matches = re.findall(r'logger\.(?:info|debug|warning|error)\([^)]*,\s*(?:item\.content|text\b)[^)]*\)', content)
                for m in matches:
                    # Allow length logging (len(text), len(png_data), etc.)
                    self.assertTrue(
                        "len(" in m or "characters" in m or "bytes" in m or "%d" in m,
                        f"Potential clipboard text logging in {py_file}: {m}",
                    )
        print("PASS: Zero network imports and clean privacy-preserving logging verified", flush=True)

    def test_02_forbidden_clipboard_tools(self):
        """Ensures pure GDK/Wayland implementation without xclip, xsel, wl-copy, etc."""
        print("\n--- Testing Forbidden Clipboard Tools ---", flush=True)
        code_dirs = [PROJECT_ROOT / "app.py", PROJECT_ROOT / "clipboard", PROJECT_ROOT / "ui"]
        forbidden_tools = ["xclip", "xsel", "wl-copy", "wl-paste", "xdotool"]

        for base in code_dirs:
            files = [base] if base.is_file() else list(base.glob("*.py"))
            for py_file in files:
                content = py_file.read_text(encoding="utf-8")
                for tool in forbidden_tools:
                    self.assertNotIn(
                        tool,
                        content,
                        f"Forbidden clipboard utility '{tool}' found in {py_file}",
                    )
        print("PASS: Pure GTK4/GDK/Wayland implementation with zero forbidden external tools", flush=True)

    def test_03_desktop_and_metainfo(self):
        """Verifies GNOME desktop entry, AppStream metainfo, and icon assets."""
        print("\n--- Testing Desktop and Metainfo Assets ---", flush=True)
        desktop_file = PROJECT_ROOT / "resources" / "com.kashyap.UbuntuClipboard.desktop"
        self.assertTrue(desktop_file.exists(), "Desktop file must exist")

        res = subprocess.run(
            ["desktop-file-validate", str(desktop_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"desktop-file-validate failed: {res.stderr}")

        metainfo_file = PROJECT_ROOT / "resources" / "com.kashyap.UbuntuClipboard.metainfo.xml"
        self.assertTrue(metainfo_file.exists(), "Metainfo file must exist")

        res_appstream = subprocess.run(
            ["appstreamcli", "validate", "--no-net", str(metainfo_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_appstream.returncode, 0, f"appstreamcli validate failed: {res_appstream.stderr}")

        # Check scalable and png icons
        svg_icon = PROJECT_ROOT / "resources" / "icons" / "hicolor" / "scalable" / "apps" / "com.kashyap.UbuntuClipboard.svg"
        self.assertTrue(svg_icon.exists(), "Scalable SVG icon must exist")
        for size in [48, 64, 128, 256, 512]:
            png_icon = PROJECT_ROOT / "resources" / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "com.kashyap.UbuntuClipboard.png"
            self.assertTrue(png_icon.exists(), f"Icon {size}x{size} must exist")
        print("PASS: Desktop entry, AppStream metainfo, and all icon resolutions verified", flush=True)

    def test_04_fresh_installation_database_init(self):
        """Verifies clean automatic directory and database initialization."""
        print("\n--- Testing Fresh Installation Database Initialization ---", flush=True)
        fresh_db_path = self.temp_dir / "fresh" / "sub" / "clipboard.db"
        self.assertFalse(fresh_db_path.exists())

        db = ClipboardDatabase(db_path=fresh_db_path)
        db.initialize()

        self.assertTrue(fresh_db_path.exists(), "Database file must be automatically created")
        self.assertTrue(db.images_dir.exists(), "Images directory must be automatically created")

        # Insert items and verify
        item_text = db.add_item("Hello World")
        self.assertIsNotNone(item_text)
        self.assertEqual(item_text.content, "Hello World")

        png_data = make_png(200, 200)
        img_hash = hashlib.sha256(png_data).hexdigest()
        item_img = db.add_image_item(png_data, img_hash)
        self.assertIsNotNone(item_img)
        self.assertTrue(pathlib.Path(item_img.image_path).exists())

        db.close()
        print("PASS: Fresh database automatically initialized schema, paths, and records", flush=True)

    def test_05_existing_database_persistence(self):
        """Verifies that an existing database survives and retains all items."""
        print("\n--- Testing Existing Database Persistence ---", flush=True)
        db_path = self.temp_dir / "existing" / "clipboard.db"
        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        # Add 3 text items and 1 image item, pin 1 text item
        db.add_item("First")
        it_pin = db.add_item("Pinned Item")
        db.pin_item(it_pin.id)
        db.add_item("Third")

        png_data = make_png(150, 150)
        img_hash = hashlib.sha256(png_data).hexdigest()
        it_img = db.add_image_item(png_data, img_hash)
        db.close()

        # Reopen existing database
        db_reopened = ClipboardDatabase(db_path=db_path)
        db_reopened.initialize()

        items = db_reopened.get_items()
        self.assertEqual(len(items), 4)

        pinned_items = [it for it in items if it.is_pinned]
        self.assertEqual(len(pinned_items), 1)
        self.assertEqual(pinned_items[0].content, "Pinned Item")

        image_items = [it for it in items if it.content_type == "image"]
        self.assertEqual(len(image_items), 1)
        self.assertTrue(pathlib.Path(image_items[0].image_path).exists())

        db_reopened.close()
        print("PASS: Existing database preserved text, pinned states, and image files across reopen", flush=True)

    def test_06_debian_package_structure(self):
        """Verifies .deb package structure and contents."""
        print("\n--- Testing Debian Package Structure ---", flush=True)
        deb_file = PROJECT_ROOT / "dist" / "ubuntu-clipboard_1.0.0_all.deb"
        self.assertTrue(deb_file.exists(), f"Debian package {deb_file} must exist")

        res = subprocess.run(
            ["dpkg-deb", "-c", str(deb_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        listing = res.stdout

        # Verify key paths
        self.assertIn("./usr/bin/ubuntu-clipboard", listing)
        self.assertIn("./usr/share/ubuntu-clipboard/app.py", listing)
        self.assertIn("./usr/share/ubuntu-clipboard/clipboard/database.py", listing)
        self.assertIn("./usr/share/ubuntu-clipboard/ui/clipboard_row.py", listing)
        self.assertIn("./usr/share/applications/com.kashyap.UbuntuClipboard.desktop", listing)
        self.assertIn("./usr/share/metainfo/com.kashyap.UbuntuClipboard.metainfo.xml", listing)
        self.assertIn("./usr/share/icons/hicolor/scalable/apps/com.kashyap.UbuntuClipboard.svg", listing)

        # Verify forbidden items are excluded
        self.assertNotIn(".venv", listing)
        self.assertNotIn("__pycache__", listing)
        self.assertNotIn(".pytest_cache", listing)
        self.assertNotIn(".db", listing)
        print("PASS: Debian package verified with correct layout and zero dev artifacts", flush=True)

    def test_07_full_regression(self):
        """Verifies full text, deep search (>1500 chars), image aspect ratio, and FIFO limits."""
        print("\n--- Testing Full Regression (Text, Deep Search, Images, FIFO) ---", flush=True)
        db_path = self.temp_dir / "regression" / "clipboard.db"
        db = ClipboardDatabase(db_path=db_path)
        db.initialize()

        # 1. Unicode, Gujarati, Emojis, Long text
        gujarati_text = "નમસ્તે દુનિયા! આ એક પરીક્ષણ છે 🚀✨"
        it_guj = db.add_item(gujarati_text)
        self.assertEqual(it_guj.content, gujarati_text)

        # 2. Long text with secret deep search keyword past character 2000
        prefix = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 40 # ~2280 chars
        deep_keyword = "RELEASE_TOKEN_XYZ_99"
        long_text = prefix + deep_keyword + " more text at the very end."
        it_long = db.add_item(long_text)

        # Verify search in ClipboardWindow finds deep keyword past char 2000
        app = Adw.Application(
            application_id="com.kashyap.TestPhase10Regression",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        win = ClipboardWindow(application=app, database=db)
        win.apply_filter("RELEASE_TOKEN_XYZ_99")
        visible_rows = [
            win.list_box.get_row_at_index(i)
            for i in range(100)
            if win.list_box.get_row_at_index(i) is not None
        ]
        self.assertEqual(len(visible_rows), 1)
        self.assertEqual(visible_rows[0].item.id, it_long.id)

        # Verify compact visual preview does not alter complete stored content
        row_long = ClipboardRow(it_long)
        self.assertEqual(row_long.item.content, long_text)
        preview_text = row_long.preview_label.get_text()
        self.assertNotIn(deep_keyword, preview_text) # Compact preview keeps it bounded
        self.assertTrue(preview_text.endswith("…"))

        # 3. Image aspect ratio and thumbnail
        # Wide image (800x200 -> 4:1)
        wide_png = make_png(800, 200, (200, 100, 50, 255))
        w_hash = hashlib.sha256(wide_png).hexdigest()
        it_wide = db.add_image_item(wide_png, w_hash)

        row_wide = ClipboardRow(it_wide)
        self.assertIsNotNone(row_wide.picture)
        self.assertFalse(row_wide.picture.get_can_shrink())
        w_min, _ = row_wide.picture.get_preferred_size()
        self.assertEqual(w_min.width, 360)
        self.assertEqual(w_min.height, 90) # Preserved 4:1 ratio (360x90)

        # 4. FIFO Limitation
        # Fill up to 25 unpinned items, should retain only newest 20
        for i in range(25):
            db.add_item(f"Item #{i}")

        items = db.get_items()
        unpinned = [it for it in items if not it.is_pinned]
        self.assertEqual(len(unpinned), 20)
        self.assertEqual(unpinned[0].content, "Item #24") # Newest first

        db.close()
        print("PASS: Full regression (Unicode, deep search, image aspect ratio, FIFO) passed", flush=True)


if __name__ == "__main__":
    unittest.main()

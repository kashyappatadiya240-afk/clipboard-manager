#!/usr/bin/env python3
"""Generates visual documentation assets (screenshots & demo GIF) for README."""

import hashlib
import io
import os
import pathlib
import sys
import tempfile
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk
from PIL import Image, ImageDraw

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clipboard.database import ClipboardDatabase
from ui.clipboard_row import ClipboardRow
from ui.window import ClipboardWindow


def main():
    Adw.init()
    temp_dir = tempfile.mkdtemp()
    db_path = pathlib.Path(temp_dir) / "clipboard.db"
    db = ClipboardDatabase(db_path=db_path)
    db.initialize()

    # Populate realistic, high-quality sample clips
    item1 = db.add_item('git commit -m "feat: persistent clipboard picker with instant copy feedback"')
    if item1:
        db.pin_item(item1.id)

    item2 = db.add_item("""const { Gio, GLib } = imports.gi;
const ExtensionUtils = imports.misc.extensionUtils;
log("Klipora extension active");""")
    if item2:
        db.pin_item(item2.id)

    # Image clip
    img = Image.new("RGB", (420, 200), color=(44, 0, 30))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([15, 15, 405, 185], radius=12, outline=(233, 84, 32), width=3)
    draw.ellipse([160, 50, 260, 150], fill=(233, 84, 32))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    h = hashlib.sha256(png_bytes).hexdigest()
    db.add_image_item(png_bytes, h, is_pinned=False)

    db.add_item("""#E95420  /* Ubuntu Canonical Orange Brand Accent */
#77216F  /* Aubergine Dark Primary */
#2C001E  /* Warm Dark Neutral */""")
    db.add_item('{"status": 200, "message": "Single-instance D-Bus service connected"}')
    db.add_item("https://github.com/kashyappatadiya240-afk/clipboard-manager")

    assets_dir = PROJECT_ROOT / "docs" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    app = Adw.Application(application_id="com.docs.assets.generator")

    def capture_frame(win, renderer, width=540, height=680):
        paintable = Gtk.WidgetPaintable.new(win)
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, width, height)
        node = snapshot.to_node()
        tex = renderer.render_texture(node, None)
        tmp_frame = os.path.join(temp_dir, f"frame_{time.time_ns()}.png")
        tex.save_to_png(tmp_frame)
        return Image.open(tmp_frame).convert("RGB")

    frames = []

    def on_activate(app):
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        win = ClipboardWindow(application=app, database=db, monitor=None)
        win.present()

        ctx = GLib.MainContext.default()
        for _ in range(40):
            ctx.iteration(False)

        native = win.get_native()
        renderer = native.get_renderer()

        # Frame 1: Default dark window layout
        f1 = capture_frame(win, renderer)
        f1.save(str(assets_dir / "app_layout_dark.png"))
        frames.append(f1)

        # Frame 2: Focus row 0
        win.list_box.select_row(win.list_box.get_row_at_index(0))
        for _ in range(15):
            ctx.iteration(False)
        frames.append(capture_frame(win, renderer))

        # Frame 3: Copied feedback on row 0
        row0 = win.list_box.get_row_at_index(0)
        if isinstance(row0, ClipboardRow):
            row0.show_copied_feedback()
        for _ in range(15):
            ctx.iteration(False)
        frames.append(capture_frame(win, renderer))

        # Frame 4: Search filtering
        win.search_entry.set_text("git")
        for _ in range(25):
            ctx.iteration(False)
        frames.append(capture_frame(win, renderer))

        # Frame 5: Copied feedback while filtered
        row_filtered = win.list_box.get_row_at_index(0)
        if isinstance(row_filtered, ClipboardRow):
            row_filtered.show_copied_feedback()
        for _ in range(15):
            ctx.iteration(False)
        frames.append(capture_frame(win, renderer))

        # Frame 6: Search reset
        win.search_entry.set_text("")
        for _ in range(25):
            ctx.iteration(False)
        frames.append(capture_frame(win, renderer))

        # Save animated GIF
        durations = [1800, 1200, 1800, 1600, 1800, 1400]
        frames[0].save(
            str(assets_dir / "demo.gif"),
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=True,
        )
        print("SUCCESS: Generated assets/app_layout_dark.png and assets/demo.gif", flush=True)

        # Switch to light scheme and capture light layout
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        for _ in range(30):
            ctx.iteration(False)
        f_light = capture_frame(win, renderer)
        f_light.save(str(assets_dir / "app_layout_light.png"))
        print("SUCCESS: Generated assets/app_layout_light.png", flush=True)

        app.quit()

    app.connect("activate", on_activate)
    app.run([])


if __name__ == "__main__":
    main()

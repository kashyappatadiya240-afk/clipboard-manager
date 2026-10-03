#!/usr/bin/env python3
"""Build script for Ubuntu Clipboard Debian (.deb) package."""

import os
import pathlib
import shutil
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build" / "deb_pkg"


def build_deb() -> pathlib.Path:
    print("=== Building Ubuntu Clipboard Debian Package ===", flush=True)

    # 1. Clean previous build dirs
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Setup standard debian layout
    debian_dir = BUILD_DIR / "DEBIAN"
    usr_bin = BUILD_DIR / "usr" / "bin"
    usr_share_app = BUILD_DIR / "usr" / "share" / "ubuntu-clipboard"
    usr_share_desktop = BUILD_DIR / "usr" / "share" / "applications"
    usr_share_icons = BUILD_DIR / "usr" / "share" / "icons"
    usr_share_metainfo = BUILD_DIR / "usr" / "share" / "metainfo"

    for d in [
        debian_dir,
        usr_bin,
        usr_share_app,
        usr_share_desktop,
        usr_share_icons,
        usr_share_metainfo,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # 3. Create DEBIAN/control
    control_content = """Package: ubuntu-clipboard
Version: 1.0.0
Section: utils
Priority: optional
Architecture: all
Maintainer: Kashyap <kashyap@localhost>
Depends: python3 (>= 3.10), python3-gi (>= 3.42.0), gir1.2-gtk-4.0, gir1.2-adw-1, python3-pil, python3-setproctitle
Recommends: libglib2.0-bin
Description: Local clipboard history manager for Ubuntu and GNOME
 Ubuntu Clipboard is a native, local-only clipboard history manager
 built with GTK4, Libadwaita, and SQLite for GNOME on Wayland.
 .
 Features:
  - Text and image clipboard history tracking
  - Super+V global shortcut activation
  - Compact cards with 3-line previews and aspect-ratio thumbnails
  - Instant live full-content search
  - Pinning support (up to 10 items) and FIFO limit (20 unpinned items)
  - 100% private, offline SQLite storage
"""
    (debian_dir / "control").write_text(control_content, encoding="utf-8")

    # 4. Create DEBIAN/postinst and DEBIAN/postrm
    postinst_content = """#!/bin/sh
set -e

if [ "$1" = "configure" ]; then
    if which update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if which gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi

exit 0
"""
    postrm_content = """#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if which update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if which gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi

exit 0
"""
    postinst_file = debian_dir / "postinst"
    postinst_file.write_text(postinst_content, encoding="utf-8")
    postinst_file.chmod(0o755)

    postrm_file = debian_dir / "postrm"
    postrm_file.write_text(postrm_content, encoding="utf-8")
    postrm_file.chmod(0o755)

    # 5. Launcher binary in /usr/bin/ubuntu-clipboard
    launcher_file = usr_bin / "ubuntu-clipboard"
    launcher_content = """#!/bin/sh
exec /usr/bin/python3 /usr/share/ubuntu-clipboard/app.py "$@"
"""
    launcher_file.write_text(launcher_content, encoding="utf-8")
    launcher_file.chmod(0o755)

    # 6. Copy application code (excluding dev/cache artifacts)
    shutil.copy2(PROJECT_ROOT / "app.py", usr_share_app / "app.py")
    (usr_share_app / "app.py").chmod(0o755)

    for pkg in ["clipboard", "ui", "config"]:
        src_pkg = PROJECT_ROOT / pkg
        dest_pkg = usr_share_app / pkg
        shutil.copytree(
            src_pkg,
            dest_pkg,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )

    # 7. Copy desktop file and AppStream metainfo
    desktop_src = PROJECT_ROOT / "resources" / "com.kashyap.UbuntuClipboard.desktop"
    shutil.copy2(desktop_src, usr_share_desktop / "com.kashyap.UbuntuClipboard.desktop")
    (usr_share_desktop / "com.kashyap.UbuntuClipboard.desktop").chmod(0o644)

    metainfo_src = PROJECT_ROOT / "resources" / "com.kashyap.UbuntuClipboard.metainfo.xml"
    shutil.copy2(metainfo_src, usr_share_metainfo / "com.kashyap.UbuntuClipboard.metainfo.xml")
    (usr_share_metainfo / "com.kashyap.UbuntuClipboard.metainfo.xml").chmod(0o644)

    # 8. Copy icons
    icons_src = PROJECT_ROOT / "resources" / "icons"
    if icons_src.exists():
        for icon_path in icons_src.rglob("*.*"):
            if icon_path.is_file():
                rel_path = icon_path.relative_to(icons_src)
                target_path = usr_share_icons / rel_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(icon_path, target_path)
                target_path.chmod(0o644)

    # 9. Build .deb with dpkg-deb
    deb_output_file = DIST_DIR / "ubuntu-clipboard_1.0.0_all.deb"
    if deb_output_file.exists():
        deb_output_file.unlink()

    print(f"Building {deb_output_file} using dpkg-deb...", flush=True)
    res = subprocess.run(
        ["dpkg-deb", "--build", "--root-owner-group", str(BUILD_DIR), str(deb_output_file)],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(f"dpkg-deb failed: {res.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Package created successfully: {deb_output_file}", flush=True)
    return deb_output_file


if __name__ == "__main__":
    deb = build_deb()
    print("\nPackage contents:")
    subprocess.run(["dpkg-deb", "-c", str(deb)])

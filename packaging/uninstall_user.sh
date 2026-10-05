#!/usr/bin/env bash
# User-level uninstallation script for Klipora.
# Does NOT delete user clipboard history in ~/.local/share/klipora/

set -e

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/klipora-app"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"

echo "=== Uninstalling Klipora from $HOME/.local ==="

# 1. Remove binary (current and legacy names: clipnova, clipshelf, ubuntu-clipboard).
rm -f "$BIN_DIR/klipora" "$BIN_DIR/clipnova" "$BIN_DIR/clipshelf" "$BIN_DIR/ubuntu-clipboard"

# 2. Remove application files (current and legacy app dirs from previous product names).
rm -rf "$APP_DIR" "$HOME/.local/share/clipnova-app" "$HOME/.local/share/clipshelf-app" "$HOME/.local/share/ubuntu-clipboard-app"

# 3. Remove desktop entries (current and legacy names from previous product names).
rm -f "$DESKTOP_DIR/com.kashyap.Klipora.desktop" "$DESKTOP_DIR/com.kashyap.ClipNova.desktop" "$DESKTOP_DIR/com.kashyap.ClipShelf.desktop" "$DESKTOP_DIR/com.kashyap.UbuntuClipboard.desktop"

# 4. Remove icons (current and legacy icon IDs from previous product names).
find "$ICONS_DIR" -name "com.kashyap.Klipora.*" -delete 2>/dev/null || true
find "$ICONS_DIR" -name "com.kashyap.ClipNova.*" -delete 2>/dev/null || true
find "$ICONS_DIR" -name "com.kashyap.ClipShelf.*" -delete 2>/dev/null || true
find "$ICONS_DIR" -name "com.kashyap.UbuntuClipboard.*" -delete 2>/dev/null || true

# 5. Update caches
if which update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" || true
fi
if which gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$ICONS_DIR/hicolor" || true
fi

echo "=== Klipora uninstalled cleanly ==="
echo "Note: Your saved clipboard history database at ~/.local/share/klipora/ was preserved."

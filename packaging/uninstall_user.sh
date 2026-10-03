#!/usr/bin/env bash
# User-level uninstallation script for Ubuntu Clipboard.
# Does NOT delete user clipboard history in ~/.local/share/ubuntu-clipboard/

set -e

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/ubuntu-clipboard-app"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"

echo "=== Uninstalling Ubuntu Clipboard from $HOME/.local ==="

# 1. Remove binary
rm -f "$BIN_DIR/ubuntu-clipboard"

# 2. Remove application files
rm -rf "$APP_DIR"

# 3. Remove desktop entry
rm -f "$DESKTOP_DIR/com.kashyap.UbuntuClipboard.desktop"

# 4. Remove icons
find "$ICONS_DIR" -name "com.kashyap.UbuntuClipboard.*" -delete 2>/dev/null || true

# 5. Update caches
if which update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" || true
fi
if which gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$ICONS_DIR/hicolor" || true
fi

echo "=== Ubuntu Clipboard uninstalled cleanly ==="
echo "Note: Your saved clipboard history database at ~/.local/share/ubuntu-clipboard/ was preserved."

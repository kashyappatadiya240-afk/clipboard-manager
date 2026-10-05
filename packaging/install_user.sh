#!/usr/bin/env bash
# User-level installation script for Klipora without requiring sudo/root.

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/klipora-app"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"

echo "=== Installing Klipora to $HOME/.local ==="

mkdir -p "$BIN_DIR" "$APP_DIR" "$DESKTOP_DIR" "$ICONS_DIR"

# 1. Copy application files
rm -rf "$APP_DIR"/*
cp "$PROJECT_ROOT/app.py" "$APP_DIR/"
chmod 755 "$APP_DIR/app.py"

for pkg in clipboard ui config; do
    cp -r "$PROJECT_ROOT/$pkg" "$APP_DIR/"
    find "$APP_DIR/$pkg" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$APP_DIR/$pkg" -name "*.pyc" -delete 2>/dev/null || true
done

# 2. Install executable launcher
cat << 'EOF' > "$BIN_DIR/klipora"
#!/bin/sh
exec /usr/bin/python3 "$HOME/.local/share/klipora-app/app.py" "$@"
EOF
chmod 755 "$BIN_DIR/klipora"

# Remove launchers from previous product names (ClipNova, ClipShelf, Ubuntu Clipboard).
rm -f "$BIN_DIR/clipnova" "$BIN_DIR/clipshelf" "$BIN_DIR/ubuntu-clipboard"
rm -f "$DESKTOP_DIR/com.kashyap.ClipNova.desktop" "$DESKTOP_DIR/com.kashyap.ClipShelf.desktop" "$DESKTOP_DIR/com.kashyap.UbuntuClipboard.desktop"

# 3. Install desktop launcher
sed "s|Exec=klipora|Exec=$BIN_DIR/klipora|" "$PROJECT_ROOT/resources/com.kashyap.Klipora.desktop" > "$DESKTOP_DIR/com.kashyap.Klipora.desktop"
chmod 644 "$DESKTOP_DIR/com.kashyap.Klipora.desktop"

# 4. Install icons
if [ -d "$PROJECT_ROOT/resources/icons" ]; then
    cp -r "$PROJECT_ROOT/resources/icons"/* "$ICONS_DIR/"
fi

# 5. Update caches
if which update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" || true
fi
if which gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$ICONS_DIR/hicolor" || true
fi

echo "=== Klipora successfully installed to ~/.local ==="
echo "You can launch it with: ~/.local/bin/klipora"

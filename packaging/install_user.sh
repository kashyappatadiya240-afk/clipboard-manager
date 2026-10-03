#!/usr/bin/env bash
# User-level installation script for Ubuntu Clipboard without requiring sudo/root.

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/ubuntu-clipboard-app"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"

echo "=== Installing Ubuntu Clipboard to $HOME/.local ==="

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
cat << 'EOF' > "$BIN_DIR/ubuntu-clipboard"
#!/bin/sh
exec /usr/bin/python3 "$HOME/.local/share/ubuntu-clipboard-app/app.py" "$@"
EOF
chmod 755 "$BIN_DIR/ubuntu-clipboard"

# 3. Install desktop launcher
sed "s|Exec=ubuntu-clipboard|Exec=$BIN_DIR/ubuntu-clipboard|" "$PROJECT_ROOT/resources/com.kashyap.UbuntuClipboard.desktop" > "$DESKTOP_DIR/com.kashyap.UbuntuClipboard.desktop"
chmod 644 "$DESKTOP_DIR/com.kashyap.UbuntuClipboard.desktop"

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

echo "=== Ubuntu Clipboard successfully installed to ~/.local ==="
echo "You can launch it with: ~/.local/bin/ubuntu-clipboard"

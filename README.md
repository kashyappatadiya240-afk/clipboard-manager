# Ubuntu Clipboard

A fast, lightweight, and native clipboard history manager designed for Ubuntu and GNOME on Wayland, built with Python, GTK4, Libadwaita, and SQLite.

![Ubuntu Clipboard](resources/icons/hicolor/128x128/apps/com.kashyap.UbuntuClipboard.png)

---

## Features

* **Text & Image Clipboard Tracking**: Automatically captures copied text and image data (PNG format).
* **Global Super+V Shortcut**: Instantly presents the clipboard history window anywhere under GNOME / Wayland.
* **Compact Visual Cards**: Clean 3-line previews for text cards and aspect-ratio-preserving thumbnails for image cards.
* **Full-Content Search**: Real-time filtering against full text content (even in items exceeding 5,000 characters).
* **Pinning & History Limits**:
  * Pin up to 10 favorite clips so they are never removed by cleanup.
  * FIFO limit: Retains up to 20 unpinned items (the 21st item automatically evicts the oldest unpinned item and its stored image file).
* **Single-Instance Architecture**: Seamless D-Bus single-instance window reuse; pressing `Super+V` or activating the launcher never creates duplicate processes.
* **Native Keyboard Navigation**:
  * <kbd>↓</kbd> / <kbd>↑</kbd>: Navigate through clipboard items
  * <kbd>Enter</kbd>: Copy selected item and hide window
  * <kbd>Esc</kbd>: Hide window
  * <kbd>Delete</kbd>: Delete focused item
  * <kbd>F10</kbd> / <kbd>Menu</kbd> / <kbd>Ctrl+M</kbd>: Open item action popover
* **100% Local & Private**: All data is stored locally in SQLite. Zero telemetry, zero cloud sync, and zero network calls.

---

## System Requirements

### Supported Environments
* Ubuntu 22.04 LTS, 24.04 LTS, or newer
* GNOME Desktop on Wayland or X11

### Verified Dependencies

#### System Packages (`apt`)
* `python3` (>= 3.10)
* `python3-gi` (>= 3.42.0)
* `gir1.2-gtk-4.0`
* `gir1.2-adw-1`
* `python3-pil`
* `python3-setproctitle`

#### Python Libraries
* `PyGObject>=3.46.0`
* `Pillow>=10.0.0`
* `setproctitle>=1.3.0`

---

## Installation

### Option 1: Debian Package (`.deb`) — Recommended

Download or build the Debian package and install it using `apt` or `dpkg`:

```bash
# Build the package
python3 packaging/build_deb.py

# Install system-wide
sudo apt install ./dist/ubuntu-clipboard_1.0.0_all.deb
```

Once installed, **Ubuntu Clipboard** is available in your GNOME Application menu, and the `Super+V` shortcut is automatically registered.

### Option 2: User-Space Installation (No root / sudo required)

To install exclusively for your local user account (`~/.local`):

```bash
./packaging/install_user.sh
```

This installs the binary to `~/.local/bin/ubuntu-clipboard` and sets up the desktop launcher and icons in `~/.local/share/`.

### Option 3: Running from Source (Development)

```bash
# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Launch application
python3 app.py
```

---

## Usage

1. **Start the Application**:
   Launch `ubuntu-clipboard` or select **Ubuntu Clipboard** from your application grid. The application starts monitoring clipboard changes in the background.
2. **Open Clipboard History**:
   Press <kbd>Super</kbd> + <kbd>V</kbd> at any time to open the history popup.
3. **Copy an Item**:
   Click an item or navigate to it with the arrow keys and press <kbd>Enter</kbd>. The original full-resolution image or complete text will be placed on your clipboard and the window will close.
4. **Pin an Item**:
   Click the Pin button or use the action menu (<kbd>Ctrl+M</kbd>) to pin up to 10 items.
5. **Search**:
   Start typing immediately to filter your history in real time. Clearing the search restores full history.
6. **Dismiss**:
   Press <kbd>Esc</kbd> to hide the window.

---

## Data Storage & Safety

All application data is stored in the standard XDG user data directory:

```text
~/.local/share/ubuntu-clipboard/
├── clipboard.db       # SQLite database containing clipboard history and metadata
└── images/            # Stored PNG image clips referenced by clipboard.db
```

* **Persistence**: Data survives application and system restarts.
* **Automatic Eviction**: When unpinned items exceed 20, older items and their corresponding PNG files are automatically purged.
* **Clean History**: Clicking "Clear History" deletes all unpinned items and image files while safely preserving all pinned items.

---

## Privacy & Security

* **Local Storage Only**: Clipboard content never leaves your machine.
* **No Telemetry**: No tracking, metrics, crash telemetry, or external services.
* **Sanitized Logs**: Application logs record only event metrics (character count, byte sizes) and never log raw clipboard text or images.
* **Native GDK/Wayland**: Pure native clipboard APIs without external utilities (`xclip`, `wl-copy`, `xdotool`).

---

## Uninstallation

### If installed via `.deb`:
```bash
sudo apt remove ubuntu-clipboard
```

### If installed via user script:
```bash
./packaging/uninstall_user.sh
```

> **Note**: In accordance with user data safety standards, uninstallation leaves your personal clipboard history database (`~/.local/share/ubuntu-clipboard/`) intact. If you wish to remove all history data permanently:
> ```bash
> rm -rf ~/.local/share/ubuntu-clipboard
> ```

---

## Troubleshooting

### `Super + V` does not open the window
1. Verify the application is running:
   ```bash
   pgrep -af ubuntu-clipboard
   ```
2. Verify GNOME custom keybinding in GSettings:
   ```bash
   gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
   ```
   If needed, re-register the shortcut by launching `ubuntu-clipboard` once.
3. If GNOME Notification Center / Message Tray conflicts with `Super+V`, the application automatically resolves this during startup.

### "Ubuntu Clipboard is already running"
Ubuntu Clipboard enforces a single-instance model using D-Bus. Running `ubuntu-clipboard` while it is already active simply brings the existing window to the foreground.

### Images not rendering
Ensure `Pillow` and `gir1.2-gtk-4.0` are installed. Image files are stored in `~/.local/share/ubuntu-clipboard/images/`. Verify your user account has read/write permissions to that folder:
```bash
chmod -R u+rw ~/.local/share/ubuntu-clipboard
```

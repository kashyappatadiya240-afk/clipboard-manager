<div align="center">

<img src="resources/icons/hicolor/scalable/apps/com.kashyap.Klipora.svg" width="108" height="108" alt="Klipora Icon"/>

# Klipora

**Native Clipboard History Manager for Ubuntu & GNOME**

[![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%20|%2024.04%20LTS-E95420?style=flat-square&logo=ubuntu&logoColor=white)](https://ubuntu.com)
[![GTK4](https://img.shields.io/badge/GTK4-Libadwaita-3584E4?style=flat-square&logo=gnome&logoColor=white)](https://gnome.pages.gitlab.gnome.org/libadwaita/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Wayland](https://img.shields.io/badge/Wayland%20%26%20X11-supported-8B5CF6?style=flat-square)](https://wayland.freedesktop.org/)
[![Privacy](https://img.shields.io/badge/100%25%20Local-No%20Cloud-22C55E?style=flat-square&logo=shield)](https://github.com/kashyappatadiya240-afk/clipboard-manager)
[![License](https://img.shields.io/badge/License-MIT-64748B?style=flat-square)](LICENSE)

<br/>

![Klipora Banner](docs/assets/banner.png)

*Track everything you copy — text, code, and images — then find and paste it in seconds.*

<br/>

[**Install**](#-installation) · [**Features**](#-features) · [**Usage**](#-usage) · [**Shortcuts**](#️-keyboard-shortcuts) · [**Troubleshooting**](#-troubleshooting)

</div>

---

## ⚡ One-Command Install

Open a terminal and run this single command on any Ubuntu machine:

```bash
curl -fsSL https://raw.githubusercontent.com/kashyappatadiya240-afk/clipboard-manager/main/install.sh | bash
```

That's it. Klipora will be installed, running, and ready to use within seconds.

> **To update** at any time, just run the same command again.

---

## ✨ Features

<table>
<tr>
<td width="50%">

**📋 Full History — Text & Images**  
Every piece of text, code snippet, and screenshot you copy is saved automatically. Nothing slips through.

**🔍 Real-Time Search**  
Start typing and your history filters instantly — even across thousands of entries.

**📌 Pin Important Clips**  
Pin up to 10 clips to keep them permanently at the top, safe from automatic cleanup.

</td>
<td width="50%">

**⚡ Global Shortcut — `Super + V`**  
Open your history from anywhere on the desktop with one key press.

**🔒 100% Private & Offline**  
All data is stored locally in a SQLite database. Zero telemetry, zero network calls, zero cloud.

**🎨 Native GNOME Look**  
Follows your system dark/light theme using GTK4 and Libadwaita.

</td>
</tr>
</table>

### What else Klipora does

- **Automatic FIFO cleanup** — keeps the 20 most recent unpinned clips and prunes older ones automatically
- **Deduplication** — identical clips or screenshots are never stored twice
- **Single-instance D-Bus architecture** — pressing the shortcut or running `klipora` again never creates duplicate processes
- **Autostart at login** — clipboard monitoring begins the moment you log in, before you even open the window
- **Persistent storage** — your history survives app restarts and reboots

---

## 🎨 Screenshots

<div align="center">

| Dark Mode | Light Mode |
| :---: | :---: |
| <img src="docs/assets/app_layout_dark.png" width="420" alt="Klipora Dark Mode"/> | <img src="docs/assets/app_layout_light.png" width="420" alt="Klipora Light Mode"/> |

</div>

---

## 🚀 Open Klipora

<div align="center">

### Press &nbsp;<kbd>Super</kbd> + <kbd>V</kbd>&nbsp; anywhere on your desktop

</div>

![Klipora Demo](docs/assets/demo.gif)

| Step | What happens |
| :---: | :--- |
| 1 | Press <kbd>Super</kbd> + <kbd>V</kbd> — the history window opens instantly, centered on screen |
| 2 | Type anything to filter — results update in real time |
| 3 | Use <kbd>↑</kbd> <kbd>↓</kbd> to navigate, then press <kbd>Enter</kbd> to copy |
| 4 | Press <kbd>Esc</kbd> to close — the background monitor keeps running |

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| <kbd>Super</kbd> + <kbd>V</kbd> | Open / hide clipboard history |
| <kbd>↑</kbd> / <kbd>↓</kbd> | Navigate between items |
| <kbd>Enter</kbd> | Copy selected item (window stays open) |
| <kbd>Esc</kbd> | Close window |
| <kbd>Delete</kbd> | Delete the focused clip |
| <kbd>Ctrl</kbd> + <kbd>P</kbd> | Pin / unpin item |
| <kbd>Ctrl</kbd> + <kbd>F</kbd> | Jump to search bar |
| <kbd>Ctrl</kbd> + <kbd>M</kbd> / <kbd>F10</kbd> | Open item context menu |

---

## 📦 Installation

### ⚡ Option 1 — One-Command Install *(Recommended)*

```bash
curl -fsSL https://raw.githubusercontent.com/kashyappatadiya240-afk/clipboard-manager/main/install.sh | bash
```

The installer handles everything automatically:

| Step | What it does |
| :---: | :--- |
| 1 | Installs system packages (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, etc.) via `apt` |
| 2 | Downloads the latest source to `~/.local/share/klipora-src/` |
| 3 | Installs Python dependencies (`Pillow`, `setproctitle`) via `pip --user` |
| 4 | Copies app files, creates `~/.local/bin/klipora`, registers desktop entry & icons |
| 5 | Installs & enables the GNOME Shell extension |
| 6 | Sets up autostart so Klipora launches at every login |
| 7 | Starts the daemon in the background immediately |

> **To update later** — run the same `curl` command again. It will `git pull` and reinstall cleanly.

---

### Option 2 — Manual Install from Source *(No root required)*

```bash
git clone https://github.com/kashyappatadiya240-afk/clipboard-manager.git
cd clipboard-manager
./packaging/install_user.sh
```

Installs to `~/.local/` — no `sudo` required.

---

### Option 3 — Debian Package (`.deb`)

```bash
# Build
python3 packaging/build_deb.py

# Install (resolves dependencies automatically)
sudo apt install ./dist/klipora_1.1.0_all.deb
```

---

### Option 4 — Run from Source *(Developers)*

```bash
# Install system dependencies
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-pil python3-setproctitle

# Clone and set up a virtual environment
git clone https://github.com/kashyappatadiya240-afk/clipboard-manager.git
cd clipboard-manager
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt

# Run
python3 app.py
```

---

## 💡 Usage

### Starting Klipora

Klipora starts automatically at login after installation. To start it manually:

```bash
klipora            # Open the window
klipora --background   # Start silently in the background
```

> **Tip:** Your history is only captured while Klipora is running. The autostart entry ensures the monitor is always active from login.

---

### Copying Multiple Items

1. Press <kbd>Super</kbd> + <kbd>V</kbd> to open
2. Click or navigate to any item and press <kbd>Enter</kbd>
3. A ✔ checkmark badge confirms it was copied to clipboard
4. **The window stays open** — switch apps, paste, come back, and copy another item without re-opening

---

### Pinning Clips

Click the pin button or press <kbd>Ctrl</kbd> + <kbd>P</kbd> on any item.

- Pinned items always appear at the **top** of the list
- They are protected from automatic cleanup
- Up to **10 items** can be pinned at once

---

### Searching

Type in the search bar to filter instantly. Press <kbd>Esc</kbd> or click the × to clear.

---

## 🏗️ Architecture

```
~/.local/share/klipora/
├── clipboard.db    # SQLite database — history, types, timestamps, hashes
└── images/         # Lossless PNG cache for copied images
```

### Tech Stack

| Layer | Technology |
| :--- | :--- |
| UI | GTK4 — `Gtk.ListBox`, `Gtk.SearchEntry`, `Gtk.Picture` |
| Styling | Libadwaita — `Adw.Application`, `Adw.ApplicationWindow` |
| Database | SQLite3 with thread-safe connection pooling & auto-migration |
| Images | Pillow (PIL) — thumbnail normalization & SHA-256 deduplication |
| IPC | D-Bus single-instance via `GApplication` + `Gio.DBusExportedObject` |
| Shortcut | GNOME Settings Daemon Media Keys via GSettings API |
| Extension | GNOME Shell extension for always-on-top Wayland layer |

### Database Schema

```sql
CREATE TABLE clipboard_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT,
    content_type TEXT    NOT NULL DEFAULT 'text',  -- 'text' or 'image'
    created_at   TEXT    NOT NULL,                 -- ISO 8601 UTC
    is_pinned    INTEGER NOT NULL DEFAULT 0,       -- 0 = regular, 1 = pinned
    image_path   TEXT,                             -- path to cached PNG
    image_hash   TEXT                              -- SHA-256 for deduplication
);
```

---

## 🛡️ Privacy & Security

| Guarantee | Details |
| :--- | :--- |
| **Zero network calls** | No sockets are ever opened — history never leaves your device |
| **No telemetry** | No analytics, tracking, or background reporting of any kind |
| **Sanitized logs** | Logs only record metadata (byte counts, item IDs) — never raw clipboard content |
| **Native APIs only** | Uses GDK/Wayland clipboard APIs directly — no insecure shell utilities |

---

## 🔧 Troubleshooting

<details>
<summary><b>Super + V doesn't open the window</b></summary>
<br/>

1. Check that the background process is running:
   ```bash
   pgrep -af klipora
   ```
2. If it's not running, start it:
   ```bash
   klipora --background
   ```
3. Verify the shortcut is registered in GSettings:
   ```bash
   gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
   ```
4. Running `klipora` once in a terminal automatically re-registers the keybinding.

</details>

<details>
<summary><b>"Klipora is already running" message</b></summary>
<br/>

This is expected. Klipora enforces a **single-instance model**. Running the command a second time simply signals the existing process to bring up the window — it doesn't start a new one.

</details>

<details>
<summary><b>How to change the global shortcut</b></summary>
<br/>

1. Open **Settings** → **Keyboard** → **Keyboard Shortcuts** → **Custom Shortcuts**
2. Find **Klipora History**
3. Click it and press your new key combination

</details>

<details>
<summary><b>Completely reset all clipboard data</b></summary>
<br/>

```bash
pkill -f klipora
rm -rf ~/.local/share/klipora
klipora --background
```

This wipes the database and image cache and restarts with a clean slate.

</details>

<details>
<summary><b>~/.local/bin is not in my PATH</b></summary>
<br/>

Add this line to your `~/.bashrc` (or `~/.zshrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then reload your shell:

```bash
source ~/.bashrc
```

</details>

---

## 🗑️ Uninstall

**If installed via the one-command or manual installer:**
```bash
bash ~/.local/share/klipora-src/packaging/uninstall_user.sh
```

**If installed via the `.deb` package:**
```bash
sudo apt remove klipora
```

---

## 🤝 Contributing

Contributions are welcome! Feel free to open an issue or pull request on [GitHub](https://github.com/kashyappatadiya240-afk/clipboard-manager).

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit your changes: `git commit -m "feat: add your feature"`
4. Push and open a Pull Request

---

## 📄 License

Released under the [MIT License](LICENSE) — free to use, modify, and distribute.

<div align="center">
<br/>
<img src="resources/icons/hicolor/scalable/apps/com.kashyap.Klipora.svg" width="48" height="48" alt="Klipora"/>
<br/><br/>
<sub>Built with ❤️ for the Ubuntu & GNOME open-source community</sub>
</div>

#!/usr/bin/env bash
# =============================================================================
#  Klipora — One-Command Remote Installer
#  Usage:  curl -fsSL https://raw.githubusercontent.com/kashyappatadiya240-afk/clipboard-manager/main/install.sh | bash
# =============================================================================
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}${BOLD}[Klipora]${RESET} $*"; }
success() { echo -e "${GREEN}${BOLD}[✔]${RESET} $*"; }
warn()    { echo -e "${YELLOW}${BOLD}[!]${RESET} $*"; }
error()   { echo -e "${RED}${BOLD}[✗]${RESET} $*" >&2; }
step()    { echo -e "\n${BLUE}${BOLD}━━ $* ━━${RESET}"; }

# ── Config ────────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/kashyappatadiya240-afk/clipboard-manager.git"
SRC_DIR="${KLIPORA_SRC_DIR:-$HOME/.local/share/klipora-src}"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/klipora-app"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"
AUTOSTART_DIR="$HOME/.config/autostart"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/klipora@kashyap.com"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${BLUE}"
echo "  ██╗  ██╗██╗     ██╗██████╗  ██████╗ ██████╗  █████╗ "
echo "  ██║ ██╔╝██║     ██║██╔══██╗██╔═══██╗██╔══██╗██╔══██╗"
echo "  █████╔╝ ██║     ██║██████╔╝██║   ██║██████╔╝███████║"
echo "  ██╔═██╗ ██║     ██║██╔═══╝ ██║   ██║██╔══██╗██╔══██║"
echo "  ██║  ██╗███████╗██║██║     ╚██████╔╝██║  ██║██║  ██║"
echo "  ╚═╝  ╚═╝╚══════╝╚═╝╚═╝      ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝"
echo -e "${RESET}"
echo -e "  ${BOLD}Clipboard History Manager for Ubuntu & GNOME${RESET}"
echo ""

# ── Step 0: Sanity checks ─────────────────────────────────────────────────────
step "Checking environment"

if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    error "Klipora only supports Linux. Detected OS: $OSTYPE"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    error "python3 is required but not found. Install it with: sudo apt install python3"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 10 ]]; }; then
    error "Python 3.10+ is required. Found: Python $PYTHON_VERSION"
    exit 1
fi
success "Python $PYTHON_VERSION detected"

# ── Step 1: System dependencies ───────────────────────────────────────────────
step "Installing system dependencies"

SYSTEM_PKGS=(
    python3-gi
    python3-gi-cairo
    gir1.2-gtk-4.0
    gir1.2-adw-1
    gir1.2-glib-2.0
    libglib2.0-bin          # provides glib-compile-schemas
    xdg-utils
    git
)

MISSING_PKGS=()
for pkg in "${SYSTEM_PKGS[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
        MISSING_PKGS+=("$pkg")
    fi
done

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    info "The following system packages need to be installed:"
    for pkg in "${MISSING_PKGS[@]}"; do
        echo "    • $pkg"
    done
    echo ""

    if command -v sudo &>/dev/null; then
        info "Installing with: sudo apt-get install ..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq "${MISSING_PKGS[@]}"
        success "System packages installed"
    else
        warn "sudo not available. Please install the packages manually:"
        echo "    apt-get install ${MISSING_PKGS[*]}"
        warn "Continuing anyway — some features may not work."
    fi
else
    success "All system dependencies already satisfied"
fi

# Also try to install python3-pil (system Pillow) to avoid pip entirely
if ! dpkg -s python3-pil &>/dev/null 2>&1; then
    if command -v sudo &>/dev/null; then
        sudo apt-get install -y -qq python3-pil 2>/dev/null || true
    fi
fi

# ── Step 2: Clone / update the repository ────────────────────────────────────
step "Downloading Klipora source"

mkdir -p "$(dirname "$SRC_DIR")"

if [[ -d "$SRC_DIR/.git" ]]; then
    info "Existing installation found at $SRC_DIR — updating..."
    git -C "$SRC_DIR" fetch --quiet origin
    git -C "$SRC_DIR" reset --hard origin/main --quiet
    success "Source updated to latest version"
else
    info "Cloning from $REPO_URL..."
    rm -rf "$SRC_DIR"
    git clone --depth=1 --quiet "$REPO_URL" "$SRC_DIR"
    success "Source downloaded to $SRC_DIR"
fi

# ── Step 3: Python dependencies ───────────────────────────────────────────────
step "Installing Python dependencies"

# Prefer system python3-pil; use pip only for what's still missing
NEEDS_PIP=()
python3 -c "from PIL import Image" 2>/dev/null || NEEDS_PIP+=("Pillow>=10.0.0")
python3 -c "import setproctitle"  2>/dev/null || NEEDS_PIP+=("setproctitle>=1.3.0")

if [[ ${#NEEDS_PIP[@]} -gt 0 ]]; then
    info "Installing Python packages via pip (user install): ${NEEDS_PIP[*]}"

    # Ensure pip is available
    if ! python3 -m pip --version &>/dev/null 2>&1; then
        if command -v sudo &>/dev/null; then
            sudo apt-get install -y -qq python3-pip 2>/dev/null || true
        fi
    fi

    PIP_FLAGS=(--quiet --user)

    # Ubuntu 23.04+ enforces PEP 668: allow user-install with --break-system-packages
    if python3 -m pip install --help 2>&1 | grep -q -- '--break-system-packages'; then
        PIP_FLAGS+=(--break-system-packages)
    fi

    python3 -m pip install "${PIP_FLAGS[@]}" "${NEEDS_PIP[@]}" || {
        warn "pip install failed. Trying without --quiet for more detail..."
        python3 -m pip install --user "${NEEDS_PIP[@]}" || {
            error "Could not install Python dependencies. Please run manually:"
            echo "    pip3 install --user ${NEEDS_PIP[*]}"
            exit 1
        }
    }
    success "Python dependencies installed"
else
    success "Python dependencies already satisfied"
fi

# ── Step 4: Install application files ─────────────────────────────────────────
step "Installing Klipora"

mkdir -p "$BIN_DIR" "$APP_DIR" "$DESKTOP_DIR" "$ICONS_DIR" "$AUTOSTART_DIR"

# 4a. Copy application source
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp "$SRC_DIR/app.py" "$APP_DIR/"
chmod 755 "$APP_DIR/app.py"

for pkg in clipboard ui config; do
    if [[ -d "$SRC_DIR/$pkg" ]]; then
        cp -r "$SRC_DIR/$pkg" "$APP_DIR/"
        find "$APP_DIR/$pkg" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        find "$APP_DIR/$pkg" -name "*.pyc"       -delete                       2>/dev/null || true
    fi
done

# 4b. Install executable launcher
cat > "$BIN_DIR/klipora" << 'LAUNCHER_EOF'
#!/bin/sh
exec /usr/bin/python3 "$HOME/.local/share/klipora-app/app.py" "$@"
LAUNCHER_EOF
chmod 755 "$BIN_DIR/klipora"

# Clean up any old product-name launchers
rm -f "$BIN_DIR/clipnova" "$BIN_DIR/clipshelf" "$BIN_DIR/ubuntu-clipboard"

# 4c. Desktop launcher
if [[ -f "$SRC_DIR/resources/com.kashyap.Klipora.desktop" ]]; then
    sed "s|Exec=klipora|Exec=$BIN_DIR/klipora|g" \
        "$SRC_DIR/resources/com.kashyap.Klipora.desktop" \
        > "$DESKTOP_DIR/com.kashyap.Klipora.desktop"
    chmod 644 "$DESKTOP_DIR/com.kashyap.Klipora.desktop"
fi

# 4d. Icons
if [[ -d "$SRC_DIR/resources/icons" ]]; then
    cp -r "$SRC_DIR/resources/icons/"* "$ICONS_DIR/"
fi

# 4e. Autostart entry
if [[ -f "$SRC_DIR/resources/com.kashyap.Klipora.autostart.desktop" ]]; then
    sed "s|Exec=klipora|Exec=$BIN_DIR/klipora|g" \
        "$SRC_DIR/resources/com.kashyap.Klipora.autostart.desktop" \
        > "$AUTOSTART_DIR/com.kashyap.Klipora.desktop"
    chmod 644 "$AUTOSTART_DIR/com.kashyap.Klipora.desktop"
fi

success "Klipora application files installed"

# ── Step 5: GNOME Shell Extension ────────────────────────────────────────────
step "Installing GNOME Shell Extension (optional)"

if [[ -d "$SRC_DIR/gnome-shell-extension" ]]; then
    mkdir -p "$EXT_DIR"
    cp -r "$SRC_DIR/gnome-shell-extension/"* "$EXT_DIR/"

    if command -v glib-compile-schemas &>/dev/null && [[ -d "$EXT_DIR/schemas" ]]; then
        glib-compile-schemas "$EXT_DIR/schemas" 2>/dev/null && \
            success "GNOME extension schemas compiled" || \
            warn "Schema compilation failed — extension may not load"
    fi

    # Enable extension (fails gracefully if no GNOME session is active)
    if command -v gnome-extensions &>/dev/null; then
        gnome-extensions enable klipora@kashyap.com 2>/dev/null && \
            success "GNOME Shell extension enabled" || \
            warn "Could not enable GNOME extension automatically. Run: gnome-extensions enable klipora@kashyap.com"
    fi
else
    warn "GNOME Shell extension source not found — skipping"
fi

# ── Step 6: Update desktop caches ────────────────────────────────────────────
step "Updating desktop database"

command -v update-desktop-database &>/dev/null && \
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache &>/dev/null && \
    gtk-update-icon-cache -q -t -f "$ICONS_DIR/hicolor" 2>/dev/null || true

success "Desktop caches refreshed"

# ── Step 7: PATH check ────────────────────────────────────────────────────────
PATH_OK=false
if echo "$PATH" | grep -q "$HOME/.local/bin"; then
    PATH_OK=true
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗"
echo -e "║       🎉  Klipora installed successfully!        ║"
echo -e "╚══════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}Launch now:${RESET}"
echo -e "    ${CYAN}$BIN_DIR/klipora${RESET}"
echo ""

if [[ "$PATH_OK" == false ]]; then
    echo -e "  ${YELLOW}${BOLD}⚠  Add ~/.local/bin to your PATH:${RESET}"
    echo -e "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    echo -e "    source ~/.bashrc"
    echo ""
    echo -e "  ${BOLD}Then you can simply run:${RESET}  ${CYAN}klipora${RESET}"
else
    echo -e "  ${BOLD}Or from anywhere:${RESET}  ${CYAN}klipora${RESET}"
fi

echo ""
echo -e "  ${BOLD}Global shortcut:${RESET}  ${CYAN}Super + V${RESET}  (registered automatically)"
echo -e "  ${BOLD}Autostart:${RESET}        Klipora starts at login automatically"
echo ""
echo -e "  ${BOLD}Uninstall later:${RESET}"
echo -e "    ${CYAN}bash $SRC_DIR/packaging/uninstall_user.sh${RESET}"
echo ""

# Optionally start daemon now
if [[ -x "$BIN_DIR/klipora" ]]; then
    if ! pgrep -f "klipora-app/app.py" &>/dev/null; then
        info "Starting Klipora in the background..."
        nohup "$BIN_DIR/klipora" --background >/dev/null 2>&1 &
        disown
        sleep 1
        if pgrep -f "klipora-app/app.py" &>/dev/null; then
            success "Klipora is now running in the background!"
        else
            warn "Could not auto-start Klipora. Run it manually: $BIN_DIR/klipora"
        fi
    else
        success "Klipora is already running."
    fi
fi

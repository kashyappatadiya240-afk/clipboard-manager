import hashlib
import io
import os
import pathlib
import subprocess
import sys
import time
from PIL import Image

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib


def make_png(w=64, h=64, color=(120, 40, 200, 255)):
    img = Image.new("RGBA", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_lifecycle_and_shortcut():
    print("=== Testing Phase 7 Bug Fix: Lifecycle and Shortcut ===", flush=True)

    project_root = pathlib.Path(__file__).resolve().parent.parent
    python_bin = sys.executable
    app_script = project_root / "app.py"

    # Step 1: Ensure clean state
    subprocess.run(["pkill", "-x", "ubuntu-clipboard"], capture_output=True)
    for _ in range(30):
        if subprocess.run(["pgrep", "-x", "ubuntu-clipboard"], capture_output=True).returncode != 0:
            break
        time.sleep(0.1)
    time.sleep(0.3)

    # Test 1 & 2: Application launch, stays alive, and process title in ps aux
    print("\n--- Test 1: Application starts and stays alive ---", flush=True)
    primary = subprocess.Popen(
        [python_bin, str(app_script)],
        env={**os.environ, "PYTHONPATH": str(project_root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(1.2)
    assert primary.poll() is None, "Primary application must remain alive"

    # Verify ps aux finds ubuntu-clipboard
    ps_out = subprocess.check_output(["sh", "-c", "ps aux | grep -i [u]buntu-clipboard"]).decode().strip()
    print("ps aux grep matched:\n", ps_out)
    assert "ubuntu-clipboard" in ps_out
    print("PASS: Test 1 Application remains alive and is named 'ubuntu-clipboard'", flush=True)

    # Test 2: Second invocation activates existing instance with clear feedback
    print("\n--- Test 2: Secondary launch activates existing instance ---", flush=True)
    sec = subprocess.run(
        [python_bin, str(app_script)],
        env={**os.environ, "PYTHONPATH": str(project_root)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    print("Secondary stdout:", sec.stdout.strip())
    assert sec.returncode == 0, f"Secondary must return 0, got {sec.returncode}"
    assert "Ubuntu Clipboard is already running" in sec.stdout
    assert primary.poll() is None, "Primary must still be running"
    print("PASS: Test 2 Secondary launch cleanly activates existing instance", flush=True)

    # Test 3: Shortcut registration in GSettings
    print("\n--- Test 3: Shortcut GSettings verification ---", flush=True)
    media_settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
    custom_list = list(media_settings.get_strv("custom-keybindings"))
    expected_path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ubuntu-clipboard/"
    assert expected_path in custom_list, "ubuntu-clipboard path must be in custom-keybindings"

    binding_settings = Gio.Settings.new_with_path(
        "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding",
        expected_path,
    )
    name = binding_settings.get_string("name")
    binding = binding_settings.get_string("binding")
    command = binding_settings.get_string("command")
    print(f"GSettings entry: name='{name}', binding='{binding}', command='{command}'")

    assert name == "Ubuntu Clipboard History"
    assert binding.lower() == "<super>v"
    assert not command.startswith('"'), "Command must not have leading literal quote"
    assert not command.endswith('"'), "Command must not have trailing literal quote"
    assert python_bin in command
    assert "app.py" in command
    print("PASS: Test 3 GSettings custom-keybinding has clean, valid command and shortcut", flush=True)

    # Test 4: Terminate primary and test launch via shortcut command (simulating GNOME Super+V)
    print("\n--- Test 4: Launch via shortcut command when NOT running ---", flush=True)
    primary.terminate()
    primary.wait(timeout=3)
    time.sleep(0.5)

    # Execute exact command configured in GSettings
    shortcut_proc = subprocess.Popen(
        command.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(1.2)
    assert shortcut_proc.poll() is None, "Application launched via shortcut command must stay alive"
    print("PASS: Test 4 Shortcut command launches application when not running", flush=True)

    # Test 5: Shortcut command when ALREADY running
    print("\n--- Test 5: Shortcut command when ALREADY running ---", flush=True)
    shortcut_sec = subprocess.run(
        command.split(),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert shortcut_sec.returncode == 0
    assert "Ubuntu Clipboard is already running" in shortcut_sec.stdout
    assert shortcut_proc.poll() is None, "Primary must still be running"
    print("PASS: Test 5 Shortcut command activates existing instance without spawning duplicate", flush=True)

    # Cleanup
    shortcut_proc.terminate()
    shortcut_proc.wait(timeout=3)
    print("\n>>> ALL BUG-FIX LIFECYCLE TESTS PASSED! <<<", flush=True)


if __name__ == "__main__":
    test_lifecycle_and_shortcut()

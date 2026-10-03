import os
import pathlib
import subprocess
import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib


def test_single_instance_real_dbus():
    print("=== Testing Single Instance D-Bus IPC Activation ===", flush=True)
    project_root = pathlib.Path(__file__).resolve().parent.parent
    app_script = project_root / "app.py"
    python_bin = sys.executable

    # Start primary application process
    primary = subprocess.Popen(
        [python_bin, str(app_script)],
        env={**os.environ, "PYTHONPATH": str(project_root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait up to 3 seconds for D-Bus registration
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        registered = False
        for _ in range(30):
            names = bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ListNames",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            name_list = names.unpack()[0]
            if "com.kashyap.UbuntuClipboard" in name_list:
                registered = True
                break
            time.sleep(0.1)

        assert registered is True, "com.kashyap.UbuntuClipboard must be registered on D-Bus"
        print("PASS: Primary application registered on session D-Bus", flush=True)

        # Launch secondary process (simulating Super+V keypress)
        start_t = time.time()
        secondary = subprocess.run(
            [python_bin, str(app_script)],
            env={**os.environ, "PYTHONPATH": str(project_root)},
            capture_output=True,
            text=True,
            timeout=5,
        )
        duration = time.time() - start_t
        print(f"PASS: Secondary invocation returned {secondary.returncode} in {duration:.2f}s", flush=True)
        assert secondary.returncode == 0, f"Secondary must return 0, got {secondary.returncode}"

        # Test GIO Action 'show-history' via D-Bus
        app_proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "com.kashyap.UbuntuClipboard",
            "/com/kashyap/UbuntuClipboard",
            "org.gtk.Actions",
            None,
        )
        actions = app_proxy.call_sync("List", None, Gio.DBusCallFlags.NONE, -1, None)
        action_names = actions.unpack()[0]
        print(f"Available application actions: {action_names}", flush=True)
        assert "show-history" in action_names, "'show-history' action must be present"
        assert "quit" in action_names, "'quit' action must be present"
        print("PASS: Application exposes show-history and quit actions", flush=True)

        # Trigger quit action via D-Bus to cleanly terminate primary instance
        app_proxy.call_sync(
            "Activate",
            GLib.Variant("(sava{sv})", ("quit", [], {})),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )

        stdout, stderr = primary.communicate(timeout=3)
        print("Primary shutdown cleanly. Exit code:", primary.returncode, flush=True)
        assert primary.returncode == 0
        print(">>> ALL SINGLE INSTANCE D-BUS IPC TESTS PASSED! <<<", flush=True)

    finally:
        if primary.poll() is None:
            primary.kill()


if __name__ == "__main__":
    from gi.repository import GLib

    test_single_instance_real_dbus()

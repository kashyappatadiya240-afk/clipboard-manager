import os
import sys
import pathlib
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gdk, GLib, Gio

from clipboard.database import ClipboardDatabase
from clipboard.monitor import ClipboardMonitor
from ui.window import ClipboardWindow


def main():
    test_db = pathlib.Path("/tmp/test_manual_clean_final.db")
    if test_db.exists():
        test_db.unlink()

    db = ClipboardDatabase(db_path=test_db)
    db.initialize()

    app = Adw.Application(
        application_id="com.kashyap.TestManualAcceptanceFinal",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_activate(app):
        print("ON_ACTIVATE START", flush=True)
        app.hold()
        display = Gdk.Display.get_default()
        clipboard = display.get_clipboard()

        def start_test():
            win = None

            def on_captured(item):
                if not item.content.startswith("PHASE 5 REAL TEST"):
                    return
                print(f"[EVENT] Clipboard captured: {item.content}", flush=True)
                if win:
                    win.add_clipboard_item(item)
                    on_step(item.content)

            monitor = ClipboardMonitor(database=db, on_new_item=on_captured)
            monitor.start()

            # Ensure db is empty
            for it in db.get_items():
                db.delete_item(it.id)

            win = ClipboardWindow(application=app, database=db, monitor=monitor)
            win.present()

            print("=== Step 1: Application started with empty history ===", flush=True)
            assert len(win._items) == 0, f"Expected 0 items, got {len(win._items)}"
            assert win.stack.get_visible_child_name() == "empty"
            print("PASS: Step 1 Empty history", flush=True)

            current_step = 1

            def on_step(content):
                nonlocal current_step
                if current_step == 1 and content == "PHASE 5 REAL TEST A":
                    print("Step 2a: Captured A. Now copying B...", flush=True)
                    current_step = 2
                    GLib.timeout_add(150, lambda: clipboard.set("PHASE 5 REAL TEST B"))
                elif current_step == 2 and content == "PHASE 5 REAL TEST B":
                    print("Step 2b: Captured B.", flush=True)
                    current_step = 3
                    GLib.idle_add(run_step_3_to_6)
                elif current_step == 7 and content == "PHASE 5 REAL TEST C":
                    print("Step 7a: Captured C.", flush=True)
                    GLib.idle_add(run_step_7b)

            def run_step_3_to_6():
                nonlocal current_step
                rows = [win.list_box.get_row_at_index(i).item.content for i in range(2)]
                print(f"Rows after copy A and B: {rows}", flush=True)
                assert rows == ["PHASE 5 REAL TEST B", "PHASE 5 REAL TEST A"]

                print("=== Step 3: Pin PHASE 5 REAL TEST A ===", flush=True)
                row_a = [
                    win.list_box.get_row_at_index(i)
                    for i in range(2)
                    if win.list_box.get_row_at_index(i).item.content == "PHASE 5 REAL TEST A"
                ][0]
                win.toggle_pin_item(row_a.item)
                rows_pinned = [win.list_box.get_row_at_index(i).item.content for i in range(2)]
                print(f"Rows after pinning A: {rows_pinned}", flush=True)
                assert rows_pinned == ["PHASE 5 REAL TEST A", "PHASE 5 REAL TEST B"]
                assert win.list_box.get_row_at_index(0).pin_icon.get_visible()
                print("PASS: Step 3 Pin", flush=True)

                print("=== Step 4: Search PHASE 5 ===", flush=True)
                win.search_entry.set_text("PHASE 5")
                win.apply_filter("PHASE 5")
                s_rows = [win.list_box.get_row_at_index(i).item.content for i in range(2)]
                print(f"Search rows: {s_rows}", flush=True)
                assert s_rows == ["PHASE 5 REAL TEST A", "PHASE 5 REAL TEST B"]
                print("PASS: Step 4 Search", flush=True)

                print("=== Step 5: Delete PHASE 5 REAL TEST B ===", flush=True)
                row_b = [
                    win.list_box.get_row_at_index(i)
                    for i in range(2)
                    if win.list_box.get_row_at_index(i).item.content == "PHASE 5 REAL TEST B"
                ][0]
                win.delete_item(row_b.item)
                del_rows = [
                    win.list_box.get_row_at_index(i).item.content
                    for i in range(2)
                    if win.list_box.get_row_at_index(i)
                ]
                print(f"Rows after deleting B: {del_rows}", flush=True)
                assert del_rows == ["PHASE 5 REAL TEST A"]
                print("PASS: Step 5 Delete", flush=True)

                print("=== Step 6: Clear the search ===", flush=True)
                win.search_entry.set_text("")
                win.apply_filter("")
                clr_rows = [
                    win.list_box.get_row_at_index(i).item.content
                    for i in range(2)
                    if win.list_box.get_row_at_index(i)
                ]
                print(f"Rows after clearing search: {clr_rows}", flush=True)
                assert clr_rows == ["PHASE 5 REAL TEST A"]
                print("PASS: Step 6 Clear search", flush=True)

                print("=== Step 7: Copy PHASE 5 REAL TEST C ===", flush=True)
                current_step = 7
                clipboard.set("PHASE 5 REAL TEST C")

            def run_step_7b():
                rows_with_c = [win.list_box.get_row_at_index(i).item.content for i in range(2)]
                print(f"Rows with C: {rows_with_c}", flush=True)
                assert "PHASE 5 REAL TEST C" in rows_with_c
                assert "PHASE 5 REAL TEST A" in rows_with_c

                print("=== Invoking Clear History (only unpinned should be deleted) ===", flush=True)
                win.clear_history()
                rows_post_clear = [
                    win.list_box.get_row_at_index(i).item.content
                    for i in range(5)
                    if win.list_box.get_row_at_index(i)
                ]
                print(f"Rows post clear: {rows_post_clear}", flush=True)
                assert rows_post_clear == ["PHASE 5 REAL TEST A"]
                print("PASS: Step 7 Clear History (Pinned A preserved, C removed)", flush=True)

                print("=== Step 8: Verify system clipboard still contains PHASE 5 REAL TEST C ===", flush=True)

                def on_read_text(clip, res):
                    try:
                        text = clip.read_text_finish(res)
                        print(f"System clipboard is: {repr(text)}", flush=True)
                        assert text == "PHASE 5 REAL TEST C"
                        print("PASS: Step 8 System clipboard preserved", flush=True)
                    except Exception as e:
                        print(f"Error reading clipboard: {e}", flush=True)
                        sys.exit(1)

                    print("=== Step 9: Restart app and verify persistence ===", flush=True)
                    monitor.stop()
                    db.close()
                    win.close()

                    db2 = ClipboardDatabase(db_path=test_db)
                    db2.initialize()
                    restarted = db2.get_items()
                    print(
                        f"Restarted items: {[(it.content, it.is_pinned) for it in restarted]}",
                        flush=True,
                    )
                    assert len(restarted) == 1
                    assert restarted[0].content == "PHASE 5 REAL TEST A"
                    assert restarted[0].is_pinned is True
                    db2.close()
                    print("PASS: Step 9 Restart persistence", flush=True)
                    print("\n>>> MANUAL ACCEPTANCE TEST STEPS 1-9 COMPLETELY PASSED! <<<", flush=True)
                    app.quit()

                GLib.timeout_add(150, lambda: clipboard.read_text_async(None, on_read_text))

            print("=== Step 2: Copying PHASE 5 REAL TEST A ===", flush=True)
            GLib.timeout_add(150, lambda: clipboard.set("PHASE 5 REAL TEST A"))

        GLib.timeout_add(150, start_test)

    app.connect("activate", on_activate)
    return app.run(None)


if __name__ == "__main__":
    sys.exit(main())

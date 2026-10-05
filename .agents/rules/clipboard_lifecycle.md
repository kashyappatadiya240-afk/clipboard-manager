# Clipboard Picker Lifecycle & Packaging Invariants

1. **Persistent Picker on Copy**:
   - Copying an item (text or image) from the clipboard picker must NEVER close, hide, or terminate the window.
   - The clipboard window must remain open so the user can inspect history, see copy feedback, or select additional items.
   - The window must ONLY close upon explicit user action: pressing `Escape`, clicking the close button, or toggling with the global shortcut `Super+V`.

2. **System Installation Synchronization**:
   - Whenever lifecycle, UI, or copying behavior is modified in the repository, any installed versions (`/usr/share/klipora/` or `~/.local/share/klipora-app/`) must be updated or rebuilt, so that launching the app from the GNOME application launcher reflects the changes.

3. **Process Matching Safety**:
   - Linux process names set via `prctl(PR_SET_NAME)` are limited to 15 characters (`TASK_COMM_LEN=16` with null byte). When matching `klipora` processes in tests or scripts, use `pkill -f` / `pgrep -f` (matching the full command line / proctitle) rather than `pkill -x` to avoid silent truncation failures.

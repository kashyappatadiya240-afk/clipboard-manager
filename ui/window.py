import logging
from typing import List, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from clipboard.database import ClipboardDatabase
from clipboard.models import ClipboardItem
from clipboard.monitor import ClipboardMonitor
from ui.clipboard_row import ClipboardRow, clear_thumbnail_cache

logger = logging.getLogger(__name__)


class ClipboardWindow(Adw.ApplicationWindow):
    """Main window for the Ubuntu Clipboard Manager with history management and launcher support."""

    def __init__(
        self,
        database: ClipboardDatabase,
        monitor: Optional[ClipboardMonitor] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.database = database
        self.monitor = monitor
        self._items: List[ClipboardItem] = []
        self._current_query: str = ""

        self.set_title("Ubuntu Clipboard")
        self.set_default_size(540, 680)
        self.set_size_request(420, 520)

        # Polished GNOME / Libadwaita styling for cards, lists, and previews
        css = """
        /* History list container: transparent background so cards float cleanly */
        .clipboard-history-list {
            background-color: transparent;
        }

        /* Individual Clipboard Item Card */
        .clipboard-card {
            border-radius: 12px;
            margin-bottom: 8px;
            background-color: @card_bg_color;
            color: @card_fg_color;
            border: 1px solid alpha(currentColor, 0.08);
            transition: background-color 150ms ease-in-out, border-color 150ms ease-in-out, outline 150ms ease-in-out;
        }

        /* Subtle hover feedback */
        .clipboard-card:hover {
            background-color: alpha(currentColor, 0.035);
            border-color: alpha(currentColor, 0.14);
        }

        /* Focused / Selected feedback: subtle neutral tint with accent outline (no peach/pink wash) */
        .clipboard-card:selected,
        .clipboard-card:selected:hover,
        .clipboard-card:selected:focus {
            background-color: alpha(currentColor, 0.05);
            color: @card_fg_color;
            border-color: alpha(@accent_color, 0.5);
            outline: 2px solid alpha(@accent_color, 0.6);
            outline-offset: -2px;
        }

        .clipboard-card:focus:not(:selected) {
            outline: 2px solid alpha(@accent_color, 0.4);
            outline-offset: -2px;
        }

        /* Pinned item card: subtle accent indicator on left and subtle warm tint */
        .clipboard-card.pinned-row {
            border-left: 3.5px solid @accent_color;
            background-color: alpha(@accent_color, 0.035);
        }

        .clipboard-card.pinned-row:hover {
            background-color: alpha(@accent_color, 0.07);
            border-color: alpha(currentColor, 0.14);
            border-left-color: @accent_color;
        }

        .clipboard-card.pinned-row:selected,
        .clipboard-card.pinned-row:selected:focus {
            background-color: alpha(@accent_color, 0.08);
            color: @card_fg_color;
            border-left: 3.5px solid @accent_color;
            outline: 2px solid alpha(@accent_color, 0.7);
            outline-offset: -2px;
        }

        /* Neutral image preview frame */
        .image-preview-box {
            border-radius: 8px;
            background-color: alpha(currentColor, 0.03);
            padding: 6px;
            border: 1px solid alpha(currentColor, 0.06);
        }

        /* Compact action buttons */
        .action-btn {
            border-radius: 6px;
            padding: 4px;
            min-width: 28px;
            min-height: 28px;
        }
        """
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(css)
        else:
            provider.load_from_data(css.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        # Intercept close request so the window hides rather than destroying itself
        self.connect("close-request", self._on_close_request)

        # Global key controller for window-level Escape handling
        win_key_ctrl = Gtk.EventControllerKey()
        win_key_ctrl.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(win_key_ctrl)

        # Main vertical container wrapped in ToastOverlay
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(main_box)
        self.set_content(self.toast_overlay)

        # 1. Header bar
        header_bar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title="Clipboard", subtitle="Ubuntu Clipboard")
        header_bar.set_title_widget(title_widget)

        # Clear history button in header bar
        self.clear_btn = Gtk.Button()
        self.clear_btn.set_icon_name("user-trash-symbolic")
        self.clear_btn.set_tooltip_text("Clear unpinned history")
        self.clear_btn.connect("clicked", self._on_clear_clicked)
        header_bar.pack_end(self.clear_btn)

        main_box.append(header_bar)

        # 2. Search bar container (fixed at top, consistent margins)
        search_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        search_box.set_margin_start(16)
        search_box.set_margin_end(16)
        search_box.set_margin_top(12)
        search_box.set_margin_bottom(8)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search clipboard...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("stop-search", self._on_stop_search)
        self.search_entry.connect("activate", self._on_search_entry_activated)

        # Key controller on search entry to support Arrow Down into history
        search_key_ctrl = Gtk.EventControllerKey()
        search_key_ctrl.connect("key-pressed", self._on_search_key_pressed)
        self.search_entry.add_controller(search_key_ctrl)

        search_box.append(self.search_entry)
        main_box.append(search_box)

        # 3. View stack: displays Empty History, No Search Results, or ScrolledWindow list
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        main_box.append(self.stack)

        # Empty-state status page (when database has no history at all)
        self.status_page = Adw.StatusPage()
        self.status_page.set_icon_name("edit-paste-symbolic")
        self.status_page.set_title("Clipboard is empty")
        self.status_page.set_description(
            "Copy text or an image to start building your clipboard history."
        )
        self.stack.add_named(self.status_page, "empty")

        # No-results status page (when search produces zero matches)
        self.no_results_page = Adw.StatusPage()
        self.no_results_page.set_icon_name("system-search-symbolic")
        self.no_results_page.set_title("No matching clips")
        self.no_results_page.set_description("Try another search term.")
        self.stack.add_named(self.no_results_page, "no_results")

        # Scrollable history container
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        list_container.set_margin_start(16)
        list_container.set_margin_end(16)
        list_container.set_margin_top(4)
        list_container.set_margin_bottom(16)

        # History listbox with single selection & row activation (cards provide own borders)
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class("clipboard-history-list")
        self.list_box.set_show_separators(False)
        self.list_box.connect("row-activated", self._on_row_activated)

        # Key controller on listbox to allow Arrow Up back into search entry
        list_key_ctrl = Gtk.EventControllerKey()
        list_key_ctrl.connect("key-pressed", self._on_list_key_pressed)
        self.list_box.add_controller(list_key_ctrl)

        list_container.append(self.list_box)

        self.scrolled_window.set_child(list_container)
        self.stack.add_named(self.scrolled_window, "history")

        # Load existing history from SQLite
        self._load_history()

        # Connect focus check if monitor was provided
        if self.monitor:
            self.connect_monitor(self.monitor)

    def _on_close_request(self, window: Gtk.Window) -> bool:
        """Hides the window instead of destroying it when closed."""
        self.hide_window()
        return True

    def hide_window(self) -> None:
        """Closes/hides the clipboard history window and resets search query."""
        logger.info("Hiding clipboard history window...")
        self.search_entry.set_text("")
        self.set_visible(False)

    def present_history(self) -> None:
        """Brings the clipboard history window to the foreground with initial focus."""
        logger.info("Presenting clipboard history window...")
        self.set_visible(True)
        self.present()
        self.focus_search_or_list()

    def focus_search_or_list(self) -> None:
        """Focuses the search entry and highlights the first history row if available."""
        self.search_entry.grab_focus()
        first_row = self.list_box.get_row_at_index(0)
        if first_row:
            self.list_box.select_row(first_row)

    def _on_window_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Handles window-level shortcut keys."""
        if keyval == Gdk.KEY_Escape:
            self.hide_window()
            return True
        return False

    def _on_search_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Handles key events inside the search entry."""
        if keyval == Gdk.KEY_Escape:
            self.hide_window()
            return True
        elif keyval == Gdk.KEY_Down:
            target_row = (
                self.list_box.get_selected_row()
                or self.list_box.get_row_at_index(0)
            )
            if target_row:
                self.list_box.select_row(target_row)
                target_row.grab_focus()
                return True
        return False

    def _on_list_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Handles key events inside the history listbox."""
        if keyval == Gdk.KEY_Escape:
            self.hide_window()
            return True
        elif keyval == Gdk.KEY_Up:
            selected = self.list_box.get_selected_row()
            if selected and selected.get_index() == 0:
                self.search_entry.grab_focus()
                return True
        return False

    def _on_search_entry_activated(self, entry: Gtk.SearchEntry) -> None:
        """Invoked when user presses Enter inside the search entry."""
        self.activate_selected_item()

    def activate_selected_item(self) -> bool:
        """Activates the currently selected row or top result."""
        selected = (
            self.list_box.get_selected_row()
            or self.list_box.get_row_at_index(0)
        )
        if selected and isinstance(selected, ClipboardRow):
            self._on_row_activated(self.list_box, selected)
            return True
        return False

    def copy_item(self, item: ClipboardItem) -> None:
        """Copies item content or original image to system clipboard and smoothly hides window."""
        self.copy_item_to_clipboard(item, hide_after=True)

    def copy_item_to_clipboard(
        self, item: ClipboardItem, hide_after: bool = True
    ) -> bool:
        """Copies an item (text or image) to system clipboard and optionally hides window."""
        if self.monitor:
            if item.content_type == "image":
                if item.image_path:
                    self.monitor.copy_image(item.image_path)
                else:
                    logger.warning("Cannot copy image: missing image path")
                    return False
            else:
                self.monitor.copy_text(item.content or "")
        if hide_after:
            GLib.timeout_add(150, self.hide_window)
        return True

    def _on_row_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Handles row click or Enter activation to copy full original content."""
        if isinstance(row, ClipboardRow):
            self.copy_item_to_clipboard(row.item, hide_after=True)
            row.show_copied_feedback()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Invoked when the search entry text changes."""
        self.apply_filter(entry.get_text())

    def _on_stop_search(self, entry: Gtk.SearchEntry) -> None:
        """Invoked when the user cancels search (e.g. presses Escape)."""
        self.hide_window()

    def _sort_items(self) -> None:
        """Sorts history items with pinned items first, then newest unpinned items."""
        self._items.sort(key=lambda it: (it.is_pinned, it.id), reverse=True)

    def apply_filter(self, query: str) -> None:
        """Filters the clipboard history based on the search query."""
        cleaned_query = query.strip().casefold()
        self._current_query = cleaned_query

        self._update_clear_button_state()

        # If no clipboard items exist in history at all
        if not self._items:
            self.list_box.remove_all()
            self.stack.set_visible_child_name("empty")
            return

        # If search query is empty, display all items (pinned first)
        if not cleaned_query:
            self._render_rows(self._items)
            self.stack.set_visible_child_name("history")
            return

        # Search against full original text content (case-insensitive substring)
        # Image items do not match text search queries
        matching_items = [
            item
            for item in self._items
            if item.content and cleaned_query in item.content.casefold()
        ]

        if matching_items:
            self._render_rows(matching_items)
            self.stack.set_visible_child_name("history")
        else:
            self.list_box.remove_all()
            self.stack.set_visible_child_name("no_results")

    def _render_rows(self, items: List[ClipboardItem]) -> None:
        """Populates list_box with ClipboardRow instances for given items."""
        self.list_box.remove_all()
        for item in items:
            row = ClipboardRow(
                item=item,
                on_copy=self.copy_item,
                on_toggle_pin=self.toggle_pin_item,
                on_delete=self.delete_item,
            )
            self.list_box.append(row)
        first_row = self.list_box.get_row_at_index(0)
        if first_row:
            self.list_box.select_row(first_row)

    def show_toast(self, message: str) -> None:
        """Displays a temporary in-app toast notification."""
        toast = Adw.Toast.new(message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def _load_history(self) -> None:
        """Loads items from database (up to max pinned + max unpinned) and displays them (pinned first)."""
        limit = getattr(self.database, "MAX_PINNED_ITEMS", 10) + getattr(
            self.database, "MAX_UNPINNED_ITEMS", 20
        )
        self._items = self.database.get_items(limit=limit)
        self.apply_filter(self.search_entry.get_text())

    def add_clipboard_item(self, item: ClipboardItem) -> None:
        """Adds a newly captured clipboard item and enforces FIFO limitation."""
        existing = next((it for it in self._items if it.id == item.id), None)
        if existing:
            return

        self._items.append(item)
        self._sort_items()

        # Enforce max unpinned items (FIFO: drop excess oldest unpinned items)
        max_unpinned = getattr(self.database, "MAX_UNPINNED_ITEMS", 20)
        unpinned = [it for it in self._items if not it.is_pinned]
        if len(unpinned) > max_unpinned:
            excess = unpinned[max_unpinned:]
            excess_ids = {it.id for it in excess}
            for it in excess:
                if it.image_path:
                    clear_thumbnail_cache(it.image_path)
            self._items = [it for it in self._items if it.id not in excess_ids]

        query = self.search_entry.get_text() or self._current_query
        self.apply_filter(query)

    def toggle_pin_item(self, item: ClipboardItem) -> None:
        """Toggles pinned status for an item in database and updates UI."""
        if not item.is_pinned and hasattr(self.database, "can_pin") and not self.database.can_pin():
            self.show_toast("Pinned limit reached (maximum 10 items)")
            return

        new_state = self.database.toggle_pin(item.id)
        if new_state is None and not item.is_pinned:
            self.show_toast("Pinned limit reached (maximum 10 items)")
            return

        if new_state is not None:
            item.is_pinned = new_state
            self._load_history()

    def delete_item(self, item: ClipboardItem) -> None:
        """Permanently deletes a single item from database and updates UI."""
        if self.database.delete_item(item.id):
            if item.image_path:
                clear_thumbnail_cache(item.image_path)
            self._items = [it for it in self._items if it.id != item.id]
            query = self.search_entry.get_text() or self._current_query
            self.apply_filter(query)

    def _on_clear_clicked(self, button: Gtk.Button) -> None:
        """Prompts user confirmation before clearing unpinned clipboard history."""
        dialog = Adw.AlertDialog(
            heading="Clear clipboard history?",
            body="All unpinned clipboard items will be permanently deleted.\n\nPinned items will be kept.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear History")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(dlg, result):
            if isinstance(result, str):
                response = result
            else:
                try:
                    response = dlg.choose_finish(result)
                except Exception:
                    response = str(result)
            if response == "clear":
                self.clear_history()

        dialog.choose(self, None, on_response)

    def clear_history(self) -> None:
        """Clears all unpinned history from database and updates UI."""
        self.database.clear_history()
        clear_thumbnail_cache()
        self._items = [it for it in self._items if it.is_pinned]
        query = self.search_entry.get_text() or self._current_query
        self.apply_filter(query)

    def _update_clear_button_state(self) -> None:
        """Enables the Clear button only when unpinned items exist."""
        has_unpinned = any(not it.is_pinned for it in self._items)
        self.clear_btn.set_sensitive(has_unpinned)

    def set_monitor(self, monitor: ClipboardMonitor) -> None:
        """Sets the monitor and hooks focus activation."""
        self.monitor = monitor
        self.connect_monitor(monitor)

    def connect_monitor(self, monitor: ClipboardMonitor) -> None:
        """Watches window activation to trigger a clipboard check when the window is focused."""

        def on_active_changed(window, pspec):
            if window.get_property("is-active"):
                monitor.check_clipboard()

        self.connect("notify::is-active", on_active_changed)

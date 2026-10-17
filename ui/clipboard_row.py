import io
import logging
import pathlib
from datetime import datetime, timedelta
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango
from PIL import Image

from clipboard.models import ClipboardItem

logger = logging.getLogger(__name__)

# In-memory thumbnail cache to avoid repeatedly decoding full-resolution images
_THUMBNAIL_CACHE: dict[str, Gdk.Texture] = {}


def get_thumbnail_texture(
    image_path: Optional[str],
    max_width: int = 360,
    max_height: int = 160,
) -> Optional[Gdk.Texture]:
    """Generates and caches a bounded aspect-ratio-preserving thumbnail texture."""
    if not image_path:
        return None

    if image_path in _THUMBNAIL_CACHE:
        return _THUMBNAIL_CACHE[image_path]

    try:
        p = pathlib.Path(image_path)
        if not p.exists():
            return None

        with Image.open(p) as img:
            # Create bounded thumbnail preserving original aspect ratio without upscaling
            img = img.convert("RGBA")
            img.thumbnail((max_width, max_height), Image.Resampling.BILINEAR)
            w, h = img.size
            raw_bytes = img.tobytes()
            gbytes = GLib.Bytes.new(raw_bytes)
            texture = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8A8, gbytes, w * 4)
            _THUMBNAIL_CACHE[image_path] = texture
            return texture
    except Exception as e:
        logger.error("Failed to generate thumbnail for %s: %s", image_path, e)
        return None


def clear_thumbnail_cache(image_path: Optional[str] = None) -> None:
    """Evicts a specific image or all images from the in-memory thumbnail cache."""
    if image_path:
        _THUMBNAIL_CACHE.pop(image_path, None)
    else:
        _THUMBNAIL_CACHE.clear()


def format_timestamp(iso_str: str) -> str:
    """Formats an ISO-8601 UTC timestamp into a human-friendly string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        local_dt = dt.astimezone()
        now = datetime.now(local_dt.tzinfo)

        today = now.date()
        item_date = local_dt.date()
        time_str = local_dt.strftime("%H:%M")

        if item_date == today:
            return f"Today, {time_str}"
        elif item_date == today - timedelta(days=1):
            return f"Yesterday, {time_str}"
        elif item_date.year == today.year:
            return f"{local_dt.strftime('%d %b')}, {time_str}"
        else:
            return f"{local_dt.strftime('%d %b %Y')}, {time_str}"
    except Exception:
        return iso_str


def create_visual_preview(
    content: Optional[str],
    max_lines: int = 3,
    chars_per_line: int = 65,
) -> str:
    """Creates a compact visual preview constrained to approximately max_lines.

    The original item.content is never modified and remains fully intact for storage,
    clipboard copying, and full-content search.
    """
    if not content:
        return ""

    raw_lines = content.splitlines()
    if not raw_lines:
        return ""

    collected = []
    lines_used = 0
    has_more = False

    for i, line in enumerate(raw_lines):
        remaining_budget = max_lines - lines_used
        if remaining_budget <= 0:
            has_more = True
            break

        stripped = line.rstrip()
        line_len = len(stripped)
        if line_len == 0:
            collected.append("")
            lines_used += 1
        else:
            wrapped_lines = (line_len + chars_per_line - 1) // chars_per_line
            if wrapped_lines <= remaining_budget:
                collected.append(stripped)
                lines_used += max(1, wrapped_lines)
            else:
                max_chars = remaining_budget * chars_per_line
                truncated = stripped[:max_chars].rstrip()
                collected.append(truncated)
                lines_used += remaining_budget
                has_more = True
                break

    if i < len(raw_lines) - 1:
        has_more = True

    preview = "\n".join(collected)
    if has_more and not preview.endswith("…"):
        preview = preview.rstrip() + "…"

    return preview


class ClipboardRow(Gtk.ListBoxRow):
    """Reusable GTK4 row component for displaying and managing a clipboard history item."""

    def __init__(
        self,
        item: ClipboardItem,
        on_toggle_pin: Optional[Callable[[ClipboardItem], None]] = None,
        on_delete: Optional[Callable[[ClipboardItem], None]] = None,
        on_copy: Optional[Callable[[ClipboardItem], None]] = None,
    ):
        super().__init__()
        self.item = item
        self.on_toggle_pin = on_toggle_pin
        self.on_delete = on_delete
        self.on_copy = on_copy
        self._feedback_timer_id: Optional[int] = None

        self._is_hovered: bool = False
        self._is_focused: bool = False
        self._popover_open: bool = False

        self.set_activatable(True)
        self.set_selectable(True)
        self.set_focusable(True)

        self.add_css_class("clipboard-card")
        if item.is_pinned:
            self.add_css_class("pinned-row")

        # Main vertical card layout with consistent internal padding and spacing
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main_box.set_margin_start(14)
        main_box.set_margin_end(14)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        self.set_child(main_box)

        # 1. Header bar: Pin indicator + Content Type + Actions revealer
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Visual pinned indicator with icon + label + accent styling
        self.pin_indicator = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.pin_icon = Gtk.Image.new_from_icon_name("view-pin-symbolic")
        self.pin_icon.add_css_class("accent")
        self.pin_label = Gtk.Label(label="Pinned")
        self.pin_label.add_css_class("caption")
        self.pin_label.add_css_class("accent")
        self.pin_indicator.append(self.pin_icon)
        self.pin_indicator.append(self.pin_label)
        self.pin_indicator.set_tooltip_text("Pinned item")
        self.pin_indicator.set_visible(item.is_pinned)
        self.pin_icon.set_visible(item.is_pinned)
        header_box.append(self.pin_indicator)

        # Content type badge (small, secondary label)
        self.type_label = Gtk.Label(label=item.content_type.upper())
        self.type_label.set_xalign(0.0)
        self.type_label.add_css_class("caption")
        self.type_label.add_css_class("dim-label")
        header_box.append(self.type_label)

        # Expander spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header_box.append(spacer)

        # Actions revealer (revealed on hover or focus to keep default state clean)
        self.actions_revealer = Gtk.Revealer()
        self.actions_revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.actions_revealer.set_transition_duration(150)
        self.actions_revealer.set_reveal_child(False)

        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        # Quick Copy action button
        self.copy_btn = Gtk.Button()
        self.copy_btn.set_icon_name("edit-copy-symbolic")
        self.copy_btn.add_css_class("flat")
        self.copy_btn.add_css_class("action-btn")
        self.copy_btn.set_valign(Gtk.Align.CENTER)
        self.copy_btn.set_tooltip_text("Copy")
        self.copy_btn.connect("clicked", self._on_quick_copy_clicked)
        actions_box.append(self.copy_btn)

        # Quick Pin / Unpin action button
        self.quick_pin_btn = Gtk.Button()
        self.quick_pin_btn.set_icon_name("view-pin-symbolic")
        self.quick_pin_btn.add_css_class("flat")
        self.quick_pin_btn.add_css_class("action-btn")
        self.quick_pin_btn.set_valign(Gtk.Align.CENTER)
        if item.is_pinned:
            self.quick_pin_btn.add_css_class("accent")
            self.quick_pin_btn.set_tooltip_text("Unpin")
        else:
            self.quick_pin_btn.set_tooltip_text("Pin")
        self.quick_pin_btn.connect("clicked", self._on_quick_pin_clicked)
        actions_box.append(self.quick_pin_btn)

        # Row action menu button
        self.menu_btn = Gtk.MenuButton()
        self.menu_btn.set_icon_name("view-more-symbolic")
        self.menu_btn.add_css_class("flat")
        self.menu_btn.add_css_class("action-btn")
        self.menu_btn.set_valign(Gtk.Align.CENTER)
        self.menu_btn.set_tooltip_text("Options")

        popover = Gtk.Popover()
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pop_box.set_margin_top(6)
        pop_box.set_margin_bottom(6)
        pop_box.set_margin_start(6)
        pop_box.set_margin_end(6)

        # Popover - Copy item action
        pop_copy_btn = Gtk.Button()
        pop_copy_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pop_copy_box.append(Gtk.Image.new_from_icon_name("edit-copy-symbolic"))
        pop_copy_box.append(Gtk.Label(label="Copy"))
        pop_copy_btn.set_child(pop_copy_box)
        pop_copy_btn.add_css_class("flat")
        pop_copy_btn.connect("clicked", self._on_popover_copy_clicked, popover)
        pop_box.append(pop_copy_btn)

        # Popover - Pin / Unpin button
        pop_pin_btn = Gtk.Button()
        pop_pin_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pop_pin_icon = Gtk.Image.new_from_icon_name("view-pin-symbolic")
        self.menu_pin_label = Gtk.Label(label="Unpin" if item.is_pinned else "Pin")
        pop_pin_box.append(pop_pin_icon)
        pop_pin_box.append(self.menu_pin_label)
        pop_pin_btn.set_child(pop_pin_box)
        pop_pin_btn.add_css_class("flat")
        pop_pin_btn.connect("clicked", self._on_popover_pin_clicked, popover)
        pop_box.append(pop_pin_btn)

        # Popover - Delete button
        del_btn = Gtk.Button()
        del_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        del_btn_icon = Gtk.Image.new_from_icon_name("user-trash-symbolic")
        del_btn_label = Gtk.Label(label="Delete")
        del_btn_box.append(del_btn_icon)
        del_btn_box.append(del_btn_label)
        del_btn.set_child(del_btn_box)
        del_btn.add_css_class("flat")
        del_btn.add_css_class("destructive-action")
        del_btn.connect("clicked", self._on_popover_delete_clicked, popover)
        pop_box.append(del_btn)

        popover.set_child(pop_box)
        popover.connect("closed", self._on_popover_closed)
        self.popover = popover
        self.menu_btn.set_popover(popover)
        actions_box.append(self.menu_btn)

        self.actions_revealer.set_child(actions_box)
        header_box.append(self.actions_revealer)

        main_box.append(header_box)

        # 2. Content presentation (Image thumbnail in neutral frame or 3-line text preview)
        self.texture: Optional[Gdk.Texture] = None
        self.picture: Optional[Gtk.Picture] = None

        if item.content_type == "image":
            image_frame = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            image_frame.set_halign(Gtk.Align.CENTER)
            image_frame.set_valign(Gtk.Align.CENTER)
            image_frame.set_margin_top(4)
            image_frame.set_margin_bottom(4)
            image_frame.add_css_class("image-preview-box")

            self.texture = get_thumbnail_texture(item.image_path)
            if self.texture:
                self.picture = Gtk.Picture()
                self.picture.set_paintable(self.texture)
                self.picture.set_can_shrink(False)
                self.picture.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
                self.picture.set_size_request(self.texture.get_width(), self.texture.get_height())
                image_frame.append(self.picture)
            else:
                fallback_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                fallback_box.set_halign(Gtk.Align.CENTER)
                fallback_box.set_margin_start(16)
                fallback_box.set_margin_end(16)
                fallback_box.set_margin_top(12)
                fallback_box.set_margin_bottom(12)
                fallback_icon = Gtk.Image.new_from_icon_name("image-missing-symbolic")
                fallback_label = Gtk.Label(label="Image unavailable")
                fallback_label.add_css_class("dim-label")
                fallback_box.append(fallback_icon)
                fallback_box.append(fallback_label)
                image_frame.append(fallback_box)

            main_box.append(image_frame)
        else:
            self.preview_label = Gtk.Label()
            preview_text = create_visual_preview(item.content, max_lines=3)
            self.preview_label.set_text(preview_text)
            self.preview_label.set_xalign(0.0)
            self.preview_label.set_wrap(True)
            self.preview_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.preview_label.set_ellipsize(Pango.EllipsizeMode.END)
            self.preview_label.set_lines(3)
            self.preview_label.add_css_class("body")
            self.preview_label.set_margin_top(2)
            self.preview_label.set_margin_bottom(2)
            main_box.append(self.preview_label)

        # 3. Status stack (switches between timestamp and "✓ Copied" feedback)
        self.status_stack = Gtk.Stack()
        self.status_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.status_stack.set_transition_duration(150)
        main_box.append(self.status_stack)

        # View A: Timestamp
        meta_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.time_label = Gtk.Label(label=format_timestamp(item.created_at))
        self.time_label.set_xalign(0.0)
        self.time_label.add_css_class("caption")
        self.time_label.add_css_class("dim-label")
        meta_box.append(self.time_label)
        self.status_stack.add_named(meta_box, "metadata")

        # View B: "Copied" visual feedback (single checkmark icon + label)
        copied_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        copied_icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
        copied_icon.add_css_class("accent")
        copied_label = Gtk.Label(label="Copied")
        copied_label.set_xalign(0.0)
        copied_label.add_css_class("caption")
        copied_label.add_css_class("accent")
        copied_box.append(copied_icon)
        copied_box.append(copied_label)
        self.status_stack.add_named(copied_box, "copied")

        self.status_stack.set_visible_child_name("metadata")

        # 4. Controllers for Hover, Focus, Key Shortcuts, and Context Menu
        motion_ctrl = Gtk.EventControllerMotion()
        motion_ctrl.connect("enter", self._on_motion_enter)
        motion_ctrl.connect("leave", self._on_motion_leave)
        self.add_controller(motion_ctrl)

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("enter", self._on_focus_enter)
        focus_ctrl.connect("leave", self._on_focus_leave)
        self.add_controller(focus_ctrl)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_row_key_pressed)
        self.add_controller(key_ctrl)

        right_click_ctrl = Gtk.GestureClick()
        right_click_ctrl.set_button(3)
        right_click_ctrl.connect("pressed", self._on_right_click)
        self.add_controller(right_click_ctrl)

    def _on_motion_enter(self, controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        self._is_hovered = True
        self._update_actions_visibility()

    def _on_motion_leave(self, controller: Gtk.EventControllerMotion) -> None:
        self._is_hovered = False
        self._update_actions_visibility()

    def _on_focus_enter(self, controller: Gtk.EventControllerFocus) -> None:
        self._is_focused = True
        self._update_actions_visibility()

    def _on_focus_leave(self, controller: Gtk.EventControllerFocus) -> None:
        self._is_focused = False
        self._update_actions_visibility()

    def _on_popover_closed(self, popover: Gtk.Popover) -> None:
        self._popover_open = False
        self._update_actions_visibility()

    def _update_actions_visibility(self) -> None:
        """Reveals action buttons when hovered, focused, or popover is open."""
        show = self._is_hovered or self._is_focused or self._popover_open
        self.actions_revealer.set_reveal_child(show)

    def popup_menu(self) -> None:
        """Opens the action menu popover."""
        self._popover_open = True
        self._update_actions_visibility()
        if self.get_root():
            self.menu_btn.popup()

    def _on_right_click(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        """Opens the action popover when right-clicking the row."""
        self.popup_menu()

    def _on_row_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Keyboard shortcuts on row: Menu/F10/Shift+F10/Ctrl+M opens menu, Delete key deletes."""
        is_menu_key = keyval in (Gdk.KEY_Menu, Gdk.KEY_F10)
        is_ctrl_m = keyval in (Gdk.KEY_m, Gdk.KEY_M) and bool(state & Gdk.ModifierType.CONTROL_MASK)
        if is_menu_key or is_ctrl_m:
            self.popup_menu()
            return True
        elif keyval == Gdk.KEY_Delete:
            if self.on_delete:
                self._handle_delete()
                return True
        return False

    def _on_quick_copy_clicked(self, button: Gtk.Button) -> None:
        self._handle_copy()

    def _on_popover_copy_clicked(self, button: Gtk.Button, popover: Gtk.Popover) -> None:
        popover.popdown()
        self._handle_copy()

    def _handle_copy(self) -> None:
        if self.on_copy:
            self.on_copy(self.item)
        self.show_copied_feedback()

    def _on_quick_pin_clicked(self, button: Gtk.Button) -> None:
        if self.on_toggle_pin:
            self.on_toggle_pin(self.item)

    def _on_popover_pin_clicked(self, button: Gtk.Button, popover: Gtk.Popover) -> None:
        popover.popdown()
        if self.on_toggle_pin:
            self.on_toggle_pin(self.item)

    def _on_popover_delete_clicked(self, button: Gtk.Button, popover: Gtk.Popover) -> None:
        popover.popdown()
        self._handle_delete()

    def _handle_delete(self) -> None:
        if self.item.image_path:
            clear_thumbnail_cache(self.item.image_path)
        if self.on_delete:
            self.on_delete(self.item)

    def set_pinned(self, is_pinned: bool) -> None:
        """Updates row presentation when pinned state changes."""
        self.item.is_pinned = is_pinned
        self.pin_indicator.set_visible(is_pinned)
        self.pin_icon.set_visible(is_pinned)
        if is_pinned:
            self.add_css_class("pinned-row")
            self.quick_pin_btn.add_css_class("accent")
            self.quick_pin_btn.set_tooltip_text("Unpin")
            self.menu_pin_label.set_text("Unpin")
        else:
            self.remove_css_class("pinned-row")
            self.quick_pin_btn.remove_css_class("accent")
            self.quick_pin_btn.set_tooltip_text("Pin")
            self.menu_pin_label.set_text("Pin")

    def show_copied_feedback(self) -> None:
        """Displays temporary '✓ Copied' visual feedback for 1.5 seconds."""
        if self._feedback_timer_id:
            GLib.source_remove(self._feedback_timer_id)
            self._feedback_timer_id = None

        self.status_stack.set_visible_child_name("copied")
        self._feedback_timer_id = GLib.timeout_add(1500, self._restore_metadata)

    def _restore_metadata(self) -> bool:
        """Restores normal metadata display."""
        self._feedback_timer_id = None
        self.status_stack.set_visible_child_name("metadata")
        return False

    def do_unroot(self) -> None:
        """Cleans up active timers when row is removed from the widget tree."""
        if self._feedback_timer_id:
            GLib.source_remove(self._feedback_timer_id)
            self._feedback_timer_id = None
        Gtk.ListBoxRow.do_unroot(self)

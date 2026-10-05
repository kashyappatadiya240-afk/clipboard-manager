"""D-Bus Picker Service for GNOME Shell Extension integration."""

import logging
from typing import List, Optional, Tuple

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from clipboard.database import ClipboardDatabase
from clipboard.monitor import ClipboardMonitor

logger = logging.getLogger(__name__)

PICKER_INTERFACE_XML = """
<node>
  <interface name="com.kashyap.Klipora.Picker">
    <method name="GetHistory">
      <arg type="s" name="query" direction="in"/>
      <arg type="u" name="limit" direction="in"/>
      <arg type="a(ss)" name="items" direction="out"/>
    </method>
    <method name="CopyItem">
      <arg type="s" name="item_id" direction="in"/>
      <arg type="b" name="success" direction="out"/>
    </method>
  </interface>
</node>
"""


class PickerDBusService:
    """Exports D-Bus interface com.kashyap.Klipora.Picker for GNOME Shell Extension."""

    BUS_NAME = "com.kashyap.Klipora.Picker"
    OBJECT_PATH = "/com/kashyap/Klipora"
    INTERFACE_NAME = "com.kashyap.Klipora.Picker"

    def __init__(self, database: ClipboardDatabase, monitor: Optional[ClipboardMonitor] = None):
        self.database = database
        self.monitor = monitor
        self._node_info = Gio.DBusNodeInfo.new_for_xml(PICKER_INTERFACE_XML)
        self._reg_id: int = 0
        self._name_owner_id: int = 0
        self._connection: Optional[Gio.DBusConnection] = None

    def start(self, connection: Optional[Gio.DBusConnection] = None) -> None:
        """Starts the D-Bus service, exporting object on session bus."""
        if connection:
            self._connection = connection
            self._register_on_connection(connection)
        else:
            self._name_owner_id = Gio.bus_own_name(
                Gio.BusType.SESSION,
                self.BUS_NAME,
                Gio.BusNameOwnerFlags.NONE,
                self._on_bus_acquired,
                None,
                None,
            )

    def _on_bus_acquired(self, connection: Gio.DBusConnection, name: str) -> None:
        self._connection = connection
        self._register_on_connection(connection)

    def _register_on_connection(self, connection: Gio.DBusConnection) -> None:
        if self._reg_id != 0:
            return
        try:
            self._reg_id = connection.register_object(
                self.OBJECT_PATH,
                self._node_info.interfaces[0],
                self._handle_method_call,
                None,
                None,
            )
            logger.info("Exported %s on %s", self.INTERFACE_NAME, self.OBJECT_PATH)
        except Exception as e:
            logger.error("Failed to register D-Bus picker object: %s", e)

    def _handle_method_call(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        try:
            if method_name == "GetHistory":
                query, limit = parameters.unpack()
                items = self.get_history(query, limit)
                invocation.return_value(GLib.Variant("(a(ss))", [items]))
            elif method_name == "CopyItem":
                (item_id,) = parameters.unpack()
                success = self.copy_item(item_id)
                invocation.return_value(GLib.Variant("(b)", (success,)))
            else:
                invocation.return_error_literal(
                    Gio.DBusError,
                    Gio.DBusError.UNKNOWN_METHOD,
                    f"Unknown method {method_name}",
                )
        except Exception as e:
            logger.exception("Error handling method %s", method_name)
            invocation.return_error_literal(
                Gio.DBusError,
                Gio.DBusError.FAILED,
                str(e),
            )

    def get_history(self, query: str, limit: int) -> List[Tuple[str, str]]:
        """Retrieves recent text clipboard history matching the given query."""
        if limit <= 0:
            limit = 20
        max_fetch = max(limit * 2, 50)
        items = self.database.get_items(limit=max_fetch)
        cleaned_query = query.strip().casefold() if query else ""

        results: List[Tuple[str, str]] = []
        for item in items:
            if item.content_type != "text" or not item.content:
                continue
            if cleaned_query and cleaned_query not in item.content.casefold():
                continue
            results.append((str(item.id), item.content))
            if len(results) >= limit:
                break
        return results

    def copy_item(self, item_id: str) -> bool:
        """Copies item to system clipboard using existing backend copy implementation."""
        try:
            target_id = int(item_id)
        except (ValueError, TypeError):
            logger.warning("Invalid item_id for copy: %r", item_id)
            return False

        items = self.database.get_items(limit=100)
        item = next((it for it in items if it.id == target_id), None)
        if not item:
            logger.warning("Item %d not found for copying", target_id)
            return False

        if self.monitor:
            if item.content_type == "image":
                if item.image_path:
                    self.monitor.copy_image(item.image_path)
                    return True
                return False
            else:
                self.monitor.copy_text(item.content or "")
                return True
        return False

    def stop(self) -> None:
        """Unregisters object and releases bus name."""
        if self._reg_id and self._connection:
            try:
                self._connection.unregister_object(self._reg_id)
            except Exception:
                pass
            self._reg_id = 0
        if self._name_owner_id:
            Gio.bus_unown_name(self._name_owner_id)
            self._name_owner_id = 0

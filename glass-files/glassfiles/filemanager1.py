"""org.freedesktop.FileManager1 so browsers and apps can 'Show in folder'."""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib

from . import util

BUS_NAME = "org.freedesktop.FileManager1"
OBJECT_PATH = "/org/freedesktop/FileManager1"

XML = """
<node>
  <interface name="org.freedesktop.FileManager1">
    <method name="ShowFolders">
      <arg type="as" name="URIs" direction="in"/>
      <arg type="s" name="StartupId" direction="in"/>
    </method>
    <method name="ShowItems">
      <arg type="as" name="URIs" direction="in"/>
      <arg type="s" name="StartupId" direction="in"/>
    </method>
    <method name="ShowItemProperties">
      <arg type="as" name="URIs" direction="in"/>
      <arg type="s" name="StartupId" direction="in"/>
    </method>
    <property name="version" type="s" access="read"/>
  </interface>
</node>
"""


class FileManager1:
    def __init__(self, app):
        self.app = app
        self.connection = None
        self.registration_id = 0
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            self._on_name_acquired,
            self._on_name_lost,
        )

    def _on_bus_acquired(self, connection, name):
        self.connection = connection
        try:
            self.registration_id = connection.register_object(
                OBJECT_PATH, self._interface_info(), self._on_call,
                self._on_get_property, None
            )
        except GLib.Error as e:
            self.registration_id = 0
            print(f"glass-files: FileManager1 registration failed: {e.message}")

    def _on_name_acquired(self, connection, name):
        pass

    def _on_name_lost(self, connection, name):
        # Another file manager owns it; we stay out of the way quietly.
        self.connection = None

    def _interface_info(self):
        return Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]

    def _on_get_property(self, connection, sender, path, interface, prop):
        if prop == "version":
            return GLib.Variant("s", "1.0")
        return None

    def _on_call(self, connection, sender, path, interface, method, params, invocation):
        try:
            uris = list(params.get_child_value(0).unpack()) if params is not None else []
            if method in ("ShowFolders", "ShowItems"):
                show_items = method == "ShowItems"
                GLib.idle_add(self.app.present_uris, uris, show_items)
            elif method == "ShowItemProperties":
                GLib.idle_add(self.app.show_properties_uris, uris)
        finally:
            invocation.return_value(GLib.Variant("()", ()))

    def stop(self):
        if self.connection is not None and self.registration_id:
            try:
                self.connection.unregister_object(self.registration_id)
            except Exception:
                pass
        self.registration_id = 0
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0

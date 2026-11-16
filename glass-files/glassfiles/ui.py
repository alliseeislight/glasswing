"""Tiny GTK widget helpers so the real modules stay readable."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gio, Gtk


def label(text="", css=None, xalign=0.0, ellipsize=None, width_chars=-1, wrap=False,
          selectable=False):
    lab = Gtk.Label(label=text)
    lab.set_xalign(xalign)
    if css:
        for c in css.split():
            lab.add_css_class(c)
    if ellipsize:
        lab.set_ellipsize(ellipsize)
    if width_chars > 0:
        lab.set_width_chars(width_chars)
    if wrap:
        lab.set_wrap(True)
        lab.set_wrap_mode(2)
    lab.set_selectable(selectable)
    return lab


def image_icon(name: str, size: int = 16):
    img = Gtk.Image.new_from_icon_name(name)
    img.set_pixel_size(size)
    return img


def button(*, icon=None, text=None, tooltip=None, css=None, flat=True, size=None):
    if icon is not None and text is None:
        btn = Gtk.Button.new_from_icon_name(icon)
        btn.set_child(Gtk.Image.new_from_icon_name(icon))
        if size:
            btn.get_child().set_pixel_size(size)
    elif icon is not None and text is not None:
        btn = Gtk.Button()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        img = Gtk.Image.new_from_icon_name(icon)
        if size:
            img.set_pixel_size(size)
        box.append(img)
        box.append(Gtk.Label(label=text))
        btn.set_child(box)
    else:
        btn = Gtk.Button(label=text or "")
    if tooltip:
        btn.set_tooltip_text(tooltip)
    if flat:
        btn.add_css_class("flat")
    for c in (css or "").split():
        btn.add_css_class(c)
    return btn


def sep(vertical=False):
    s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL)
    return s


def spacer(hexpand=True):
    b = Gtk.Box()
    b.set_hexpand(hexpand)
    return b


def show_menu(model: Gio.MenuModel, parent: Gtk.Widget, x=None, y=None):
    pop = Gtk.PopoverMenu.new_from_model(model)
    pop.set_has_arrow(False)
    pop.set_parent(parent)
    if x is not None and y is not None:
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
    pop.popup()
    return pop


def item_menu(entries):
    """entries: list of (label, action) or None for a separator."""
    menu = Gio.Menu()
    section = Gio.Menu()
    for entry in entries:
        if entry is None:
            menu.append_section(None, section)
            section = Gio.Menu()
            continue
        text, action = entry
        section.append(text, action)
    menu.append_section(None, section)
    return menu


def menu_with_submenus(entries):
    """entries: (label, action|Gio.MenuModel|None)."""
    menu = Gio.Menu()
    for text, value in entries:
        if value is None:
            continue
        if isinstance(value, Gio.MenuModel):
            menu.append_submenu(text, value)
        else:
            menu.append(text, value)
    return menu

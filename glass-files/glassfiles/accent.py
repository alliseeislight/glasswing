"""Wallpaper accent, reusing the shell's accent.py when it is available."""

from __future__ import annotations

import importlib.util
import json
import os
import re

from . import util

POPOUT_ACCENT = os.path.expanduser(
    "~/.config/hypr/scripts/popouts/accent.py"
)
SETTINGS = os.path.expanduser("~/.config/glass/settings.json")
DEFAULT = (168, 184, 230)


def _load_popouts():
    if not os.path.isfile(POPOUT_ACCENT):
        return None
    try:
        spec = importlib.util.spec_from_file_location("glass_shell_accent", POPOUT_ACCENT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _fallback(path=None):
    import colorsys

    cols = {}
    path = path or os.path.expanduser("~/.config/kitty/colors.conf")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^\s*(color\d+)\s+#([0-9a-fA-F]{6})", line)
                if m:
                    cols[m.group(1)] = m.group(2)
    except OSError:
        pass
    best = None
    for i in (1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14):
        h = cols.get(f"color{i}")
        if not h:
            continue
        r, g, b = (int(h[j:j + 2], 16) / 255 for j in (0, 2, 4))
        hue, light, sat = colorsys.rgb_to_hls(r, g, b)
        score = sat * (1 - abs(light - 0.5))
        if best is None or score > best[0]:
            best = (score, hue, sat)
    if best is None:
        return DEFAULT
    _, hue, sat = best
    sat = min(sat, 0.55)
    if sat > 0.20:
        sat = max(sat, 0.35)
    r, g, b = colorsys.hls_to_rgb(hue, 0.70, sat)
    return tuple(round(v * 255) for v in (r, g, b))


def compute() -> tuple[int, int, int]:
    mod = _load_popouts()
    if mod is not None and hasattr(mod, "compute"):
        try:
            rgb = mod.compute()
            if rgb and len(rgb) == 3:
                return tuple(max(0, min(255, int(v))) for v in rgb)
        except Exception:
            pass
    return _fallback()


def hex_of(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def defines(rgb) -> str:
    r, g, b = rgb
    return (
        f"@define-color glass_accent rgb({r},{g},{b});\n"
        f"@define-color glass_accent_soft rgba({r},{g},{b},0.28);\n"
        f"@define-color glass_accent_mid rgba({r},{g},{b},0.55);\n"
        f"@define-color glass_accent_line rgba({r},{g},{b},0.42);\n"
    )


def read_override():
    """Manual accent lives in the shell's settings.json, which owns that key."""
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    if st.get("accent_mode") == "manual":
        h = str(st.get("accent", "")).lstrip("#")
        if re.fullmatch(r"[0-9a-fA-F]{6}", h):
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return None


def desktop_is_light() -> bool:
    """True when the generated palette is a light one (cream paper, dark ink)."""
    path = os.path.expanduser("~/.config/kitty/colors.conf")
    bg = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^\s*background\s+#([0-9a-fA-F]{6})", line)
                if m:
                    bg = m.group(1)
                    break
    except OSError:
        pass
    if not bg:
        return False
    try:
        r, g, b = (int(bg[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 140

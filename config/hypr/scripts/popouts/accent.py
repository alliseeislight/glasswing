import colorsys
import json
import os
import re

KITTY = os.path.expanduser("~/.config/kitty/colors.conf")
DEFAULT = (168, 184, 230)


def _parse(path):
    cols = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r"^\s*(color\d+)\s+#([0-9a-fA-F]{6})", line)
                if m:
                    cols[m.group(1)] = m.group(2)
    except OSError:
        pass
    return cols


def _manual():
    try:
        with open(os.path.expanduser("~/.config/glass/settings.json")) as f:
            st = json.load(f)
        if st.get("accent_mode") == "manual":
            h = str(st.get("accent", "")).lstrip("#")
            if re.fullmatch(r"[0-9a-fA-F]{6}", h):
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return None


def compute(path=KITTY):
    """Pick the most colourful palette entry, then soften it so it never shouts."""
    manual = _manual()
    if manual:
        return manual
    cols = _parse(path)
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


def defines(rgb):
    r, g, b = rgb
    return (
        f"@define-color glass_accent rgb({r},{g},{b});\n"
        f"@define-color glass_accent_soft rgba({r},{g},{b},0.28);\n"
        f"@define-color glass_accent_mid rgba({r},{g},{b},0.55);\n"
    )


def rasi(rgb):
    r, g, b = rgb
    hx = f"{r:02x}{g:02x}{b:02x}"
    return f"* {{\n    accent: #{hx};\n    accent-soft: #{hx}47;\n    accent-mid: #{hx}8c;\n}}\n"


def hypr_vars(rgb):
    r, g, b = rgb
    return f"$accent = rgb({r},{g},{b})\n$accent_soft = rgba({r},{g},{b},0.45)\n"


def write(rgb):
    home = os.path.expanduser("~/.config")
    os.makedirs(os.path.join(home, "glass"), exist_ok=True)
    jobs = [
        (os.path.join(home, "waybar", "accent.css"), defines(rgb)),
        (os.path.join(home, "swaync", "accent.css"), defines(rgb)),
        (os.path.join(home, "wlogout", "accent.css"), defines(rgb)),
        (os.path.join(home, "rofi", "accent.rasi"), rasi(rgb)),
        (os.path.join(home, "glass", "accent.conf"), hypr_vars(rgb)),
    ]
    for path, text in jobs:
        try:
            if os.path.isdir(os.path.dirname(path)):
                with open(path, "w") as f:
                    f.write(text)
        except OSError:
            pass

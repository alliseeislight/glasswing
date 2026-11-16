"""Config for the dock and desktop widgets (no GTK here, so it can be tested on its own)."""
import json
import os

CFG = os.path.expanduser("~/.config/glass/shell.json")

DEFAULTS = {
    "dock": {
        "enabled": True,
        "pinned": [],          # desktop ids, e.g. "kitty.desktop"; filled on first run
        "icon_size": 44,
        "exclusive": True,     # push tiled windows up so the dock never covers them
    },
    "widgets": {
        "enabled": True,
        "units": "metric",     # or "imperial"
        "photo_dir": "~/Pictures/widgets",
        "margin_top": 56,
        "margin_left": 20,
    },
    "bar": {
        "enabled": True,
    },
}

CANDIDATES = [
    "zen.desktop", "zen-browser.desktop", "firefox.desktop", "org.mozilla.firefox.desktop",
    "kitty.desktop", "org.gnome.Nautilus.desktop", "nautilus.desktop", "thunar.desktop",
    "spotify.desktop", "spotify-launcher.desktop", "code.desktop", "visual-studio-code.desktop",
    "discord.desktop", "vesktop.desktop", "obsidian.desktop", "steam.desktop",
]


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(CFG) as f:
            user = json.load(f)
        for sect, vals in user.items():
            if sect in cfg and isinstance(vals, dict):
                cfg[sect].update(vals)
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    tmp = CFG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, CFG)


def default_pinned(existing_ids, limit=8):
    have = set(existing_ids)
    out = []
    for c in CANDIDATES:
        if c in have and c not in out:
            out.append(c)
        if len(out) >= limit:
            break
    return out

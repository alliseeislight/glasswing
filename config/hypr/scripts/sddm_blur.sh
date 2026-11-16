#!/bin/bash
# Optional SDDM touch: only run when the theme file is writable by this user.
# Set GLASSWING_SDDM_WALLPAPER to use a different theme path.
OUT="${GLASSWING_SDDM_WALLPAPER:-/usr/share/sddm/themes/WhiteSur/blurred_wallpaper.jpg}"
[ -w "$OUT" ] || exit 0
command -v magick >/dev/null 2>&1 || exit 0
magick "$1" -scale 960x600^ -gravity center -extent 960x600 -blur 0x8 -scale 1920x1200 "$OUT"

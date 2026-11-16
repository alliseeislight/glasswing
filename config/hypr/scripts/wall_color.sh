#!/bin/bash
IMG="$1"
SCRIPTS_DIR="$(dirname "$(readlink -f "$0")")"

if [[ -z "$IMG" || ! -f "$IMG" ]]; then
    echo "usage: $0 /path/to/wallpaper" >&2
    exit 1
fi

# Videos: use one frame for the palette and the SDDM blur.
SRC="$IMG"
case "${IMG,,}" in
    *.mp4|*.webm|*.mkv|*.gif)
        SRC="/tmp/glass-wall-frame.png"
        ffmpeg -y -ss 1 -i "$IMG" -frames:v 1 "$SRC" >/dev/null 2>&1
        if [[ ! -f "$SRC" ]]; then
            echo "wall_color: could not extract a frame from $IMG" >&2
            exit 1
        fi
        ;;
esac

sed -i 's/palette = ".*/palette = "light"/' ~/.config/wallust/wallust.toml

wallust run -s "$SRC"

sleep 0.05

hyprctl reload
killall -SIGUSR2 waybar
swaync-client -rs

nice -n 19 "$SCRIPTS_DIR/sddm_blur.sh" "$SRC" &

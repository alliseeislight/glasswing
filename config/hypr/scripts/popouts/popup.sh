#!/usr/bin/env bash
# usage: popup.sh daemon
#        popup.sh wifi|bluetooth|battery|calendar|volume|clipboard|settings|media|notes|notes|notes   (toggle a popup)
#        popup.sh osd volume up|down|mute      popup.sh osd brightness up|down
dir="$(dirname "$(readlink -f "$0")")"
APP=local.glass.daemon

start_daemon() {
  pgrep -f "glassd.py" >/dev/null && return 0
  LIB=$(ls /usr/lib/libgtk4-layer-shell.so* 2>/dev/null | head -1)
  env LD_PRELOAD="$LIB" setsid -f /usr/bin/python3 "$dir/glassd.py" >/tmp/glassd.log 2>&1 </dev/null
}

if [ "$1" = daemon ]; then start_daemon; exit 0; fi

if [ "$1" = osd ]; then
  action=osd; arg="$2 $3"
else
  x=$(hyprctl cursorpos 2>/dev/null | cut -d, -f1 | tr -d ' ')
  case "$x" in ''|*[!0-9-]*) x=1500 ;; esac
  action=toggle; arg="$1 $x"
fi

send() { gapplication action "$APP" "$action" "'$arg'" >/dev/null 2>&1; }

send && exit 0
start_daemon
for i in $(seq 1 24); do sleep 0.25; send && exit 0; done
exit 1

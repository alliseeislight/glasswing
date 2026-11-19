local M = "SUPER"
local home = os.getenv("HOME")
local popup = home .. "/.config/hypr/scripts/popouts/popup.sh"

hl.bind(M .. " + RETURN", hl.dsp.window.float({ action = "toggle" }))
hl.bind(M .. " + B", hl.dsp.exec_cmd("xdg-open https://github.com/alliseeislight/glasswing"))
hl.bind(M .. " + E", hl.dsp.exec_cmd(home .. "/.local/bin/glass-files-open"))
hl.bind(M .. " + W", hl.dsp.exec_cmd(home .. "/.config/hypr/scripts/cycle_wall.sh"))

hl.bind(M .. " + Q", hl.dsp.window.close(), { repeating = true })
hl.bind(M .. " + SHIFT + Q", hl.dsp.exec_cmd("hyprctl activewindow | grep pid | tr -d 'pid:' | xargs kill"))
hl.bind(M .. " + CTRL + R", hl.dsp.exec_cmd("hyprctl reload"))

hl.bind(M .. " + F", hl.dsp.window.fullscreen({ mode = 0 }))
hl.bind(M .. " + SHIFT + F", hl.dsp.window.fullscreen({ mode = 1 }))
hl.bind(M .. " + T", hl.dsp.exec_cmd("kitty"))
hl.bind(M .. " + P", hl.dsp.window.pin())

hl.bind(M .. " + left", hl.dsp.focus({ direction = "left" }), { repeating = true })
hl.bind(M .. " + right", hl.dsp.focus({ direction = "right" }), { repeating = true })
hl.bind(M .. " + up", hl.dsp.focus({ direction = "up" }), { repeating = true })
hl.bind(M .. " + down", hl.dsp.focus({ direction = "down" }), { repeating = true })

hl.bind(M .. " + SHIFT + right", hl.dsp.layout("colresize +0.05"), { repeating = true })
hl.bind(M .. " + SHIFT + left", hl.dsp.layout("colresize -0.05"), { repeating = true })

hl.bind(M .. " + ALT + left", hl.dsp.layout("swapcol l"), { repeating = true })
hl.bind(M .. " + ALT + right", hl.dsp.layout("swapcol r"), { repeating = true })

hl.bind(M .. " + CTRL + left", hl.dsp.layout("move -col"), { repeating = true })
hl.bind(M .. " + CTRL + right", hl.dsp.layout("move +col"), { repeating = true })

hl.bind(M .. " + CTRL + C", hl.dsp.layout("center"))
hl.bind(M .. " + CTRL + F", hl.dsp.layout("fit active"))
hl.bind(M .. " + CTRL + A", hl.dsp.layout("fit all"))
hl.bind(M .. " + CTRL + V", hl.dsp.layout("fit visible"))
hl.bind(M .. " + CTRL + E", hl.dsp.layout("fit expand"))

hl.bind(M .. " + bracketleft", hl.dsp.layout("colresize -conf"), { repeating = true })
hl.bind(M .. " + bracketright", hl.dsp.layout("colresize +conf"), { repeating = true })

hl.bind(M .. " + J", hl.dsp.layout("swapcol l"))
hl.bind(M .. " + K", hl.dsp.layout("consume_or_expel prev"))

hl.bind(M .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(M .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

hl.bind(M .. " + D", hl.dsp.exec_cmd("rofi -show drun -theme " .. home .. "/.config/rofi/glass.rasi"))
hl.bind(M .. " + N", hl.dsp.exec_cmd("swaync-client -t -sw"))
hl.bind(M .. " + Print", hl.dsp.exec_cmd('grim -g "$(slurp)" - | satty --filename -'))

hl.bind("XF86PowerOff", hl.dsp.exec_cmd("wlogout -b 3 -T 300 -B 300"))
hl.bind("XF86ScreenSaver", hl.dsp.exec_cmd("glass-lock"))

hl.bind("code:238", hl.dsp.exec_cmd("brightnessctl -d smc::kbd_backlight s +10"))
hl.bind("code:237", hl.dsp.exec_cmd("brightnessctl -d smc::kbd_backlight s 10-"))

for i = 1, 9 do
	hl.bind(M .. " + " .. i, hl.dsp.focus({ workspace = i }))
	hl.bind(M .. " + SHIFT + " .. i, hl.dsp.window.move({ workspace = i, silent = true }))
	hl.bind(M .. " + ALT + " .. i, hl.dsp.window.move({ workspace = i }))
end

hl.bind(M .. " + 0", hl.dsp.focus({ workspace = 10 }))
hl.bind(M .. " + SHIFT + 0", hl.dsp.window.move({ workspace = 10, silent = true }))
hl.bind(M .. " + ALT + 0", hl.dsp.window.move({ workspace = 10 }))

hl.bind(M .. " + S", hl.dsp.workspace.toggle_special("scratch"))
hl.bind(M .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special:scratch" }))

hl.bind("ALT + F7", hl.dsp.exec_cmd([[sh -c "pkill -x wlogout || wlogout -p layer-shell -b 5"]]))

hl.bind("SUPER + V", hl.dsp.exec_cmd(popup .. " clipboard"))
hl.bind("SUPER + SHIFT + N", hl.dsp.exec_cmd(popup .. " notes"))
hl.bind("SUPER + I", hl.dsp.exec_cmd(popup .. " settings"))

-- volume / brightness overlay (glass popup daemon)
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd(popup .. " osd volume up"), { repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd(popup .. " osd volume down"), { repeating = true })
hl.bind("XF86AudioMute", hl.dsp.exec_cmd(popup .. " osd volume mute"))
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd(popup .. " osd brightness up"), { repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd(popup .. " osd brightness down"), { repeating = true })

-- capture: screenshots + screen recording
hl.bind("Print", hl.dsp.exec_cmd(home .. "/.local/bin/shot-full"))
hl.bind("SHIFT + Print", hl.dsp.exec_cmd(home .. "/.local/bin/shot-region"))
hl.bind(M .. " + R", hl.dsp.exec_cmd(home .. "/.local/bin/rec-toggle"))

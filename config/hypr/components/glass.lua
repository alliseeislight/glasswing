hl.config({
	decoration = {
		blur = {
			enabled = true,
			size = 12,
			passes = 3,
			vibrancy = 0.12,
			new_optimizations = true,
			xray = false,
			noise = 0.02,
			contrast = 1.1,
			brightness = 0.98,
			popups = true,
			popups_ignorealpha = 0.1,
		},
	},
})

hl.layer_rule({ match = { namespace = "rofi" }, blur = true, ignore_alpha = 0 })
hl.layer_rule({ match = { namespace = "waybar" }, blur = true, ignore_alpha = 0 })
hl.layer_rule({ match = { namespace = "swaync" }, blur = true, ignore_alpha = 0 })
hl.layer_rule({
	match = { namespace = "swaync-control-center" },
	blur = true,
	ignore_alpha = 0,
	animation = "slide top",
})
hl.layer_rule({ match = { namespace = "wlogout" }, blur = true, ignore_alpha = 0 })
hl.layer_rule({ match = { namespace = "hyprlock" }, animation = "fade" })
hl.layer_rule({ match = { namespace = "zen-browser" }, blur = true, ignore_alpha = 0, animation = "fade" })

hl.layer_rule({ match = { namespace = "rofi" }, blur = true, ignore_alpha = 0, animation = "slide top" })

hl.layer_rule({ match = { namespace = "volume-popout" }, blur = true, ignore_alpha = 0, animation = "slide top" })

hl.layer_rule({ match = { namespace = "volume-popout" }, blur = true, ignore_alpha = 0.2, animation = "slide top" })

hl.layer_rule({ match = { namespace = "glass-popup" }, blur = true, ignore_alpha = 0.2, animation = "slide top" })

hl.layer_rule({ match = { namespace = "waybar" }, blur = true, ignore_alpha = 0.2 })
hl.layer_rule({ match = { namespace = "swaync-control-center" }, blur = true, ignore_alpha = 0.2, animation = "slide right" })
hl.layer_rule({ match = { namespace = "swaync-notification-window" }, blur = true, ignore_alpha = 0.2, animation = "slide right" })

hl.layer_rule({ match = { namespace = "logout_dialog" }, blur = true, ignore_alpha = 0 })

hl.layer_rule({ match = { namespace = "glass-dock" }, blur = true, ignore_alpha = 0.2 })

hl.layer_rule({ match = { namespace = "glass-widget" }, blur = true, ignore_alpha = 0.2 })

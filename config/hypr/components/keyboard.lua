-- Keyboard and touchpad defaults. Set kb_layout to match your keyboard.
hl.config({
	input = {
		kb_layout = "us,latam",
		follow_mouse = 1,
		mouse_refocus = false,
		sensitivity = 0.5,
		accel_profile = "flat",
		touchpad = {
			natural_scroll = false,
			scroll_factor = 0.3,
			tap_to_click = true,
			drag_lock = true,
			disable_while_typing = false,
		},
	},
	binds = {
		workspace_back_and_forth = false,
		allow_workspace_cycles = true,
		pass_mouse_when_bound = false,
	},
})

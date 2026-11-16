-- Glass Files: keep the glass card's 28px corners, and float its dialogs.
-- Rules are matched by WM class (the GTK application id).

hl.window_rule({
    name = "glass-files",
    match = { class = "local.glass.files" },
    float = true,
    center = true,
    rounding = 20,
    border_size = 0,
    opacity = "1.0 override 1.0 override",
})

hl.window_rule({
    name = "glass-files-dialogs",
    match = { class = "local.glass.files", title = "Glass Files .*" },
    float = true,
    center = true,
    rounding = 20,
    border_size = 0,
    animation = "popin 90%",
})

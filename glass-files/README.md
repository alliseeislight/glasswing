# Glass Files

A GTK4 file manager designed for the Glasswing desktop: translucent card,
rounded corners, a live accent from the wallpaper palette, and no libadwaita
chrome.

- **App id / WM class:** `local.glass.files`
- **Installed source:** `~/.local/share/glasswing/glass-files`
- **Launcher:** `~/.local/bin/glass-files`
- **Config:** `~/.config/glass/files.json` (file manager only)

## Install

Glass Files is installed by Glasswing's top-level installer:

```bash
./install.sh
```

The installer copies the app to `~/.local/share/glasswing/glass-files`, writes
the absolute-path launcher, desktop entry, icon, D-Bus services, and the
Hyprland window rule in `~/.config/hypr/components/glass-files.lua`.

## Run

```bash
glass-files
glass-files ~/Pictures
glass-files ~/some/file.pdf     # opens the folder with the file selected
```

It is single-instance: a second launch forwards paths to the running window as
tabs. `org.freedesktop.FileManager1` is implemented, so “Show in folder” from
browsers and `gio open` callers land here when the installer registers it.

The launcher deliberately uses `/usr/bin/python3`; GTK/PyGObject are system
packages, not virtualenv packages.

## Features

- Tabs (drag to reorder, move to a new window), split view, per-folder view and
  sort memory.
- Grid, list, and compact views; icon zoom; sort by name, size, modified, type,
  extension, with folders-first.
- Fast directories: `Gtk.DirectoryList` + filter/sort models + `GridView`/
  `ColumnView`, thumbnail work on a thread pool. Large folders stay usable.
- Search current folder as you type; Enter searches recursively with `fd`.
- Quick Look (`Space`): images, video poster frames, PDF pages, audio tags,
  text/code, archives, folder contents.
- Rename dialog (reliable in every view) and batch find/replace, numbering,
  case; duplicate, compress (`zip`, `7z`, `tar.gz`), extract, checksums.
- Rotate JPEG, PNG, WebP, BMP, and TIFF images left/right in place from the
  context menu or Quick Look. EXIF orientation is normalised, writes are
  atomic, and thumbnails refresh immediately.
- Quick Look slideshow (`P`) and select-by-type shortcuts for images, folders,
  and files.
- Copy/cut/paste with progress, speed, ETA, cancel; conflict dialog with
  replace/skip/keep-both/apply-to-all; atomic moves on the same filesystem.
- Trash by default (freedesktop spec, per-mount `.Trash-$uid`), restore, empty,
  and delete confirmation. Undo/redo for rename, create, copy, move, and trash.
- Properties: permissions, owner, timestamps, size, MIME, checksums, folder
  item counts.
- Bookmarks, devices, connect to server (sftp/smb/nfs/dav), recent, starred.
- Drag and drop out to other apps (file lists + URI lists) and in from other
  apps; drop onto breadcrumbs or a sidebar place.
- Keyboard-first: location entry with completion, context menus, accelerators.
- Remembers window size, per-folder view, sort, hidden toggle, bookmarks.

## Keyboard

| Keys | Action |
| --- | --- |
| `Ctrl+L` | edit location |
| `Ctrl+F` | search this folder |
| `Ctrl+T` / `Ctrl+W` | new / close tab |
| `Ctrl+Shift+T` | reopen closed tab |
| `Ctrl+N` | new window |
| `Ctrl+Shift+N` | new folder |
| `F2` | rename |
| `Space` | Quick Look |
| `R` / `Shift+R` | rotate image right / left in Quick Look |
| `P` | play/pause Quick Look slideshow |
| `Delete` / `Shift+Delete` | trash / delete permanently |
| `Ctrl+Z` / `Ctrl+Shift+Z` | undo / redo |
| `Ctrl+C` / `X` / `V` | copy / cut / paste |
| `Ctrl+1` / `2` / `3` | grid / list / compact |
| `Ctrl+H` | show hidden |
| `Ctrl+D` | bookmark |
| `F3` | split view |
| `F11` | preview pane |
| `Alt+Left/Right/Up` | back / forward / parent |
| `Ctrl+,` | preferences |
| `Ctrl+Q` | quit |

## Tests

The GTK-free core runs with the system Python:

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

## Notes

- No libadwaita. Dialogs are custom glass cards; Hyprland floats them through a
  title-match rule (`Glass Files — …`).
- Trash lives on the same filesystem as the file; cross-device moves copy then
  remove, and only remove after the copy finishes.
- Video/PDF thumbnails use `ffmpegthumbnailer`/`pdftoppm` when present; missing
  helpers degrade to icons, never to an error dialog.

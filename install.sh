#!/usr/bin/env bash
# Glasswing installer — a complete glassy Hyprland shell for Arch Linux.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOME="${HOME:-}"
DRY_RUN=0
NO_DEPS=0
YES=0
NO_RELOAD=0
NO_FILE_MANAGER=0
REAL_HOME="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6 || true)"

say()  { printf '\033[38;5;180m›\033[0m %s\n' "$*"; }
ok()   { printf '\033[38;5;120m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[38;5;214m!\033[0m %s\n' "$*"; }
die()  { printf '\033[38;5;203m✗\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
	cat <<'EOF'
Glasswing installer

Usage: ./install.sh [options]

Options:
  --dry-run             Show what would happen, change nothing
  --no-deps             Do not install missing packages
  --yes                 Do not ask for confirmation
  --no-reload           Do not reload the running Hyprland session
  --no-file-manager     Do not register Glass Files as org.freedesktop.FileManager1
  -h, --help            Show this help

The installer backs up every file it replaces under
~/.local/state/glasswing/backups/<timestamp>/ and writes a manifest there.
EOF
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--dry-run) DRY_RUN=1 ;;
		--no-deps) NO_DEPS=1 ;;
		--yes|-y) YES=1 ;;
		--no-reload) NO_RELOAD=1 ;;
		--no-file-manager) NO_FILE_MANAGER=1 ;;
		-h|--help) usage; exit 0 ;;
		*) die "unknown option: $1 (try --help)" ;;
	esac
	shift
done

[ -n "$HOME" ] || die "HOME is not set"
case "$HOME" in
	/|"") die "refusing to install into HOME=$HOME" ;;
esac
[ "$(id -u)" -ne 0 ] || die "run this as your desktop user, not as root"

if [ "$DRY_RUN" = 0 ]; then
	mkdir -p -- "$HOME"
fi

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/glasswing"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$STATE_DIR/backups/$STAMP"
MANIFEST="$BACKUP_DIR/manifest.tsv"

say "Glasswing → $HOME"
say "repository: $ROOT"

confirm() {
	[ "$YES" = 1 ] && return 0
	[ "$DRY_RUN" = 1 ] && return 0
	[ -t 0 ] || die "no terminal for confirmation; re-run with --yes"
	local ans
	read -r -p "$1 [Y/n] " ans
	case "$ans" in
		""|y|Y|yes|YES) return 0 ;;
		*) return 1 ;;
	esac
}

record() {
	local action="$1" target="$2" backup="${3:-}"
	[ "$DRY_RUN" = 1 ] && return 0
	mkdir -p -- "$BACKUP_DIR"
	printf '%s\t%s\t%s\n' "$action" "$target" "$backup" >> "$MANIFEST"
}

backup_path() {
	local target="$1"
	local rel="${target#"$HOME"/}"
	local name="${rel//\//_}"
	local dest="$BACKUP_DIR/$name"
	if [ "$DRY_RUN" = 1 ]; then
		if [ -e "$target" ] || [ -L "$target" ]; then
			say "would back up ${target#"$HOME"/}"
		fi
		return 0
	fi
	if [ -e "$target" ] || [ -L "$target" ]; then
		mkdir -p -- "$BACKUP_DIR"
		# Avoid flattening collisions by adding a numeric suffix.
		if [ -e "$dest" ] || [ -L "$dest" ]; then
			local i=2
			while [ -e "${dest}.$i" ] || [ -L "${dest}.$i" ]; do i=$((i + 1)); done
			dest="${dest}.$i"
		fi
		cp -a -- "$target" "$dest"
		record backup "$target" "$dest"
		say "backed up ${target#"$HOME"/}"
	else
		record create "$target" ""
	fi
}

replace_home() {
	local target="$1"
	[ "$DRY_RUN" = 1 ] && return 0
	/usr/bin/python3 - "$target" "$HOME" <<'PY'
import os
import sys

root, home = sys.argv[1], sys.argv[2]
if os.path.isfile(root):
	paths = [root]
else:
	paths = []
	for base, _dirs, files in os.walk(root):
		paths.extend(os.path.join(base, f) for f in files)
needle = b"@HOME@"
for path in paths:
	try:
		with open(path, "rb") as f:
			data = f.read()
	except OSError:
		continue
	if needle not in data:
		continue
	with open(path, "wb") as f:
		f.write(data.replace(needle, home.encode()))
PY
}

ensure_dir() {
	local dir="$1"
	if [ "$DRY_RUN" = 1 ]; then
		say "would create ${dir#"$HOME"/}/"
	else
		mkdir -p -- "$dir"
	fi
}

install_tree() {
	local src="$1" dst="$2"
	[ -d "$src" ] || die "missing tree: $src"
	if [ "$DRY_RUN" = 1 ]; then
		backup_path "$dst"
		say "would install ${src#"$ROOT"/}/ → ${dst#"$HOME"/}/"
		return 0
	fi
	backup_path "$dst"
	rm -rf -- "$dst"
	mkdir -p -- "$(dirname -- "$dst")"
	cp -a -- "$src" "$dst"
	replace_home "$dst"
	ok "installed ${dst#"$HOME"/}/"
}

install_file() {
	local src="$1" dst="$2" mode="${3:-644}"
	[ -f "$src" ] || die "missing file: $src"
	if [ "$DRY_RUN" = 1 ]; then
		backup_path "$dst"
		say "would install ${src#"$ROOT"/} → ${dst#"$HOME"/}"
		return 0
	fi
	backup_path "$dst"
	install -Dm "$mode" -- "$src" "$dst"
	replace_home "$dst"
}

write_file() {
	local dst="$1" mode="${2:-644}"
	local tmp
	tmp="$(mktemp)"
	cat > "$tmp"
	if [ "$DRY_RUN" = 1 ]; then
		say "would write ${dst#"$HOME"/}"
		rm -f -- "$tmp"
		return 0
	fi
	backup_path "$dst"
	mkdir -p -- "$(dirname -- "$dst")"
	install -Dm "$mode" -- "$tmp" "$dst"
	rm -f -- "$tmp"
}

seed_file() {
	local src="$1" dst="$2" mode="${3:-644}"
	if [ -e "$dst" ] || [ -L "$dst" ]; then
		say "kept existing ${dst#"$HOME"/}"
		return 0
	fi
	install_file "$src" "$dst" "$mode"
}

render_template() {
	local src="$1" dst="$2" mode="${3:-644}"
	[ -f "$src" ] || die "missing template: $src"
	local content
	content="$(sed "s|@HOME@|$HOME|g" "$src")"
	write_file "$dst" "$mode" <<< "$content"
}

run() {
	if [ "$DRY_RUN" = 1 ]; then
		say "would run: $*"
		return 0
	fi
	"$@"
}

missing_packages() {
	local p
	for p in "$@"; do
		pacman -Qq "$p" >/dev/null 2>&1 || printf '%s\n' "$p"
	done
}

install_deps() {
	local repo_deps=(
		hyprland waybar swaync rofi kitty grim slurp swappy satty
		playerctl cliphist wl-clipboard brightnessctl pavucontrol
		network-manager-applet blueman bluez bluez-utils upower
		power-profiles-daemon cava python-gobject gtk4 gtk4-layer-shell
		python-pillow socat ffmpeg imagemagick polkit-gnome hypridle
		hyprlock inter-font ttf-fira-code ttf-jetbrains-mono-nerd libnotify psmisc fd
		ffmpegthumbnailer poppler zip 7zip tar nwg-look xdg-utils
		xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-hyprland
	)
	local aur_deps=(wallust waypaper wlogout mpvpaper wl-screenrec bibata-cursor-theme-bin hyprmod)
	local missing_repo=() missing_aur=()

	if [ "$NO_DEPS" = 1 ]; then
		mapfile -t missing_repo < <(missing_packages "${repo_deps[@]}")
		mapfile -t missing_aur < <(missing_packages "${aur_deps[@]}")
		if [ "${#missing_repo[@]}" -gt 0 ]; then
			warn "missing repo packages: ${missing_repo[*]}"
		fi
		if [ "${#missing_aur[@]}" -gt 0 ]; then
			warn "missing AUR packages: ${missing_aur[*]}"
		fi
		return 0
	fi

	command -v pacman >/dev/null 2>&1 || die "pacman not found; this installer targets Arch Linux"

	mapfile -t missing_repo < <(missing_packages "${repo_deps[@]}")
	if [ "${#missing_repo[@]}" -gt 0 ]; then
		warn "missing packages: ${missing_repo[*]}"
		confirm "Install them with pacman?" || die "missing dependencies"
		local sudo_cmd=()
		[ "$(id -u)" -eq 0 ] || sudo_cmd=(sudo)
		run "${sudo_cmd[@]}" pacman -S --needed --noconfirm "${missing_repo[@]}"
	fi

	mapfile -t missing_aur < <(missing_packages "${aur_deps[@]}")
	if [ "${#missing_aur[@]}" -gt 0 ]; then
		local helper=""
		if command -v yay >/dev/null 2>&1; then helper="yay"
		elif command -v paru >/dev/null 2>&1; then helper="paru"
		fi
		if [ -z "$helper" ]; then
			warn "missing AUR packages: ${missing_aur[*]}"
			die "install yay or paru, then: yay -S --needed ${missing_aur[*]}"
		else
			warn "missing AUR packages: ${missing_aur[*]}"
			confirm "Install them with $helper?" || die "missing AUR dependencies"
			run "$helper" -S --needed --noconfirm "${missing_aur[@]}"
		fi
	fi
}

check_runtime() {
	if ! /usr/bin/python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, Gtk4LayerShell
PY
	then
		die "GTK4 + PyGObject + Gtk4LayerShell are not importable with /usr/bin/python3"
	fi
	if ! compgen -G "/usr/lib/libgtk4-layer-shell.so*" >/dev/null; then
		die "libgtk4-layer-shell.so not found (install gtk4-layer-shell)"
	fi
	if ! command -v hyprctl >/dev/null 2>&1; then
		warn "hyprctl is not on PATH; the shell cannot reload Hyprland automatically"
	fi
}

install_deps
check_runtime

if [ "$DRY_RUN" = 0 ]; then
	mkdir -p -- "$STATE_DIR"
fi

# A single confirmation before replacing user configuration.
if [ "$DRY_RUN" = 0 ] && [ "$YES" != 1 ]; then
	say "The installer will replace ~/.config/{hypr,waybar,swaync,rofi,kitty,wallust,waypaper,wlogout}"
	say "and install the Glasswing daemon, Glass Files, launchers, and D-Bus entries."
	confirm "Continue?" || { say "cancelled"; exit 0; }
fi

ensure_dir "$HOME/.local/bin"
ensure_dir "$HOME/.local/share/applications"
ensure_dir "$HOME/.local/share/dbus-1/services"
ensure_dir "$HOME/.local/share/icons/hicolor/scalable/apps"
ensure_dir "$HOME/.local/share/glasswing"
ensure_dir "$HOME/.config/glass"
ensure_dir "$HOME/.config/cava"
ensure_dir "$HOME/Pictures/wallpapers"
ensure_dir "$HOME/Pictures/widgets"

# Desktop configuration.
install_tree "$ROOT/config/hypr" "$HOME/.config/hypr"
install_tree "$ROOT/config/waybar" "$HOME/.config/waybar"
install_tree "$ROOT/config/swaync" "$HOME/.config/swaync"
install_tree "$ROOT/config/rofi" "$HOME/.config/rofi"
install_tree "$ROOT/config/kitty" "$HOME/.config/kitty"
install_tree "$ROOT/config/wallust" "$HOME/.config/wallust"
install_tree "$ROOT/config/waypaper" "$HOME/.config/waypaper"
install_tree "$ROOT/config/wlogout" "$HOME/.config/wlogout"

# Seed user-editable shell settings without clobbering existing ones.
seed_file "$ROOT/config/glass/settings.json" "$HOME/.config/glass/settings.json"
seed_file "$ROOT/config/glass/shell.json" "$HOME/.config/glass/shell.json"
seed_file "$ROOT/config/glass/hypr-user.lua" "$HOME/.config/glass/hypr-user.lua"
seed_file "$ROOT/config/glass/accent.conf" "$HOME/.config/glass/accent.conf"

# Install the file manager source, then the small launchers.
install_tree "$ROOT/glass-files" "$HOME/.local/share/glasswing/glass-files"
write_file "$HOME/.local/bin/glass-files" 755 <<'EOF'
#!/usr/bin/env bash
# Glasswing launcher: always use the system Python that owns PyGObject.
exec /usr/bin/python3 "$HOME/.local/share/glasswing/glass-files/run.py" "$@"
EOF
for f in bar-start glass-files-open glass-idle glass-lock shot-full shot-region rec-toggle; do
	install_file "$ROOT/scripts/$f" "$HOME/.local/bin/$f" 755
done

# Desktop entry, icon, and D-Bus activation.
render_template "$ROOT/glass-files/data/glass-files.desktop" "$HOME/.local/share/applications/glass-files.desktop"
install_file "$ROOT/glass-files/data/local.glass.files.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/local.glass.files.svg"
render_template "$ROOT/glass-files/data/local.glass.files.service" "$HOME/.local/share/dbus-1/services/local.glass.files.service"
if [ "$NO_FILE_MANAGER" = 1 ]; then
	say "skipping org.freedesktop.FileManager1 registration"
else
	render_template "$ROOT/glass-files/data/org.freedesktop.FileManager1.service" "$HOME/.local/share/dbus-1/services/org.freedesktop.FileManager1.service"
fi

# Wallpaper and widget sample art.
seed_file "$ROOT/assets/wallpapers/glasswing.jpg" "$HOME/Pictures/wallpapers/glasswing.jpg"
seed_file "$ROOT/assets/widgets/glasswing.jpg" "$HOME/Pictures/widgets/glasswing.jpg"

if [ "$DRY_RUN" = 0 ]; then
	if command -v update-desktop-database >/dev/null 2>&1; then
		update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
	fi
	if command -v gtk-update-icon-cache >/dev/null 2>&1; then
		gtk-update-icon-cache -f -t -q "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
	fi
	if command -v xdg-mime >/dev/null 2>&1; then
		backup_path "$HOME/.config/mimeapps.list"
		if [ "$NO_FILE_MANAGER" = 0 ]; then
			xdg-mime default glass-files.desktop inode/directory >/dev/null 2>&1 || true
		fi
		for mime in image/png image/jpeg image/webp image/gif image/bmp image/tiff image/avif image/heic image/heif image/jxl; do
			xdg-mime default swappy.desktop "$mime" >/dev/null 2>&1 || true
		done
	fi
fi

if [ "$DRY_RUN" = 0 ]; then
	printf '%s\n' "$BACKUP_DIR" > "$STATE_DIR/last-install"
fi

if [ "$DRY_RUN" = 0 ] && [ "$NO_RELOAD" = 0 ] && [ "$HOME" = "$REAL_HOME" ] && [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && command -v hyprctl >/dev/null 2>&1; then
	hyprctl reload >/dev/null 2>&1 && ok "Hyprland reloaded" || warn "Hyprland reload failed; log out and back in"
	if ! pgrep -x waybar >/dev/null 2>&1; then
		"$HOME/.local/bin/bar-start" >/dev/null 2>&1 &
	fi
fi

if [ "$DRY_RUN" = 1 ]; then
	say "dry run complete — no files were changed"
else
	ok "Glasswing installed"
	say "Log out and back in (or restart Hyprland) to start the full shell."
	say "First run: Super+E opens Glass Files, Super+D opens the launcher."
	say "Backups: $BACKUP_DIR"
fi

#!/usr/bin/env bash
# Glasswing uninstaller. By default it removes the launchers, daemon, and
# desktop integration, but leaves your configuration in ~/.config intact.
set -euo pipefail

HOME="${HOME:-}"
DRY_RUN=0
YES=0
RESTORE=0
PURGE=0
REAL_HOME="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6 || true)"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/glasswing"

say()  { printf '\033[38;5;180m›\033[0m %s\n' "$*"; }
ok()   { printf '\033[38;5;120m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[38;5;214m!\033[0m %s\n' "$*"; }
die()  { printf '\033[38;5;203m✗\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
	cat <<'EOF'
Glasswing uninstaller

Usage: ./uninstall.sh [options]

Options:
  --restore    Restore every backup from the last install (full rollback)
  --purge      Remove the installed configs as well (does not restore)
  --dry-run    Show what would happen, change nothing
  --yes        Do not ask for confirmation
  -h, --help   Show this help

The default removes Glass Files, the Glasswing launchers and daemon, the
desktop entry, icon, and D-Bus services. Your ~/.config files are left alone.
EOF
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--restore) RESTORE=1 ;;
		--purge) PURGE=1 ;;
		--dry-run) DRY_RUN=1 ;;
		--yes|-y) YES=1 ;;
		-h|--help) usage; exit 0 ;;
		*) die "unknown option: $1 (try --help)" ;;
	esac
	shift
done

[ -n "$HOME" ] || die "HOME is not set"
case "$HOME" in
	/|"") die "refusing to operate on HOME=$HOME" ;;
esac
[ "$(id -u)" -ne 0 ] || die "run this as your desktop user, not as root"

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

remove_path() {
	local target="$1"
	case "$target" in
		"$HOME"/*) ;;
		*) die "refusing to remove outside HOME: $target" ;;
	esac
	[ "$target" = "$HOME" ] && die "refusing to remove HOME"
	if [ -e "$target" ] || [ -L "$target" ]; then
		if [ "$DRY_RUN" = 1 ]; then
			say "would remove ${target#"$HOME"/}"
		else
			rm -rf -- "$target"
			ok "removed ${target#"$HOME"/}"
		fi
	fi
}

stop_shell() {
	# Only target processes that belong to this HOME. This makes it safe to
	# test with a fake HOME while the live shell is running.
	if [ "$DRY_RUN" = 0 ] && [ -f "$HOME/.config/hypr/scripts/popouts/glassd.py" ]; then
		pkill -f "$HOME/.config/hypr/scripts/popouts/glassd.py" 2>/dev/null || true
	fi
	if [ "$DRY_RUN" = 0 ] && [ -d "$HOME/.local/share/glasswing/glass-files" ]; then
		pkill -f "$HOME/.local/share/glasswing/glass-files/run.py" 2>/dev/null || true
	fi
	if [ "$DRY_RUN" = 1 ]; then
		say "would stop the Glasswing popup daemon and Glass Files"
	fi
}

restore_last() {
	local manifest="$STATE_DIR/last-install"
	local backup_dir=""
	[ -f "$manifest" ] && backup_dir="$(head -n1 "$manifest")"
	if [ -z "$backup_dir" ] || [ ! -f "$backup_dir/manifest.tsv" ]; then
		warn "no install manifest found under $STATE_DIR/backups; removing launchers only"
		return 0
	fi
	say "restoring from $backup_dir"
	while IFS=$'\t' read -r action target backup; do
		[ -n "${action:-}" ] || continue
		case "$action" in
			backup|create) ;;
			*) continue ;;
		esac
		[ -n "${target:-}" ] || continue
		remove_path "$target"
		if [ "$action" = backup ] && [ -n "${backup:-}" ] && { [ -e "$backup" ] || [ -L "$backup" ]; }; then
			if [ "$DRY_RUN" = 1 ]; then
				say "would restore ${target#"$HOME"/}"
			else
				mkdir -p -- "$(dirname -- "$target")"
				cp -a -- "$backup" "$target"
				ok "restored ${target#"$HOME"/}"
			fi
		fi
	done < "$backup_dir/manifest.tsv"
	if [ "$DRY_RUN" = 0 ]; then
		rm -f -- "$STATE_DIR/last-install"
	fi
}

remove_launchers() {
	local f
	for f in glass-files bar-start glass-files-open shot-full shot-region rec-toggle; do
		remove_path "$HOME/.local/bin/$f"
	done
	remove_path "$HOME/.local/share/glasswing"
	remove_path "$HOME/.local/share/applications/glass-files.desktop"
	remove_path "$HOME/.local/share/icons/hicolor/scalable/apps/local.glass.files.svg"
	remove_path "$HOME/.local/share/dbus-1/services/local.glass.files.service"
	if [ -f "$HOME/.local/share/dbus-1/services/org.freedesktop.FileManager1.service" ] &&
		grep -q 'glass-files' "$HOME/.local/share/dbus-1/services/org.freedesktop.FileManager1.service" 2>/dev/null; then
		remove_path "$HOME/.local/share/dbus-1/services/org.freedesktop.FileManager1.service"
	fi
}

purge_configs() {
	local d
	for d in hypr waybar swaync rofi kitty wallust waypaper wlogout glass; do
		remove_path "$HOME/.config/$d"
	done
}

if [ "$RESTORE" = 1 ] && [ "$PURGE" = 1 ]; then
	die "--restore and --purge are mutually exclusive"
fi

if [ "$DRY_RUN" = 0 ] && [ "$YES" != 1 ]; then
	if [ "$RESTORE" = 1 ]; then
		say "This will stop Glasswing and restore the files backed up by the last install."
	elif [ "$PURGE" = 1 ]; then
		say "This will remove Glasswing and delete ~/.config/{hypr,waybar,swaync,rofi,kitty,wallust,waypaper,wlogout,glass}."
	else
		say "This will remove Glasswing launchers and desktop integration, but keep ~/.config."
	fi
	confirm "Continue?" || { say "cancelled"; exit 0; }
fi

stop_shell

if [ "$RESTORE" = 1 ]; then
	remove_launchers
	restore_last
elif [ "$PURGE" = 1 ]; then
	remove_launchers
	purge_configs
else
	remove_launchers
fi

if [ "$DRY_RUN" = 0 ] && command -v update-desktop-database >/dev/null 2>&1; then
	update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

if [ "$DRY_RUN" = 1 ]; then
	say "dry run complete — no files were changed"
else
	ok "Glasswing removed"
	if [ "$RESTORE" = 1 ]; then
		say "Restored the files backed up by the last install."
	elif [ "$PURGE" = 1 ]; then
		say "Configs removed. Log out and back in if you are still in a Glasswing session."
	else
		say "Your configs are still in ~/.config. Use --restore to roll them back, or --purge to delete them."
	fi
	if [ "$HOME" = "$REAL_HOME" ] && [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && command -v hyprctl >/dev/null 2>&1; then
		hyprctl reload >/dev/null 2>&1 || true
	fi
fi

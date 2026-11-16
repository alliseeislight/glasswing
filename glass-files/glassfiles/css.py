"""The whole stylesheet, generated with the live accent baked in."""

from __future__ import annotations

from . import accent as accent_mod

DARK = "dark"
LIGHT = "light"

FONT = 'Inter, "Inter Variable", "Cantarell", sans-serif'


def _palette(rgb, theme):
    r, g, b = rgb
    if theme == LIGHT:
        return {
            "card_bg": "rgba(255,255,255,0.46)",
            "card_grad": ("linear-gradient(155deg, rgba(255,255,255,0.72), "
                          "rgba(255,255,255,0.30) 55%, rgba(255,255,255,0.52))"),
            "card_border": "rgba(255,255,255,0.72)",
            "chrome_bg": "rgba(255,255,255,0.34)",
            "glass_bg": "rgba(255,255,255,0.40)",
            "glass_bg_strong": "rgba(255,255,255,0.60)",
            "fg": "rgba(24,26,36,0.94)",
            "fg_dim": "rgba(24,26,36,0.60)",
            "fg_faint": "rgba(24,26,36,0.42)",
            "hover": "rgba(20,22,32,0.07)",
            "pressed": "rgba(20,22,32,0.12)",
            "hairline": "rgba(20,22,32,0.10)",
            "field": "rgba(255,255,255,0.52)",
            "field_border": "rgba(20,22,32,0.10)",
            "inset_top": "rgba(255,255,255,0.85)",
            "inset_bottom": "rgba(20,22,32,0.05)",
            "shadow": "rgba(40,48,70,0.16)",
            "dark_on_accent": "rgba(18,20,28,0.90)",
        }
    return {
        "card_bg": "rgba(20,22,32,0.42)",
        "card_grad": ("linear-gradient(155deg, rgba(255,255,255,0.20), "
                      "rgba(255,255,255,0.04) 55%, rgba(255,255,255,0.10))"),
        "card_border": "rgba(255,255,255,0.28)",
        "chrome_bg": "rgba(18,20,30,0.30)",
        "glass_bg": "rgba(18,20,30,0.55)",
        "glass_bg_strong": "rgba(22,24,34,0.78)",
        "fg": "rgba(255,255,255,0.93)",
        "fg_dim": "rgba(255,255,255,0.62)",
        "fg_faint": "rgba(255,255,255,0.42)",
        "hover": "rgba(255,255,255,0.07)",
        "pressed": "rgba(255,255,255,0.12)",
        "hairline": "rgba(255,255,255,0.10)",
        "field": "rgba(255,255,255,0.06)",
        "field_border": "rgba(255,255,255,0.13)",
        "inset_top": "rgba(255,255,255,0.22)",
        "inset_bottom": "rgba(255,255,255,0.08)",
        "shadow": "rgba(0,0,0,0.28)",
        "dark_on_accent": "rgba(16,18,26,0.92)",
    }


def build(rgb=(168, 184, 230), theme=DARK, scale=1.0) -> str:
    p = _palette(rgb, theme)
    return f"""
{accent_mod.defines(rgb)}
@define-color glass_fg {p['fg']};
@define-color glass_fg_dim {p['fg_dim']};
@define-color glass_fg_faint {p['fg_faint']};
@define-color glass_hairline {p['hairline']};
@define-color glass_field {p['field']};

/* ---------------------------------------------------------------- window */
window.glass-window,
window.glass-window > contents {{
    background-color: transparent;
    color: @glass_fg;
}}
window.glass-window.dialog,
window.glass-window.popup {{
    background: transparent;
}}

.glass-root {{
    font-family: {FONT};
    font-size: 13px;
    color: @glass_fg;
    background-color: {p['card_bg']};
    background-image: {p['card_grad']};
    border: 1px solid {p['card_border']};
    border-radius: 20px;
    box-shadow: inset 0 1px 0 @glass_accent_mid,
                inset 0 -1px 0 {p['inset_bottom']},
                0 18px 50px {p['shadow']};
}}

/* ---------------------------------------------------------------- chrome */
.chrome {{
    background-color: {p['chrome_bg']};
    background-image: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.00));
    border-top-left-radius: 20px;
    border-top-right-radius: 20px;
    border-bottom: 1px solid {p['hairline']};
    box-shadow: inset 0 1px 0 {p['inset_top']};
    padding: 8px 10px;
}}
.chrome-bottom {{ border-bottom: none; border-top: 1px solid {p['hairline']}; }}

.nav-btn {{
    min-width: 32px; min-height: 32px;
    padding: 0;
    border-radius: 16px;
    background: none;
    background-image: none;
    border: 1px solid transparent;
    box-shadow: none;
    color: {p['fg_dim']};
    transition: background-color 140ms ease, color 140ms ease;
}}
.nav-btn:hover {{
    background-color: {p['hover']};
    color: @glass_fg;
}}
.nav-btn:active {{ background-color: {p['pressed']}; }}
.nav-btn:disabled {{ color: {p['fg_faint']}; background: none; }}

.win-btn {{
    min-width: 28px; min-height: 28px;
    padding: 0;
    border-radius: 14px;
    background: none; background-image: none;
    border: none; box-shadow: none;
    color: {p['fg_dim']};
}}
.win-btn:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.win-btn.close:hover {{ background-color: rgba(214,92,92,0.75); color: white; }}

.pill {{
    border-radius: 18px;
    background-color: {p['field']};
    border: 1px solid {p['field_border']};
    box-shadow: inset 0 1px 0 {p['inset_top']};
    padding: 2px 6px;
}}
.pill-flat {{
    border-radius: 18px;
    background: none;
    border: 1px solid transparent;
    padding: 2px;
}}

.breadcrumb {{ padding: 0 2px; }}
.crumb-btn {{
    min-height: 28px;
    padding: 2px 9px;
    border-radius: 12px;
    background: none; background-image: none;
    border: 1px solid transparent;
    box-shadow: none;
    color: {p['fg_dim']};
    font-weight: 500;
}}
.crumb-btn:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.crumb-btn.crumb-cur {{
    color: @glass_fg;
    background-color: @glass_accent_soft;
    border-color: @glass_accent_line;
}}
.crumb-sep {{ color: {p['fg_faint']}; font-size: 10px; padding: 0 1px; }}
.crumb-over {{ background-color: @glass_accent_soft; border-color: @glass_accent_line; }}

.path-entry {{
    background: none; background-image: none;
    border: none; box-shadow: none;
    color: @glass_fg;
    caret-color: @glass_accent;
    font-family: "JetBrainsMono Nerd Font", monospace;
    font-size: 12px;
    min-height: 28px;
    padding: 0 6px;
}}
.path-entry selection {{ background-color: @glass_accent_soft; color: @glass_fg; }}

.search-entry {{
    background: none; background-image: none;
    border: none; box-shadow: none;
    color: @glass_fg;
    caret-color: @glass_accent;
    min-height: 28px;
    padding: 0 2px;
}}
.search-entry image {{ color: {p['fg_faint']}; }}
.search-entry placeholder {{ color: {p['fg_faint']}; }}

.seg {{ border-radius: 18px; padding: 2px; }}
.seg-btn {{
    min-width: 30px; min-height: 28px;
    padding: 0 6px;
    border-radius: 14px;
    background: none; background-image: none;
    border: 1px solid transparent;
    box-shadow: none;
    color: {p['fg_dim']};
}}
.seg-btn:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.seg-btn:checked {{
    background-color: @glass_accent_soft;
    border-color: @glass_accent_line;
    color: @glass_fg;
}}

.menu-btn {{
    min-height: 30px;
    padding: 2px 10px;
    border-radius: 15px;
    background: none; background-image: none;
    border: 1px solid transparent;
    box-shadow: none;
    color: {p['fg_dim']};
    font-weight: 500;
}}
.menu-btn:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.menu-btn.accent {{ color: @glass_accent; }}

/* ------------------------------------------------------------------ tabs */
.tabstrip {{
    background-color: {p['chrome_bg']};
    padding: 4px 10px 7px 10px;
    border-bottom: 1px solid {p['hairline']};
}}
.tab {{
    min-height: 28px;
    padding: 2px 6px 2px 12px;
    border-radius: 14px;
    background: none; background-image: none;
    border: 1px solid transparent;
    box-shadow: none;
    color: {p['fg_dim']};
}}
.tab:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.tab.tab-active {{
    background-color: {p['field']};
    border-color: {p['field_border']};
    box-shadow: inset 0 1px 0 {p['inset_top']};
    color: @glass_fg;
    font-weight: 500;
}}
.tab.tab-active .tab-dot {{ color: @glass_accent; }}
.tab-close {{
    min-width: 20px; min-height: 20px;
    padding: 0; border-radius: 10px;
    background: none; background-image: none;
    border: none; box-shadow: none;
    color: {p['fg_faint']};
}}
.tab-close:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.tab-add {{
    min-width: 28px; min-height: 28px;
    padding: 0; border-radius: 14px;
    background: none; background-image: none;
    border: none; box-shadow: none;
    color: {p['fg_dim']};
}}
.tab-add:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.tab-drop {{ background-color: @glass_accent_soft; }}

/* --------------------------------------------------------------- sidebar */
.sidebar {{
    background-color: rgba(255,255,255,0.035);
    border-right: 1px solid {p['hairline']};
    border-bottom-left-radius: 20px;
    padding: 6px 8px 12px 8px;
}}
.side-head {{
    min-height: 26px;
    padding: 2px 8px;
    border-radius: 12px;
    background: none; background-image: none;
    border: none; box-shadow: none;
    color: {p['fg_faint']};
    font-size: 11px;
    font-weight: 600;
}}
.side-head:hover {{ color: {p['fg_dim']}; background: none; }}
.side-row {{
    min-height: 30px;
    padding: 2px 8px;
    border-radius: 12px;
    background: none; background-image: none;
    border: 1px solid transparent;
    box-shadow: none;
    color: {p['fg_dim']};
}}
.side-row:hover {{ background-color: {p['hover']}; color: @glass_fg; }}
.side-row.side-on {{
    background-color: @glass_accent_soft;
    border-color: @glass_accent_line;
    color: @glass_fg;
    font-weight: 500;
}}
.side-row image {{ color: {p['fg_dim']}; }}
.side-row.side-on image {{ color: @glass_accent; }}
.side-badge {{
    min-width: 18px;
    padding: 1px 6px;
    border-radius: 9px;
    background-color: {p['hover']};
    color: {p['fg_dim']};
    font-size: 10px;
    font-weight: 600;
}}
.side-bar {{ min-height: 3px; border-radius: 2px; background-color: {p['hairline']}; }}
.side-bar > trough {{ min-height: 3px; border-radius: 2px; background-color: {p['hairline']}; }}
.side-bar > trough > progress {{ min-height: 3px; border-radius: 2px; background-color: @glass_accent; }}
.side-sub {{ font-size: 10px; color: {p['fg_faint']}; }}

/* ----------------------------------------------------------------- panes */
.pane {{ background: transparent; }}
.pane-inactive {{ opacity: 0.94; }}
.view-swap {{ background: transparent; }}

gridview, columnview, listview {{
    background: transparent;
    color: @glass_fg;
}}
gridview > child, columnview > listview > row {{
    border-radius: 16px;
    outline: none;
}}
gridview > child:hover {{ background-color: {p['hover']}; }}
gridview > child:selected {{
    background-color: @glass_accent_soft;
    box-shadow: inset 0 0 0 1px @glass_accent_line;
}}
gridview > child:selected .item-label {{ color: @glass_fg; font-weight: 500; }}

columnview > listview > row {{ border-radius: 12px; }}
columnview > listview > row:hover {{ background-color: {p['hover']}; }}
columnview > listview > row:selected {{
    background-color: @glass_accent_soft;
    box-shadow: inset 0 0 0 1px @glass_accent_line;
}}
columnview > header > button {{
    min-height: 30px;
    padding: 0 8px;
    border-radius: 10px;
    background: none; background-image: none;
    border: none; box-shadow: none;
    color: {p['fg_faint']};
    font-size: 11px;
    font-weight: 600;
}}
columnview > header > button:hover {{ color: {p['fg_dim']}; }}
columnview > header > button:checked {{ color: @glass_accent; }}

.item {{ padding: 8px; }}
.item-icon {{ margin: 2px 0 4px 0; }}
.item-label {{
    font-size: 12px;
    color: @glass_fg;
    text-shadow: 0 1px 2px rgba(0,0,0,0.10);
}}
.item-meta {{ font-size: 10px; color: {p['fg_faint']}; }}
.row-cell {{ padding: 0 6px; font-size: 12px; color: {p['fg_dim']}; }}
.row-name {{ color: @glass_fg; }}
.row-icon {{ margin-right: 8px; }}

/* ---------------------------------------------------------------- status */
.status {{
    background-color: {p['chrome_bg']};
    border-top: 1px solid {p['hairline']};
    border-bottom-left-radius: 20px;
    border-bottom-right-radius: 20px;
    padding: 4px 14px;
    color: {p['fg_faint']};
    font-size: 11px;
}}
.status-label {{ color: {p['fg_faint']}; font-size: 11px; }}
.status-strong {{ color: {p['fg_dim']}; }}
.zoom scale {{ min-width: 92px; }}
.zoom scale > trough {{ min-height: 3px; border-radius: 2px; background-color: {p['hairline']}; }}
.zoom scale > trough > highlight {{ min-height: 3px; border-radius: 2px; background-color: @glass_accent; }}
.zoom scale > slider {{ min-width: 11px; min-height: 11px; border-radius: 6px; background-color: @glass_fg; border: none; box-shadow: none; }}
.zoom scale > slider:hover {{ background-color: @glass_accent; }}

/* --------------------------------------------------------------- popover */
popover.background {{
    background: none;
    box-shadow: none;
    border: none;
}}
popover.background > contents {{
    background-color: {p['glass_bg']};
    background-image: {p['card_grad']};
    border: 1px solid {p['card_border']};
    border-radius: 18px;
    box-shadow: inset 0 1px 0 {p['inset_top']}, 0 12px 34px {p['shadow']};
    padding: 6px;
    color: @glass_fg;
}}
popover.background modelbutton,
popover.background menu item {{
    min-height: 28px;
    padding: 2px 10px;
    border-radius: 10px;
    color: @glass_fg;
}}
popover.background modelbutton:hover {{ background-color: {p['hover']}; }}
popover.background modelbutton:disabled {{ color: {p['fg_faint']}; }}
popover.background separator {{ background-color: {p['hairline']}; min-height: 1px; margin: 4px 8px; }}

/* --------------------------------------------------------------- dialogs */
window.dialog .glass-root,
.dialog-glass {{
    background-color: {p['glass_bg_strong']};
    background-image: {p['card_grad']};
    border: 1px solid {p['card_border']};
    border-radius: 20px;
    box-shadow: inset 0 1px 0 {p['inset_top']}, 0 20px 60px {p['shadow']};
    color: @glass_fg;
}}
.dialog-title {{ font-size: 15px; font-weight: 600; color: @glass_fg; }}
.dialog-sub {{ font-size: 12px; color: {p['fg_dim']}; }}
.field {{
    background-color: {p['field']};
    background-image: none;
    border: 1px solid {p['field_border']};
    border-radius: 12px;
    box-shadow: inset 0 1px 0 {p['inset_top']};
    color: @glass_fg;
    caret-color: @glass_accent;
    min-height: 32px;
    padding: 2px 10px;
}}
.field:focus {{ border-color: @glass_accent_line; }}
.field selection {{ background-color: @glass_accent_soft; color: @glass_fg; }}
textview, textview > text {{
    background: transparent;
    color: @glass_fg;
}}

.btn {{
    min-height: 30px;
    padding: 2px 14px;
    border-radius: 15px;
    background-color: {p['field']};
    background-image: none;
    border: 1px solid {p['field_border']};
    box-shadow: inset 0 1px 0 {p['inset_top']};
    color: @glass_fg;
    font-weight: 500;
}}
.btn:hover {{ background-color: {p['hover']}; }}
.btn.suggested {{
    background-color: @glass_accent_soft;
    border-color: @glass_accent_line;
}}
.btn.destructive {{
    color: #f0b6b6;
    background-color: rgba(214,92,92,0.16);
    border-color: rgba(214,92,92,0.42);
}}
.btn.flat {{ background: none; box-shadow: none; border-color: transparent; }}
.btn.flat:hover {{ background-color: {p['hover']}; }}

switch {{
    min-width: 40px; min-height: 22px;
    border-radius: 12px;
    background-color: {p['hairline']};
    border: 1px solid {p['field_border']};
    box-shadow: none;
}}
switch:checked {{ background-color: @glass_accent_mid; border-color: @glass_accent_line; }}
switch > slider {{ min-width: 18px; min-height: 18px; border-radius: 9px; background-color: #f4f2ee; }}

checkbutton check {{
    min-width: 16px; min-height: 16px;
    border-radius: 5px;
    border: 1px solid {p['field_border']};
    background-color: {p['field']};
    background-image: none;
}}
checkbutton check:checked {{
    background-color: @glass_accent_mid;
    border-color: @glass_accent_line;
    color: {p['dark_on_accent']};
}}
radiobutton radio {{
    min-width: 16px; min-height: 16px;
    border-radius: 9px;
    border: 1px solid {p['field_border']};
    background-color: {p['field']};
    background-image: none;
}}
radiobutton radio:checked {{ background-color: @glass_accent_mid; border-color: @glass_accent_line; }}

/* ------------------------------------------------------- progress / jobs */
.job-title {{ font-weight: 600; color: @glass_fg; font-size: 12px; }}
.job-sub {{ color: {p['fg_faint']}; font-size: 11px; }}
progressbar trough {{
    min-height: 5px; border-radius: 3px;
    background-color: {p['hairline']};
}}
progressbar progress {{
    min-height: 5px; border-radius: 3px;
    background-color: @glass_accent;
}}
progressbar text {{ color: {p['fg_faint']}; font-size: 10px; }}
.job-cancel {{
    min-width: 24px; min-height: 24px; padding: 0;
    border-radius: 12px;
    background: none; background-image: none; border: none; box-shadow: none;
    color: {p['fg_faint']};
}}
.job-cancel:hover {{ color: @glass_fg; background-color: {p['hover']}; }}

/* ------------------------------------------------------------ empty state */
.empty {{ padding: 40px; }}
.empty-title {{ font-size: 16px; font-weight: 600; color: {p['fg_dim']}; }}
.empty-sub {{ font-size: 12px; color: {p['fg_faint']}; }}
.empty-icon {{ color: {p['fg_faint']}; margin-bottom: 6px; }}

/* ------------------------------------------------------------ quick look */
.ql {{ border-radius: 20px; }}
.ql-media {{ border-radius: 16px; background-color: rgba(0,0,0,0.18); }}
.ql-title {{ font-size: 14px; font-weight: 600; color: @glass_fg; }}
.ql-meta {{ font-size: 11px; color: {p['fg_faint']}; }}
.ql-text {{
    font-family: "JetBrainsMono Nerd Font", monospace;
    font-size: 11px;
    color: {p['fg_dim']};
    background-color: rgba(0,0,0,0.14);
    border-radius: 14px;
    padding: 10px;
}}
.mono {{ font-family: "JetBrainsMono Nerd Font", monospace; font-size: 11px; }}

/* -------------------------------------------------------------- previews */
.preview {{ background-color: {p['chrome_bg']}; border-left: 1px solid {p['hairline']}; padding: 10px; border-bottom-right-radius: 20px; }}
.preview-title {{ font-weight: 600; font-size: 13px; }}
.preview-meta {{ font-size: 11px; color: {p['fg_faint']}; }}

/* --------------------------------------------------------------- scrollbar */
scrollbar {{ background: transparent; }}
scrollbar slider {{
    min-width: 5px; min-height: 28px;
    border-radius: 3px;
    background-color: {p['hairline']};
}}
scrollbar slider:hover {{ background-color: {p['pressed']}; }}
scrollbar.vertical {{ padding: 2px; }}

/* --------------------------------------------------------------- misc */
separator {{ background-color: {p['hairline']}; min-height: 1px; min-width: 1px; }}
tooltip.background {{
    background-color: {p['glass_bg_strong']};
    border: 1px solid {p['card_border']};
    border-radius: 10px;
    color: @glass_fg;
    padding: 3px 8px;
}}
*:focus {{ outline: none; }}
.focus-ring:focus-within {{ border-color: @glass_accent_line; }}
.link {{ color: @glass_accent; }}
.dim {{ color: {p['fg_dim']}; }}
.faint {{ color: {p['fg_faint']}; }}
.title-strong {{ font-weight: 600; }}
.small {{ font-size: 11px; }}
.tag {{
    padding: 1px 8px; border-radius: 9px;
    background-color: @glass_accent_soft;
    border: 1px solid @glass_accent_line;
    color: @glass_fg; font-size: 10px;
}}
.error {{ color: #f0b6b6; }}
"""

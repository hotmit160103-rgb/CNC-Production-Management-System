import json
import pandas as pd
import streamlit as st
from pathlib import Path


class _CachedFile:
    """Proxy for UploadedFile — preserves file data across multi-page navigation."""
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data
        self.size = len(data)
    def getvalue(self) -> bytes:
        return self._data
    def read(self) -> bytes:
        return self._data


_NC_CACHE_KEY = "_nc_files_cache"

# ── Cost parameter defaults & session-state helper ────────────────────────────
_COST_DEFAULTS: dict = {
    "machine_hour_rate":  150_000.0,
    "labor_hour_rate":     50_000.0,
    "tooling_hour_rate":   30_000.0,
    "energy_hour_rate":    10_000.0,
    "overhead_hour_rate":  20_000.0,
    "batch_quantity":          100,
}

# Widget keys used in the Costing page — shared so Optimize can read them
_COST_KEYS = {
    "machine_hour_rate":  "cp_machine_rate",
    "labor_hour_rate":    "cp_labor_rate",
    "tooling_hour_rate":  "cp_tooling_rate",
    "energy_hour_rate":   "cp_energy_rate",
    "overhead_hour_rate": "cp_overhead_rate",
    "batch_quantity":     "cp_batch_qty",
}


def get_cost_cfg() -> dict:
    """Read current cost configuration from session state (set by Costing page)."""
    return {
        k: (int(st.session_state[wk]) if k == "batch_quantity"
            else float(st.session_state[wk]))
        if (wk := _COST_KEYS[k]) in st.session_state
        else _COST_DEFAULTS[k]
        for k in _COST_DEFAULTS
    }


# ── Color tokens ──────────────────────────────────────────────────────────────

PRIMARY        = "#1a2b4a"
PRIMARY_HOVER  = "#0f1c30"
PRIMARY_LIGHT  = "#eef1f7"
DANGER         = "#e2483b"
DANGER_LIGHT   = "#fdf1f0"
DANGER_BORDER  = "#f5b8b4"
SUCCESS        = "#1a8a50"
SUCCESS_LIGHT  = "#edf7f2"
SUCCESS_BORDER = "#a3d9bc"
WARNING        = "#c97b10"
WARNING_LIGHT  = "#fdf3e3"
INK            = "#222222"
BODY           = "#3f3f3f"
MUTED          = "#6a6a6a"
MUTED_SOFT     = "#929292"
CANVAS         = "#ffffff"
SURFACE_SOFT   = "#f7f7f7"
SURFACE_STRONG = "#f2f2f2"
HAIRLINE       = "#dddddd"
HAIRLINE_SOFT  = "#ebebeb"
SIDEBAR_TEXT   = "#b0bfd4"
SIDEBAR_LABEL  = "#7a94b0"

SHADOW = "rgba(0,0,0,.02) 0 0 0 1px, rgba(0,0,0,.04) 0 2px 6px 0, rgba(0,0,0,.08) 0 4px 8px 0"
LIMIT_LINE_COLOR = "rgba(226,72,59,0.7)"
CHART_FONT = dict(family="Inter, -apple-system, sans-serif", size=11, color=BODY)

TIME_CATEGORY_COLORS = {
    "Effective Cutting Interpolation Time":   "#1a2b4a",
    "Non-cutting Rapid Positioning Time":     "#1a8a50",
    "Automatic Tool Change Time":             "#c97b10",
    "Spindle Start or Speed Change Time":     "#5b6fa8",
    "Unclassified Motion Time":               "#aab0be",
    "Other Non-productive Event Time":        "#dddddd",
}

AXIS_COLORS = {"X": "#1a2b4a", "Y": "#1a8a50", "Z": "#c97b10"}


# ── Nav icon helpers ──────────────────────────────────────────────────────────

_NAV_ICON_PATHS = {
    "dashboard": (
        "<rect x='3' y='3' width='7' height='9'/>"
        "<rect x='14' y='3' width='7' height='5'/>"
        "<rect x='14' y='12' width='7' height='9'/>"
        "<rect x='3' y='16' width='7' height='5'/>"
    ),
    "cycle": "<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>",
    "faults": (
        "<path d='M10.3 3.6L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3"
        "L13.7 3.6a2 2 0 0 0-3.4 0z'/>"
        "<line x1='12' y1='9' x2='12' y2='13'/>"
        "<line x1='12' y1='17' x2='12.01' y2='17'/>"
    ),
    "costing": (
        "<circle cx='12' cy='12' r='9'/>"
        "<path d='M12 7v10M14.6 9.3c-.6-.7-1.6-1.1-2.6-1.1-1.7 0-3 1-3 2.3"
        "s1.3 1.8 3 2.1 3 .8 3 2.1S13.7 19 12 19c-1 0-2-.4-2.6-1.1'/>"
    ),
    "optimize": "<path d='M13 2 4 14h7l-1 8 9-12h-7z'/>",
}


def _svg_icon_url(paths: str, stroke: str) -> str:
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' "
        f"viewBox='0 0 24 24' fill='none' stroke='{stroke}' "
        f"stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round'>"
        f"{paths}</svg>"
    )
    encoded = (
        svg
        .replace("%", "%25")
        .replace("#", "%23")
        .replace("<", "%3C")
        .replace(">", "%3E")
    )
    return f'url("data:image/svg+xml,{encoded}")'


def _build_nav_icon_css() -> str:
    icons = list(_NAV_ICON_PATHS.items())
    parts = []
    for i, (_, paths) in enumerate(icons, 1):
        dim = f'[data-testid="stSidebarNavItems"] li:nth-child({i})'
        url_dim = _svg_icon_url(paths, "#6a86a5")
        url_bright = _svg_icon_url(paths, "#ffffff")
        parts.append(
            f'{dim} [data-testid="stSidebarNavLink"]::before'
            f' {{ background-image: {url_dim}; }}\n'
            f'{dim} [data-testid="stSidebarNavLink"]:hover::before,'
            f'{dim} [data-testid="stSidebarNavLink"][aria-current="page"]::before'
            f' {{ background-image: {url_bright}; }}'
        )
    return "<style>\n" + "\n".join(parts) + "\n</style>"


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* App background — pure white, no gray bleed around content card */
.stApp { background-color: #ffffff; }

/* Main content block */
.block-container {
    background-color: #ffffff;
    padding: 28px 32px 56px 32px !important;
    max-width: 1280px !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div:first-child {
    background-color: #1a2b4a !important;
}

/* ── Sidebar layout order: Header(logo) → Nav → UserContent ── */
[data-testid="stSidebarContent"] {
    display: flex !important;
    flex-direction: column !important;
}
[data-testid="stSidebarNav"]         { order: 1; }
[data-testid="stSidebarUserContent"] { order: 2; }

/* ── Sidebar Brand Header ── */
[data-testid="stSidebarHeader"] {
    position: relative !important;
    padding: 20px 22px 18px !important;
    border-bottom: 1px solid rgba(255,255,255,0.08) !important;
    flex-direction: column !important;
    align-items: flex-start !important;
    gap: 0 !important;
}

[data-testid="stLogoSpacer"] {
    display: none !important;
}

[data-testid="stSidebarCollapseButton"] {
    position: absolute !important;
    right: 10px !important;
    top: 14px !important;
}

[data-testid="stSidebarHeader"]::before {
    content: "CNC Manufacturing\\A Management System";
    white-space: pre-line;
    display: block;
    font-family: 'Inter', -apple-system, sans-serif;
    font-size: 17px;
    font-weight: 750;
    letter-spacing: -0.035em;
    color: #ffffff;
    line-height: 1.08;
    max-width: 230px;
}

[data-testid="stSidebarHeader"]::after {
    content: "OFFLINE SIMULATION SUITE";
    display: block;
    font-family: 'Inter', -apple-system, sans-serif;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.18em;
    color: #7eb8f0;
    margin-top: 8px;
    opacity: 0.85;
}

/* ── Nav ── */
[data-testid="stSidebarNav"] {
    background: transparent;
    padding: 8px 8px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 4px;
}
[data-testid="stSidebarNav"]::before {
    content: "NAVIGATION";
    display: block;
    font-family: 'Inter', sans-serif;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #3d567a;
    padding: 8px 14px 8px;
}
[data-testid="stSidebarNav"] ul { padding: 0; margin: 0; gap: 2px; }
[data-testid="stSidebarNavSeparator"] { display: none !important; }

[data-testid="stSidebarNavLink"] {
    display: flex !important;
    align-items: center !important;
    gap: 12px !important;
    padding: 10px 14px !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    color: #7a96b2 !important;
    background: transparent !important;
    border-radius: 10px !important;
    border-left: 3px solid transparent !important;
    transition: all 140ms ease !important;
    margin: 0 !important;
    text-decoration: none !important;
}
[data-testid="stSidebarNavLink"]:hover {
    color: #c8daf0 !important;
    background: rgba(255,255,255,0.08) !important;
    border-left-color: rgba(255,255,255,0.30) !important;
}
/* Active — strong contrast, unmistakably selected */
[data-testid="stSidebarNavLink"][aria-current="page"] {
    color: #ffffff !important;
    background: rgba(255,255,255,0.22) !important;
    border-left: 3px solid #7eb8f0 !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
}

/* Icon container — 28×28 rounded square */
[data-testid="stSidebarNavLink"]::before {
    content: "" !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 28px !important;
    height: 28px !important;
    min-width: 28px !important;
    border-radius: 7px !important;
    background-color: rgba(255,255,255,0.08) !important;
    background-repeat: no-repeat !important;
    background-position: center center !important;
    background-size: 15px 15px !important;
    transition: background-color 140ms ease !important;
}
[data-testid="stSidebarNavLink"]:hover::before {
    background-color: rgba(255,255,255,0.13) !important;
}
/* Active icon — clearly distinct */
[data-testid="stSidebarNavLink"][aria-current="page"]::before {
    background-color: rgba(255,255,255,0.28) !important;
}

/* ── Nav item labels & subtitles — p only, no stMarkdownContainer::after ── */

/* Item 1: hide "app", use p::before for label, p::after for subtitle */
[data-testid="stSidebarNavLink"] span[label="app"] p {
    font-size: 0 !important;
    line-height: 0 !important;
    overflow: visible !important;
}
[data-testid="stSidebarNavLink"] span[label="app"] p::before {
    content: "DASHBOARD" !important;
    display: block !important;
    font-size: 12px !important;
    font-weight: inherit !important;
    letter-spacing: 0.05em !important;
    line-height: 1.2 !important;
    text-transform: uppercase !important;
    /* inherits color from <a> — inactive:#7a96b2, active:#fff */
}
[data-testid="stSidebarNavItems"] li:nth-child(1) [data-testid="stSidebarNavLink"] p::after {
    content: "Simulation overview";
}

/* Items 2-5: p::after for subtitles */
[data-testid="stSidebarNavItems"] li:nth-child(2) [data-testid="stSidebarNavLink"] p::after { content: "Breakdown & timing"; }
[data-testid="stSidebarNavItems"] li:nth-child(3) [data-testid="stSidebarNavLink"] p::after { content: "MCS safety check"; }
[data-testid="stSidebarNavItems"] li:nth-child(4) [data-testid="stSidebarNavLink"] p::after { content: "Cost estimation"; }
[data-testid="stSidebarNavItems"] li:nth-child(5) [data-testid="stSidebarNavLink"] p::after { content: "Improvement tips"; }

/* Shared subtitle style for all items */
[data-testid="stSidebarNavItems"] li [data-testid="stSidebarNavLink"] p::after {
    display: block !important;
    font-size: 10px !important;
    font-weight: 400 !important;
    letter-spacing: 0.01em !important;
    text-transform: none !important;
    color: #44617c !important;
    margin-top: 2px !important;
    line-height: 1.2 !important;
}

/* Active state: label (::before) inherits white from <a>, subtitle (::after) dims */
[data-testid="stSidebarNavItems"] li [data-testid="stSidebarNavLink"][aria-current="page"] p::after {
    color: rgba(255,255,255,0.65) !important;
}

[data-testid="stSidebarNav"] li a span { color: inherit !important; }

/* Sidebar text defaults */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] .stMarkdown p { color: #b0bfd4; font-size: 13px; }

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #ffffff !important; }

[data-testid="stSidebar"] label {
    color: #5c7a9a !important;
    font-size: 9px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.12em !important;
}

/* ── Unified number-input pill ── */
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"] {
    display: flex !important;
    align-items: stretch !important;
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 10px !important;
    overflow: hidden !important;
    height: 40px !important;
    gap: 0 !important;
    padding: 0 !important;
    transition: border-color 130ms ease !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"]:focus-within {
    border-color: rgba(255,255,255,0.30) !important;
    box-shadow: 0 0 0 2px rgba(255,255,255,0.06) !important;
}
/* Transparent inner wrappers */
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"] > div {
    background: transparent !important;
    border: none !important;
    display: contents !important;
}
/* The actual <input> */
[data-testid="stSidebar"] [data-testid="stNumberInputField"] {
    flex: 1 !important;
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: #d8e8f4 !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 0 12px !important;
    height: 100% !important;
    min-width: 0 !important;
    box-shadow: none !important;
    outline: none !important;
}
/* Buttons separator container */
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"] > div:last-child,
[data-testid="stSidebar"] [data-testid="stNumberInputContainer"] > div > div:last-child {
    display: flex !important;
    align-items: stretch !important;
    border-left: 1px solid rgba(255,255,255,0.10) !important;
    background: transparent !important;
}
/* Step-down and step-up buttons */
[data-testid="stSidebar"] [data-testid="stNumberInputStepDown"],
[data-testid="stSidebar"] [data-testid="stNumberInputStepUp"] {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: #5a7898 !important;
    width: 34px !important;
    min-width: 34px !important;
    height: 100% !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: 14px !important;
    cursor: pointer !important;
    transition: background 110ms ease, color 110ms ease !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInputStepDown"] {
    border-right: 1px solid rgba(255,255,255,0.08) !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInputStepDown"]:hover,
[data-testid="stSidebar"] [data-testid="stNumberInputStepUp"]:hover {
    background: rgba(255,255,255,0.10) !important;
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInputStepDown"]:active,
[data-testid="stSidebar"] [data-testid="stNumberInputStepUp"]:active {
    background: rgba(255,255,255,0.16) !important;
}
/* Text inputs (not number) */
[data-testid="stSidebar"] .stTextInput input {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 10px !important;
    color: #d8e8f4 !important;
    font-size: 13px !important;
    font-weight: 500 !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(255,255,255,0.14) !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] [aria-selected],
[data-testid="stSidebar"] [data-baseweb="select"] div[class] { color: #e2eaf4 !important; }
[data-testid="stSidebar"] [data-baseweb="select"] svg { fill: #5c7a9a !important; }

/* Collapse button */
[data-testid="stSidebarCollapseButton"] button {
    color: #3d567a !important;
    border-radius: 6px !important;
}
[data-testid="stSidebarCollapseButton"] button:hover {
    color: #8aa8c8 !important;
    background: rgba(255,255,255,0.07) !important;
}

/* Sidebar file uploader dropzone — compact, clean */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
    border: 1.5px dashed rgba(255,255,255,0.20) !important;
    border-radius: 12px !important;
    background: rgba(255,255,255,0.03) !important;
    padding: 14px 16px !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    gap: 10px !important;
    min-height: unset !important;
}
/* Hide "200MB per file" and drag-drop instruction text in ALL possible elements */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small,
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] p,
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] { display: none !important; }
/* Upload button — pill style */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
    width: 100% !important;
    background: rgba(255,255,255,0.10) !important;
    color: #c4d6ea !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    border-radius: 9px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    padding: 10px 16px !important;
    height: auto !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 8px !important;
    transition: all 120ms ease !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
    background: rgba(255,255,255,0.17) !important;
    border-color: rgba(255,255,255,0.30) !important;
    color: #ffffff !important;
}
/* Hide the icon inside the button — we use just text */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button svg { display: none !important; }
/* Inject text via ::after since SVG is hidden */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button::before {
    content: "↑  Upload .nc files";
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
}
/* Hide native file chips — custom card renders instead */
[data-testid="stSidebar"] [data-testid="stFileChips"] { display: none !important; }

/* Sidebar general button (Change file) */
[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.06) !important;
    color: #6a86a5 !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    width: 100% !important;
    height: 32px !important;
    transition: all 120ms ease !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.12) !important;
    color: #c4d6ea !important;
    border-color: rgba(255,255,255,0.22) !important;
}

/* ── Machine dropdown portal (renders outside sidebar) ── */
[data-baseweb="popover"] [data-baseweb="menu"],
[data-baseweb="popover"] ul[role="listbox"] {
    background: #162238 !important;
    border: 1px solid rgba(255,255,255,0.14) !important;
    border-radius: 10px !important;
    box-shadow: rgba(0,0,0,0.36) 0 8px 28px !important;
    overflow: hidden !important;
}
[data-baseweb="popover"] li[role="option"],
[data-baseweb="popover"] [role="option"] {
    color: #9ab8d4 !important;
    background: transparent !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    font-size: 13px !important;
    padding: 10px 16px !important;
    transition: background 100ms ease !important;
}
[data-baseweb="popover"] li[role="option"]:hover {
    background: rgba(255,255,255,0.09) !important;
    color: #ffffff !important;
}
[data-baseweb="popover"] li[role="option"][aria-selected="true"] {
    background: rgba(255,255,255,0.13) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}

[data-testid="stSidebar"] hr,
[data-testid="stSidebar"] [data-testid="stDecoration"] {
    border-color: rgba(255,255,255,0.10) !important;
}

/* ── Header / Toolbar ── */
[data-testid="stHeader"] {
    background: rgba(255,255,255,0.90) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border-bottom: 1px solid rgba(0,0,0,0.07) !important;
    box-shadow: rgba(0,0,0,0.04) 0 1px 0 !important;
    z-index: 999 !important;
}
[data-testid="stToolbar"] {
    padding-right: 14px !important;
}
[data-testid="stToolbarActions"] {
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
    padding: 0 !important;
}
/* Deploy button */
[data-testid="stAppDeployButton"] button {
    background: #1a2b4a !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    padding: 0 14px !important;
    height: 32px !important;
    cursor: pointer !important;
    transition: background 130ms ease, box-shadow 130ms ease !important;
    box-shadow: rgba(26,43,74,0.22) 0 1px 4px, rgba(26,43,74,0.10) 0 0 0 1px !important;
}
[data-testid="stAppDeployButton"] button:hover {
    background: #0f1c30 !important;
    box-shadow: rgba(26,43,74,0.35) 0 2px 8px, rgba(26,43,74,0.15) 0 0 0 1px !important;
}
[data-testid="stAppDeployButton"] button:active {
    background: #08111e !important;
    transform: translateY(1px) !important;
}
/* Main menu ⋮ button */
[data-testid="stMainMenuButton"] > button {
    background: transparent !important;
    border: 1px solid #e0e0e0 !important;
    border-radius: 8px !important;
    color: #6a6a6a !important;
    width: 32px !important;
    height: 32px !important;
    padding: 0 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: all 130ms ease !important;
    box-shadow: rgba(0,0,0,0.04) 0 1px 2px !important;
}
[data-testid="stMainMenuButton"] > button:hover {
    background: #f4f6f8 !important;
    border-color: #bbbbbb !important;
    color: #1a1a1a !important;
    box-shadow: rgba(0,0,0,0.08) 0 1px 4px !important;
}
[data-testid="stMainMenuButton"] > button:active {
    transform: scale(0.96) !important;
}
/* Running spinner */
[data-testid="stStatusWidget"] {
    color: #6a6a6a !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 12px !important;
}

/* ── Plotly chart cards ── */
[data-testid="stPlotlyChart"] {
    background: #ffffff;
    border: 1px solid #e8eaed;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: rgba(0,0,0,.02) 0 0 0 1px, rgba(0,0,0,.04) 0 2px 6px 0, rgba(0,0,0,.06) 0 4px 10px 0;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid #e8eaed;
    background: transparent;
}
.stTabs [data-baseweb="tab"] {
    font-size: 13px;
    font-weight: 500;
    color: #929292;
    padding: 10px 20px;
    border-radius: 0;
    background: transparent;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    letter-spacing: 0.01em;
    transition: color 120ms ease;
}
.stTabs [data-baseweb="tab"]:hover { color: #1a2b4a; }
.stTabs [aria-selected="true"] {
    color: #1a2b4a !important;
    font-weight: 600 !important;
    border-bottom-color: #1a2b4a !important;
    background: transparent !important;
}
/* Fix: Streamlit uses tab-highlight div for the animated underline — override red default */
.stTabs [data-baseweb="tab-highlight"] {
    background-color: #1a2b4a !important;
    height: 2px !important;
}
.stTabs [data-baseweb="tab-panel"] { padding: 20px 0 0 0; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] table { font-size: 13px; color: #3f3f3f; }
[data-testid="stDataFrame"] thead th {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.05em; color: #6a6a6a; background: #f7f7f7;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    border: 1px solid #e8eaed !important;
    border-radius: 14px !important;
    background: #ffffff !important;
    box-shadow: rgba(0,0,0,.02) 0 0 0 1px, rgba(0,0,0,.04) 0 2px 6px 0, rgba(0,0,0,.08) 0 4px 8px 0 !important;
}
[data-testid="stExpander"] summary {
    font-size: 13px;
    font-weight: 600;
    color: #3f3f3f;
    padding: 14px 18px !important;
}
[data-testid="stExpander"] summary:hover { color: #1a2b4a; }

/* ── Number inputs in main content area (light theme) ── */
[data-testid="stMain"] [data-testid="stNumberInputContainer"] {
    display: flex !important;
    align-items: stretch !important;
    background: #ffffff !important;
    border: 1.5px solid #e0e4ea !important;
    border-radius: 10px !important;
    height: 44px !important;
    overflow: hidden !important;
    gap: 0 !important;
    transition: border-color 130ms ease, box-shadow 130ms ease !important;
}
[data-testid="stMain"] [data-testid="stNumberInputContainer"]:focus-within {
    border-color: #1a2b4a !important;
    box-shadow: 0 0 0 3px rgba(26,43,74,0.08) !important;
}
[data-testid="stMain"] [data-testid="stNumberInputContainer"] > div {
    background: transparent !important;
    border: none !important;
    display: contents !important;
}
[data-testid="stMain"] [data-testid="stNumberInputContainer"] div[data-baseweb="base-input"] {
    background: #ffffff !important;
    color-scheme: light !important;
}
[data-testid="stMain"] [data-testid="stNumberInputField"] {
    flex: 1 !important;
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: #1a1a1a !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    padding: 0 12px !important;
    height: 100% !important;
    box-shadow: none !important;
    outline: none !important;
}
[data-testid="stMain"] [data-testid="stNumberInputStepDown"],
[data-testid="stMain"] [data-testid="stNumberInputStepUp"] {
    background: #f5f7fb !important;
    border: none !important;
    border-radius: 0 !important;
    color: #8090a0 !important;
    width: 36px !important;
    min-width: 36px !important;
    height: 100% !important;
    font-size: 14px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: all 110ms ease !important;
    cursor: pointer !important;
}
[data-testid="stMain"] [data-testid="stNumberInputStepDown"] {
    border-left: 1.5px solid #e0e4ea !important;
    border-right: 1px solid #e8eaed !important;
}
[data-testid="stMain"] [data-testid="stNumberInputStepUp"] {
    border-left: 1px solid #e8eaed !important;
}
[data-testid="stMain"] [data-testid="stNumberInputStepDown"]:hover,
[data-testid="stMain"] [data-testid="stNumberInputStepUp"]:hover {
    background: #eaeff8 !important;
    color: #1a2b4a !important;
}
[data-testid="stMain"] [data-testid="stNumberInputStepDown"]:active,
[data-testid="stMain"] [data-testid="stNumberInputStepUp"]:active {
    background: #dce4f4 !important;
}
/* Label above input */
[data-testid="stMain"] .stNumberInput label {
    color: #555e6d !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em !important;
    text-transform: none !important;
    margin-bottom: 4px !important;
}

/* ── Alert boxes ── */
[data-testid="stAlert"] { border-radius: 14px; }

/* ── Scrollbars ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #f2f2f2; }
::-webkit-scrollbar-thumb { background: #dddddd; border-radius: 3px; }

/* ── Page header ── */
.page-header { margin-bottom: 24px; }
.page-header .micro-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: #6a6a6a; margin-bottom: 4px;
}
.page-header h1 {
    font-size: 22px; font-weight: 700; letter-spacing: -0.02em;
    color: #1a1a1a; margin: 0 0 4px 0;
}
.page-header .subtitle { font-size: 13px; color: #6a6a6a; margin: 0; }

/* ── Chart headers ── */
.chart-header { margin-bottom: 8px; }
.chart-header .chart-title { font-size:14px; font-weight:600; color:#1a1a1a; margin-bottom:1px; }
.chart-header .chart-subtitle { font-size:11px; color:#6a6a6a; }

/* ══════════════════════════════════════════════════════
   COMPREHENSIVE COLOR SYSTEM REFINEMENT
   ══════════════════════════════════════════════════════ */

/* ── Fix: tab highlight bar was red (#ff4b4b Streamlit default) → navy ── */
[data-baseweb="tab-highlight"] {
    background-color: #1a2b4a !important;
    height: 2px !important;
}

/* ── Nav separator — aggressive remove ── */
[data-testid="stSidebarNavSeparator"] {
    display: none !important;
    height: 0 !important;
    overflow: hidden !important;
}

/* Nav subtitle / active colors now fully handled in the nav section above (p only) */

/* ── KPI card hover lift ── */
[data-testid="stHorizontalBlock"] [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stColumn"] [data-testid="stMarkdown"] > div > div[style*="border-radius:14px"],
[data-testid="stColumn"] [data-testid="stMarkdown"] > div > div[style*="border-top:3px"] {
    transition: transform 150ms ease, box-shadow 150ms ease !important;
}
[data-testid="stColumn"] [data-testid="stMarkdown"] > div > div[style*="border-top:3px"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: rgba(0,0,0,.03) 0 0 0 1px, rgba(0,0,0,.07) 0 4px 14px, rgba(0,0,0,.10) 0 8px 20px !important;
}

/* ── Recommendation cards hover ── */
[data-testid="stMarkdown"] div[style*="border-radius:14px"][style*="margin-bottom:12px"] {
    transition: transform 140ms ease, box-shadow 140ms ease, border-color 140ms ease !important;
    cursor: default;
}
[data-testid="stMarkdown"] div[style*="border-radius:14px"][style*="margin-bottom:12px"]:hover {
    transform: translateY(-1px) !important;
    border-color: #c4cad4 !important;
    box-shadow: rgba(0,0,0,.04) 0 0 0 1px, rgba(0,0,0,.08) 0 4px 14px !important;
}

/* ── Radio buttons → pill-chips (Faults MCS axis filter) ── */
.stRadio > div { gap: 5px !important; }
.stRadio [data-baseweb="radio"] {
    border: 1.5px solid #dde2ea !important;
    border-radius: 9999px !important;
    padding: 5px 16px !important;
    background: #f5f7fb !important;
    cursor: pointer !important;
    margin: 0 !important;
    transition: all 120ms ease !important;
}
.stRadio [data-baseweb="radio"] > div:first-child { display: none !important; }
.stRadio [data-baseweb="radio"] > div:last-child {
    color: #5a6a7a !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
}
/* Active state: checked input lives inside the div — use :has() */
.stRadio [data-baseweb="radio"]:has(input[type="radio"]:checked) {
    background: #1a2b4a !important;
    border-color: #1a2b4a !important;
}
.stRadio [data-baseweb="radio"]:has(input[type="radio"]:checked) > div:last-child {
    color: #ffffff !important;
}
.stRadio [data-baseweb="radio"]:hover { border-color: #b0bece !important; background: #eceff6 !important; }
.stRadio [data-baseweb="radio"]:has(input[type="radio"]:checked):hover {
    background: #0f1c30 !important;
    border-color: #0f1c30 !important;
}

/* ── Page header micro-label — more visible ── */
.page-header .micro-label { color: #888888 !important; letter-spacing: 0.10em !important; }
.page-header h1 { color: #111111 !important; font-size: 24px !important; font-weight: 700 !important; }
.page-header .subtitle { color: #777777 !important; }

/* ── Content section labels — stronger hierarchy ── */
[data-testid="stMarkdown"] div[style*="font-size:11px"][style*="text-transform:uppercase"],
[data-testid="stMarkdown"] div[style*="font-size: 11px"][style*="text-transform: uppercase"] {
    color: #505050 !important;
    letter-spacing: 0.09em !important;
}

/* ── Callout boxes — warmer surface distinct from plain white ── */
[data-testid="stMarkdown"] div[style*="background:#f7f7f7"] {
    background: #f3f6fb !important;
    border-color: #dde3ee !important;
}

/* ── Scrollbars — blue-tinted ── */
::-webkit-scrollbar-track { background: #edf0f6 !important; }
::-webkit-scrollbar-thumb { background: #c0c9da !important; }
::-webkit-scrollbar-thumb:hover { background: #a4b0c6 !important; }

/* ── DataTable ── */
[data-testid="stDataFrame"] thead th { background: #f2f5fb !important; color: #505060 !important; }
[data-testid="stDataFrame"] tbody tr:hover td { background: #f7f9fd !important; }

/* ── Streamlit divider ── */
[data-testid="stDivider"] { border-color: #e4e8f0 !important; }

/* ── Plotly chart cards — faint blue border tint ── */
[data-testid="stPlotlyChart"] { border-color: #e2e8f0 !important; }

/* ── Alert/status boxes ── */
[data-testid="stAlert"] { border-radius: 12px !important; font-size: 13px !important; }

/* ── Expander hover ── */
[data-testid="stExpander"] summary:hover { color: #1a2b4a !important; background: #f7f9fd !important; }

/* ── Equal-height columns: all stColumns in a row stretch to tallest ── */
[data-testid="stHorizontalBlock"] { align-items: stretch !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    display: flex !important; flex-direction: column !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div > [data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] {
    flex: 1 !important; display: flex !important; flex-direction: column !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] > [data-testid="stMarkdown"],
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] > [data-testid="stMarkdown"] > div,
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > div > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] > [data-testid="stMarkdown"] > div > div {
    flex: 1 !important; height: 100% !important;
}
</style>
"""


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(_build_nav_icon_css(), unsafe_allow_html=True)


# ── Config ────────────────────────────────────────────────────────────────────

@st.cache_data
def load_config():
    try:
        base_dir = Path(__file__).parent
        config_path = base_dir / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Configuration loading error: {e}")
        return None


# ── Data helpers ──────────────────────────────────────────────────────────────

def _to_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def make_arrow_safe_display_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    safe = df.copy()
    for col in safe.columns:
        if safe[col].dtype == "object":
            safe[col] = safe[col].map(_to_text).astype("string")
    return safe


@st.cache_data(show_spinner=False)
def process_nc_data(content: str, config_snapshot: dict, machine_id: str):
    from src.engine import GCodeEngine
    from transformation import DigitalTwinTransformer

    config_snapshot = dict(config_snapshot)
    config_snapshot["active_machine_id"] = machine_id

    engine = GCodeEngine(config_snapshot)
    transformer = DigitalTwinTransformer(config_snapshot)

    source_lines = []
    flat_logs = []

    for i, line in enumerate(content.splitlines(), start=1):
        source_lines.append({"line_number": i, "raw_line": line})
        cmd = engine.parse_line(line)
        block_dict = {
            "tokens": cmd if isinstance(cmd, dict) else {},
            "line_number": i,
            "raw_line": line,
        }

        block_start_time = float(transformer.state.get("current_time", 0.0))
        segments = transformer.apply_block(block_dict)
        block_end_time = float(transformer.state.get("current_time", 0.0))

        for seg in segments:
            seg_start_time = float(seg.get("start_time", block_start_time))
            seg_end_time = float(seg.get("end_time", block_end_time))

            if seg.get("type") == "motion" and "trajectory_slide" in seg:
                for pt in seg["trajectory_slide"]:
                    flat_logs.append({
                        "time": float(pt.get("t", seg_end_time)),
                        "axis_x": pt.get("X"), "axis_y": pt.get("Y"), "axis_z": pt.get("Z"),
                        "tip_x": pt.get("tip_x"), "tip_y": pt.get("tip_y"), "tip_z": pt.get("tip_z"),
                        "line_number": pt.get("line_number", i),
                        "raw_line": pt.get("raw_line", line),
                        "motion_mode": pt.get("motion_mode", seg.get("motion_mode")),
                        "is_air_time": pt.get("is_air_time", seg.get("is_air_time", False)),
                        "event_type": "", "event_duration_s": 0.0, "event_duration_source": "",
                        "previous_tool_id": None, "next_tool_id": None,
                        "station_count": None, "tool_station_steps": None,
                        "spindle_rpm_before": None, "spindle_rpm_target": None,
                        "feedrate": float(pt.get("feedrate", transformer.state.get("feedrate", 0))),
                        "rpm": float(pt.get("rpm", transformer.state.get("rpm", 0))),
                        "tool_id": str(pt.get("tool_id", transformer.state.get("active_tool_id", "None"))),
                        "H_length": float(transformer.state.get("H_length", 0.0)),
                        "H_status": pt.get("H_status", transformer.state.get("H_status", "")),
                        "tool_length_warning": pt.get("tool_length_warning", transformer.state.get("tool_length_warning", "")),
                        "ot_x": bool(pt.get("ot_x", False)), "ot_y": bool(pt.get("ot_y", False)), "ot_z": bool(pt.get("ot_z", False)),
                        "ot_amount_x": float(pt.get("ot_amount_x", 0.0)),
                        "ot_amount_y": float(pt.get("ot_amount_y", 0.0)),
                        "ot_amount_z": float(pt.get("ot_amount_z", 0.0)),
                    })
            else:
                event_type = seg.get("event_type", "UNKNOWN")
                event_duration = float(seg.get("duration", max(seg_end_time - seg_start_time, 0.0)))
                event_times = [seg_start_time, seg_end_time] if seg_end_time > seg_start_time else [seg_start_time]
                slide_pos = transformer.compute_slide_g53()
                tip_pos = transformer.compute_tip_g53()

                for idx_e, event_time in enumerate(event_times):
                    is_end = idx_e == len(event_times) - 1
                    flat_logs.append({
                        "time": float(event_time),
                        "axis_x": slide_pos["X"], "axis_y": slide_pos["Y"], "axis_z": slide_pos["Z"],
                        "tip_x": tip_pos["X"], "tip_y": tip_pos["Y"], "tip_z": tip_pos["Z"],
                        "line_number": i, "raw_line": line,
                        "motion_mode": "event", "is_air_time": True,
                        "event_type": event_type,
                        "event_duration_s": event_duration if is_end else 0.0,
                        "event_duration_source": seg.get("event_duration_source", ""),
                        "previous_tool_id": seg.get("previous_tool_id"),
                        "next_tool_id": seg.get("next_tool_id"),
                        "station_count": seg.get("station_count"),
                        "tool_station_steps": seg.get("tool_station_steps"),
                        "spindle_rpm_before": seg.get("spindle_rpm_before"),
                        "spindle_rpm_target": seg.get("spindle_rpm_target"),
                        "feedrate": float(transformer.state.get("feedrate", 0)),
                        "rpm": float(transformer.state.get("actual_spindle_rpm", transformer.state.get("rpm", 0))),
                        "tool_id": str(transformer.state.get("active_tool_id", "None")),
                        "H_length": float(transformer.state.get("H_length", 0.0)),
                        "H_status": transformer.state.get("H_status", ""),
                        "tool_length_warning": transformer.state.get("tool_length_warning", ""),
                        "ot_x": False, "ot_y": False, "ot_z": False,
                        "ot_amount_x": 0.0, "ot_amount_y": 0.0, "ot_amount_z": 0.0,
                    })

    df_source = pd.DataFrame(source_lines)
    df = pd.DataFrame(flat_logs)

    if not df.empty:
        df = df.sort_values(["time", "line_number"]).reset_index(drop=True)
        for col in ["axis_x", "axis_y", "axis_z"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df[["axis_x", "axis_y", "axis_z"]] = df[["axis_x", "axis_y", "axis_z"]].ffill().bfill()
        df[["feedrate", "rpm"]] = df[["feedrate", "rpm"]].fillna(0)
        for col, dflt in {
            "event_type": "", "event_duration_s": 0.0, "event_duration_source": "",
            "previous_tool_id": "", "next_tool_id": "", "station_count": "",
            "tool_station_steps": "", "spindle_rpm_before": "", "spindle_rpm_target": "",
        }.items():
            if col not in df.columns:
                df[col] = dflt
            else:
                df[col] = df[col].fillna(dflt)

    return df_source, df


# ── Sidebar ───────────────────────────────────────────────────────────────────

_GEAR_SVG = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
    'stroke="#1a2b4a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="3"/>'
    '<path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>'
    '</svg>'
)

_FILE_SVG = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
    'stroke="#9fb3cf" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
    'style="flex:0 0 18px">'
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
    '<path d="M14 2v6h6"/>'
    '</svg>'
)


def render_sidebar(config: dict):
    """Render sidebar controls and return (nc_files, selected_machine, cost_cfg, active_machine_cfg).

    Behavior:
    - Keeps uploaded NC files in session_state so they remain available across pages.
    - Allows uploading several NC files at once and adding more files later.
    - Keeps one global machine selection across Dashboard / Cycle Time / Faults / Costing / Optimize.
    """
    with st.sidebar:
        import html as _html

        # ── NC Program ────────────────────────────────────────────────────────
        st.markdown(
            '<div style="padding:12px 20px 0;">'
            '<div style="font-size:9px;font-weight:700;letter-spacing:0.14em;'
            'text-transform:uppercase;color:#3d567a;margin-bottom:10px;">NC Program</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        def _file_key(name: str, data: bytes) -> tuple:
            # enough to prevent accidental duplicate append on Streamlit reruns
            return (str(name), len(data), data[:64], data[-64:] if len(data) >= 64 else data)

        def _cache_uploaded_files(uploaded_files, append: bool = False) -> bool:
            if not uploaded_files:
                return False

            current_cache = list(st.session_state.get(_NC_CACHE_KEY, [])) if append else []
            existing_keys = {
                _file_key(item["name"], item["data"])
                for item in current_cache
            }

            changed = False
            for f in uploaded_files:
                data = f.getvalue()
                key = _file_key(f.name, data)
                if key in existing_keys:
                    continue
                current_cache.append({"name": f.name, "data": data})
                existing_keys.add(key)
                changed = True

            if changed:
                st.session_state[_NC_CACHE_KEY] = current_cache

            return changed

        # If no cache exists, show the main multi-file uploader.
        if not st.session_state.get(_NC_CACHE_KEY):
            nc_files_raw = st.file_uploader(
                "NC Program",
                type=["nc", "txt", "tap", "cnc", "gcode"],
                accept_multiple_files=True,
                key="sb_nc_files",
                label_visibility="collapsed",
            )

            if _cache_uploaded_files(nc_files_raw, append=False):
                st.rerun()

        # If files already exist, show all cards and allow adding more files.
        if st.session_state.get(_NC_CACHE_KEY):
            nc_files = [
                _CachedFile(c["name"], c["data"])
                for c in st.session_state[_NC_CACHE_KEY]
            ]

            # Display every uploaded file, not only the first one.
            for idx, c in enumerate(st.session_state[_NC_CACHE_KEY], start=1):
                raw_txt = c["data"].decode("utf-8", errors="ignore")
                block_count = sum(
                    1 for ln in raw_txt.splitlines()
                    if ln.strip()
                    and not ln.strip().startswith(";")
                    and not ln.strip().startswith("(")
                )
                size_kb = len(c["data"]) / 1024
                fname_safe = _html.escape(c["name"])

                st.markdown(
                    f'<div style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);'
                    f'border-radius:10px;padding:10px 12px;display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
                    f'{_FILE_SVG}'
                    f'<div style="flex:1;min-width:0;">'
                    f'<div style="color:#ffffff;font-size:13px;font-weight:600;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{idx}. {fname_safe}</div>'
                    f'<div style="color:#7a94b0;font-size:11px;">{block_count:,} blocks · {size_kb:.0f} KB</div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            # Add more files later without clearing existing cached files.
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
            more_files = st.file_uploader(
                "Add NC programs",
                type=["nc", "txt", "tap", "cnc", "gcode"],
                accept_multiple_files=True,
                key="sb_nc_files_append",
                label_visibility="collapsed",
            )

            if _cache_uploaded_files(more_files, append=True):
                st.rerun()

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            if st.button("↑ Change / clear NC files", key="sb_change_file"):
                st.session_state.pop(_NC_CACHE_KEY, None)
                st.session_state.pop("sb_nc_files", None)
                st.session_state.pop("sb_nc_files_append", None)
                st.rerun()
        else:
            nc_files = []

        # ── Machine ───────────────────────────────────────────────────────────
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        _sidebar_section("Machine")

        machine_ids = list(config["machines"].keys())
        global_machine_key = "global_machine_id"

        if global_machine_key not in st.session_state:
            default_machine = (
                st.session_state.get("sb_machine")
                or config.get("active_machine_id", machine_ids[0])
            )
            if default_machine not in machine_ids:
                default_machine = machine_ids[0]
            st.session_state[global_machine_key] = default_machine

        # Make sure the remembered value is still valid.
        if st.session_state[global_machine_key] not in machine_ids:
            st.session_state[global_machine_key] = machine_ids[0]

        selected_machine = st.selectbox(
            "Machine",
            machine_ids,
            index=machine_ids.index(st.session_state[global_machine_key]),
            key=global_machine_key,
            label_visibility="collapsed",
        )

        # Backward-compatible alias for pages that still read sb_machine.
        st.session_state["sb_machine"] = selected_machine

    config["active_machine_id"] = selected_machine
    active_machine_cfg = config["machines"][selected_machine]
    return nc_files, selected_machine, get_cost_cfg(), active_machine_cfg

def _sidebar_section(label: str):
    st.markdown(
        f'<div style="font-size:9px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.14em;color:#3d567a;margin-bottom:8px;">{label}</div>',
        unsafe_allow_html=True,
    )


def render_sidebar_summary(total_time: float, efficiency: float, fault_count: int):
    """Sidebar stats card shown after a file is parsed."""
    mins = int(total_time // 60)
    secs = total_time % 60
    time_str = f"{mins}:{secs:04.1f} min" if mins > 0 else f"{total_time:.1f} s"

    is_fault = fault_count > 0

    if is_fault:
        status_bg    = "rgba(226,72,59,0.18)"
        status_border= "rgba(226,72,59,0.30)"
        status_dot   = "#e2483b"
        status_text  = "#f87c74"
        status_label = f"Fault run"
        badge = (
            f'<span style="background:#e2483b;color:#fff;border-radius:9999px;'
            f'font-size:10px;font-weight:700;padding:1px 7px;margin-left:5px;">'
            f'{fault_count}</span>'
        )
        fault_val = (
            f'<span style="background:#e2483b;color:#fff;border-radius:9999px;'
            f'font-size:11px;font-weight:700;padding:1px 9px;">{fault_count}</span>'
        )
    else:
        status_bg    = "rgba(26,138,80,0.15)"
        status_border= "rgba(26,138,80,0.28)"
        status_dot   = "#1a8a50"
        status_text  = "#3fc87a"
        status_label = "Safe run"
        badge        = ""
        fault_val    = '<span style="font-size:13px;font-weight:600;color:#3fc87a;">None</span>'

    html = (
        # Section label — matches NC PROGRAM / MACHINE label style exactly
        '<div>'
        '<div style="font-size:9px;font-weight:700;text-transform:uppercase;'
        'letter-spacing:0.14em;color:#3d567a;margin-bottom:10px;">Simulation Run</div>'

        # Status row — dot + label + badge, no pill background, flat
        f'<div style="display:flex;align-items:center;gap:7px;margin-bottom:12px;">'
        f'<span style="width:7px;height:7px;border-radius:50%;background:{status_dot};'
        f'flex:0 0 7px;box-shadow:0 0 0 2px {status_border};"></span>'
        f'<span style="font-size:13px;font-weight:600;color:{status_text};">{status_label}</span>'
        f'{badge}'
        '</div>'

        # Stats — full-width, no extra card box, consistent with sidebar edge padding
        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'padding:8px 0;border-top:1px solid rgba(255,255,255,0.07);">'
        '<span style="font-size:12px;color:#6a88a8;">Cycle time</span>'
        f'<span style="font-size:13px;font-weight:600;color:#dce8f4;">{time_str}</span>'
        '</div>'
        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'padding:8px 0;border-top:1px solid rgba(255,255,255,0.07);">'
        '<span style="font-size:12px;color:#6a88a8;">Efficiency</span>'
        f'<span style="font-size:13px;font-weight:600;color:#dce8f4;">{efficiency:.1f}%</span>'
        '</div>'
        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'padding:8px 0;border-top:1px solid rgba(255,255,255,0.07);">'
        '<span style="font-size:12px;color:#6a88a8;">Overtravel</span>'
        f'{fault_val}'
        '</div>'
        '</div>'
    )
    st.sidebar.markdown(html, unsafe_allow_html=True)


# ── Page-level UI components ──────────────────────────────────────────────────

def page_header(title: str, subtitle: str = "", label: str = ""):
    parts = []
    if label:
        parts.append(f'<div class="micro-label">{label}</div>')
    parts.append(f'<h1>{title}</h1>')
    if subtitle:
        parts.append(f'<p class="subtitle">{subtitle}</p>')
    st.markdown(f'<div class="page-header">{"".join(parts)}</div>', unsafe_allow_html=True)


def _label(text: str):
    st.markdown(
        f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.07em;color:{MUTED};margin-bottom:6px;margin-top:4px;">{text}</div>',
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, unit: str = "", delta: str = "", accent: str = PRIMARY):
    # Always render delta placeholder so all cards have the same height
    delta_html = (
        f'<div style="font-size:13px;color:{MUTED};margin-top:4px;">{delta}</div>'
        if delta else
        f'<div style="font-size:13px;margin-top:4px;visibility:hidden;">—</div>'
    )
    st.markdown(f"""
    <div style="
        background:{CANVAS};
        border-radius:14px;
        border-top:3px solid {accent};
        box-shadow:{SHADOW};
        padding:16px 20px;
        height:100%;
        min-height:110px;
        box-sizing:border-box;
    ">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.07em;color:{MUTED};margin-bottom:8px;">{label}</div>
        <div style="font-size:26px;font-weight:700;color:{INK};letter-spacing:-0.03em;line-height:1.1;">
            {value}
            <span style="font-size:14px;font-weight:500;color:{BODY};">{unit}</span>
        </div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


def status_banner(is_safe: bool, message: str):
    if is_safe:
        bg, border, color = SUCCESS_LIGHT, SUCCESS_BORDER, SUCCESS
        icon = "●"
    else:
        bg, border, color = DANGER_LIGHT, DANGER_BORDER, DANGER
        icon = "⚠"
    st.markdown(f"""
    <div style="
        background:{bg};border:1px solid {border};border-radius:14px;
        padding:14px 20px;margin-bottom:20px;
        box-shadow:{SHADOW};
        font-size:14px;font-weight:700;color:{color};
        display:flex;align-items:center;gap:10px;
    ">
        <span style="font-size:18px;">{icon}</span>
        <span>{message}</span>
    </div>
    """, unsafe_allow_html=True)


def callout_box(label: str, value: str, unit: str = ""):
    st.markdown(f"""
    <div style="
        background:{SURFACE_SOFT};border:1px solid {HAIRLINE};border-radius:14px;
        padding:16px 20px;
        box-shadow:{SHADOW};
    ">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.07em;color:{MUTED};margin-bottom:6px;">{label}</div>
        <div style="font-size:24px;font-weight:700;color:{INK};letter-spacing:-0.02em;">
            {value}
            <span style="font-size:14px;font-weight:500;color:{BODY};">{unit}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def section_label(text: str, margin_top: int = 20):
    st.markdown(
        f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.07em;color:{MUTED};margin-top:{margin_top}px;margin-bottom:10px;">'
        f'{text}</div>',
        unsafe_allow_html=True,
    )


def progress_bar_row(label: str, seconds: float, pct: float, color: str, total_seconds: float = None, right_text: str = None):
    width = min(max(pct, 0), 100)
    right = right_text if right_text is not None else f"{seconds:.1f} s · {pct:.1f}%"
    st.markdown(f"""
    <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;
                    font-size:13px;color:{BODY};margin-bottom:5px;">
            <span>{label}</span>
            <span style="color:{MUTED};font-size:12px;">{right}</span>
        </div>
        <div style="background:{SURFACE_STRONG};border-radius:9999px;height:6px;">
            <div style="width:{width}%;background:{color};border-radius:9999px;height:6px;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)


BADGE_STYLES = {
    "High":       (DANGER_LIGHT,   DANGER),
    "Medium":     (WARNING_LIGHT,  WARNING),
    "Low/Medium": (WARNING_LIGHT,  WARNING),
    "Low":        (SURFACE_STRONG, MUTED),
    "Monitoring": (SURFACE_STRONG, MUTED),
}

def priority_badge(priority: str) -> str:
    bg, color = BADGE_STYLES.get(priority, (SURFACE_STRONG, MUTED))
    return (
        f'<span style="background:{bg};color:{color};border-radius:9999px;'
        f'padding:2px 10px;font-size:10px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:0.05em;">{priority}</span>'
    )


_STATUS_BADGE_STYLES = {
    "FAIL":     (DANGER_LIGHT,   DANGER),
    "CRITICAL": (WARNING_LIGHT,  WARNING),
    "WARNING":  (WARNING_LIGHT,  WARNING),
    "SAFE":     (SUCCESS_LIGHT,  SUCCESS),
    "NOT SET":  (SURFACE_STRONG, MUTED),
}

def status_badge(status: str) -> str:
    bg, color = _STATUS_BADGE_STYLES.get(status, (SURFACE_STRONG, MUTED))
    return (
        f'<span style="background:{bg};color:{color};border-radius:9999px;'
        f'padding:2px 10px;font-size:10px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:0.05em;">{status}</span>'
    )


def recommendation_card(priority: str, title: str, saving_str: str, detail: str = ""):
    badge = priority_badge(priority)
    saving_html = f'<div style="font-size:12px;color:{MUTED};margin-top:4px;">{saving_str}</div>' if saving_str else ""
    detail_html = f'<div style="font-size:13px;color:{MUTED};margin-top:6px;">{detail}</div>' if detail else ""
    st.markdown(f"""
    <div style="
        background:{CANVAS};border:1px solid {HAIRLINE};border-radius:14px;
        padding:16px 20px;margin-bottom:12px;
        box-shadow:{SHADOW};
    ">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
            {badge}
            <span style="font-size:14px;font-weight:600;color:{INK};">{title}</span>
        </div>
        {saving_html}
        {detail_html}
    </div>
    """, unsafe_allow_html=True)


def empty_state(message: str = "Upload an NC file in the sidebar to get started."):
    st.markdown(f"""
    <div style="text-align:center;color:{MUTED_SOFT};font-size:14px;padding:64px 0;">
        <div style="font-size:40px;margin-bottom:16px;">📂</div>
        <div>{message}</div>
    </div>
    """, unsafe_allow_html=True)


# ── Plotly helpers ────────────────────────────────────────────────────────────

def apply_plotly_defaults(fig, title: str = "", height: int = 280, margin=None):
    import plotly.graph_objects as go
    # More headroom when a title is present
    t_margin = 36 if title else 10
    m = margin or dict(l=8, r=8, t=t_margin, b=8)
    fig.update_layout(
        template="plotly_white",
        font=CHART_FONT,
        title=dict(
            text=title,
            font=dict(size=13, color="#111111", weight=700, family="Inter, -apple-system, sans-serif"),
            x=0, xanchor="left",
            pad=dict(l=2, b=10),   # breathing room below title before plot area
        ),
        height=height,
        margin=m,
        paper_bgcolor=CANVAS,
        plot_bgcolor=CANVAS,
        hoverlabel=dict(bgcolor=CANVAS, bordercolor=HAIRLINE, font=dict(size=11, family="Inter, -apple-system, sans-serif")),
        hovermode="x unified",
    )
    _axis_style = dict(
        gridcolor=HAIRLINE_SOFT,
        zerolinecolor=HAIRLINE,
        tickfont=dict(size=10, color="#333333", family="Inter, -apple-system, sans-serif"),
        title_font=dict(size=11, color="#111111", family="Inter, -apple-system, sans-serif"),
    )
    fig.update_xaxes(**_axis_style)
    fig.update_yaxes(**_axis_style)


def format_cycle_time(seconds: float) -> tuple[str, str]:
    if seconds >= 60:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}:{secs:04.1f}", "min:s"
    return f"{seconds:.1f}", "s"

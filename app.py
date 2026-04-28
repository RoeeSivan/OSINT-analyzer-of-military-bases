"""
OSINT GEOINT Analyzer — Streamlit GUI.

Reads data/data.json (cumulative pipeline output) and renders a per-base
intelligence dashboard with screenshots, Moondream detections, the 8-analyst
journey, and the commander synthesis. Group/filter by country.

Run:
    source venv/bin/activate
    streamlit run app.py
"""

import html
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import altair as alt
import pydeck as pdk
import streamlit as st
from streamlit_image_comparison import image_comparison

DATA_PATH = "data/data.json"
SCREENSHOT_DIR = "screenshots"

CONFIDENCE_COLORS = {"high": "#8b1a1a", "medium": "#a07a2c", "low": "#6b6357"}
ACTION_COLORS = {
    "zoom-in": "#8b1a1a",
    "zoom-out": "#2c3a4a",
    "move-left": "#a07a2c",
    "move-right": "#a07a2c",
    "finish": "#3d342c",
}
COUNTRY_FLAGS = {
    "Egypt": "🇪🇬", "Korea": "🇰🇷", "Russia": "🇷🇺", "China": "🇨🇳",
    "Iran": "🇮🇷", "Syria": "🇸🇾", "USA": "🇺🇸", "Israel": "🇮🇱",
}


# ---------- data loading ----------

@st.cache_data
def load_data(mtime: float):
    """Cached read of data.json. `mtime` arg invalidates cache when file changes."""
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- HTML helpers ----------

def pill(text: str, color: str, *, mono: bool = True) -> str:
    """Rendered as a rubber-stamp rectangle — declassified-document aesthetic."""
    font = "'Special Elite', monospace" if mono else "'EB Garamond', serif"
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:0;'
        f'background:transparent;color:{color};border:1.5px solid {color};'
        f'font-family:{font};font-size:0.8rem;font-weight:400;'
        f'letter-spacing:0.16em;text-transform:uppercase;margin:2px 4px 2px 0;">'
        f"{text}</span>"
    )


def confidence_pill(conf: str) -> str:
    return pill(conf or "unknown", CONFIDENCE_COLORS.get(conf, "#64748b"))


def action_pill(action: str) -> str:
    return pill(action, ACTION_COLORS.get(action, "#64748b"))


def detection_pills(detections: list) -> str:
    if not detections:
        return pill("no detections", "#64748b")
    counts = Counter(d["label"] for d in detections)
    return "".join(
        pill(f"{count}× {label}", "#06b6d4") for label, count in counts.most_common()
    )


def country_label(country: str) -> str:
    return f"{COUNTRY_FLAGS.get(country, '🏳️')} {country}"


def screenshot_path(filename: str | None) -> str | None:
    if not filename:
        return None
    p = os.path.join(SCREENSHOT_DIR, filename)
    return p if os.path.exists(p) else None


def pick_primary_screenshot(base: dict):
    """Best image to feature in the hero card. Prefer analyst-1 annotated → analyst-1 raw
    → any annotated → any raw. Returns (path, analyst_dict) or (None, None)."""
    analysts = base.get("analysts") or []
    if not analysts:
        return None, None
    a1 = analysts[0]
    p = screenshot_path(a1.get("annotated_screenshot_file")) or screenshot_path(a1.get("screenshot_file"))
    if p:
        return p, a1
    for a in analysts:
        if (p := screenshot_path(a.get("annotated_screenshot_file"))):
            return p, a
    for a in analysts:
        if (p := screenshot_path(a.get("screenshot_file"))):
            return p, a
    return None, None


# ---------- search helpers ----------

def base_haystack(base: dict) -> str:
    """All searchable text from a base entry, lower-cased and concatenated."""
    cmd = base["commander_report"]
    parts = [
        cmd.get("executive_summary", ""),
        cmd.get("facility_classification", ""),
        cmd.get("threat_assessment", ""),
        cmd.get("confidence", ""),
        base.get("country", ""),
        str(base.get("base_id", "")),
        " ".join(cmd.get("key_findings", [])),
        " ".join(cmd.get("recommended_next_steps", [])),
        " ".join(cmd.get("disagreements_or_uncertainties", [])),
    ]
    for a in base["analysts"]:
        ana = a.get("analysis", {})
        parts.append(ana.get("analysis", ""))
        parts.extend(ana.get("findings", []))
        parts.extend(ana.get("things_to_continue_analyzing", []))
        parts.extend(d.get("label", "") for d in a.get("moondream_detections", []))
    return " ".join(parts).lower()


def base_matches(base: dict, query: str) -> bool:
    return not query.strip() or query.strip().lower() in base_haystack(base)


def hl(text, query: str) -> str:
    """HTML-escape `text` and wrap query matches in a <mark> for highlighting."""
    if text is None:
        return ""
    safe = html.escape(str(text))
    q = (query or "").strip()
    if not q:
        return safe
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    return pattern.sub(
        lambda m: (
            f'<mark style="background:#f59e0b;color:#0b1220;padding:0 3px;'
            f'border-radius:2px;font-weight:700;">{m.group(0)}</mark>'
        ),
        safe,
    )


# ---------- page config + global CSS ----------

# ---------- session state ----------

if "selected_base_id" not in st.session_state:
    st.session_state.selected_base_id = None


st.set_page_config(
    page_title="OSINT // DOSSIER ARCHIVE",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Georgia:wght@400;700&display=swap');

:root {
  --paper:       #f4ecd8;
  --paper-deep:  #ebe1c3;
  --paper-edge:  #d4c8a4;
  --ink:         #1a1410;
  --ink-soft:    #3d342c;
  --ash:         #6b6357;
  --blood:       #8b1a1a;
  --blood-soft:  #b54545;
  --rust:        #a14a2c;
  --brass:       #a07a2c;
  --slate:       #2c3a4a;
  --olive:       #4a5024;
  --rule:        rgba(26, 20, 16, 0.18);
}

/* ========== BASE ========== */
html, body, .stApp {
  background:
    radial-gradient(ellipse 80% 60% at 50% -10%, rgba(139, 26, 26, 0.06) 0%, transparent 70%),
    radial-gradient(ellipse 60% 50% at 100% 100%, rgba(160, 122, 44, 0.05) 0%, transparent 60%),
    repeating-linear-gradient(180deg, transparent 0, transparent 38px, rgba(26, 20, 16, 0.025) 38px, rgba(26, 20, 16, 0.025) 39px),
    linear-gradient(180deg, var(--paper) 0%, var(--paper-deep) 100%) !important;
  background-attachment: fixed !important;
  color: var(--ink) !important;
}
/* Paper grain noise overlay across whole app */
.stApp::before {
  content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' seed='3'/><feColorMatrix values='0 0 0 0 0.10 0 0 0 0 0.08 0 0 0 0 0.06 0 0 0 0.4 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
  opacity: 0.32;
  mix-blend-mode: multiply;
}
/* Foxing — subtle aged-paper stains in corners */
.stApp::after {
  content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(circle 200px at 8% 95%, rgba(160, 122, 44, 0.10), transparent 60%),
    radial-gradient(circle 240px at 95% 4%, rgba(139, 26, 26, 0.06), transparent 60%);
}

/* All Streamlit body text → ink on paper */
.stApp, .stApp p, .stApp li, .stApp span, .stApp div,
.stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span,
[data-testid="stText"], [data-testid="stMarkdownContainer"] p {
  color: var(--ink);
  font-family: Georgia, 'Garamond', Georgia, serif;
}
.stMarkdown p { font-size: 1.05rem; line-height: 1.55; }

/* Streamlit headings */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
.stMarkdown h5, .stMarkdown h6, h1, h2, h3 {
  font-family: Georgia, serif;
  color: var(--ink) !important;
  font-weight: 700 !important;
  letter-spacing: -0.005em;
}

/* ========== HEADER MASTHEAD ========== */
.hero-title {
  font-family: Georgia, serif;
  font-weight: 900;
  font-size: 4rem;
  letter-spacing: -0.015em;
  line-height: 0.95;
  color: var(--ink);
  text-transform: none;
  border: none;
  padding: 0;
  margin: 0 0 6px 0;
  position: relative;
}
.hero-title::before {
  content: 'TOP SECRET // HUMINT // NOFORN';
  display: block;
  font-family: 'Courier New', monospace;
  font-size: 0.74rem;
  letter-spacing: 0.22em;
  color: var(--blood);
  margin-bottom: 18px;
  padding: 5px 12px;
  border-top: 2px solid var(--blood);
  border-bottom: 2px solid var(--blood);
  width: fit-content;
}
.hero-title::after {
  content: '';
  display: block;
  margin-top: 10px;
  height: 4px;
  background: linear-gradient(180deg, var(--ink) 0 1px, transparent 1px 3px, var(--ink) 3px 4px);
}
.hero-sub {
  font-family: 'Courier New', monospace;
  color: var(--ink-soft);
  font-size: 0.84rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin-bottom: 28px;
}

/* ========== CARDS — folded paper memos ========== */
.card {
  background: var(--paper-deep);
  border: 1px solid var(--paper-edge);
  border-left: 4px double var(--blood);
  border-radius: 0;
  padding: 26px 32px 24px 32px;
  margin: 14px 0 26px 0;
  position: relative;
  box-shadow:
    0 1px 0 rgba(255, 252, 240, 0.6) inset,
    0 8px 28px -18px rgba(26, 20, 16, 0.45),
    0 2px 4px -2px rgba(26, 20, 16, 0.18);
}
.card::before, .card::after {
  content: ''; position: absolute;
  width: 16px; height: 16px;
  border: 1px solid var(--ink); opacity: 0.5;
}
.card::before { top: 7px; left: 7px; border-right: 0; border-bottom: 0; }
.card::after  { bottom: 7px; right: 7px; border-left: 0; border-top: 0; }

/* ========== CLICKABLE CARDS ========== */
.clickable-card {
  transition: all 0.2s ease;
  display: block;
}
.clickable-card:hover .card {
  transform: translateY(-4px);
  box-shadow:
    0 1px 0 rgba(255, 252, 240, 0.6) inset,
    0 16px 36px -14px rgba(26, 20, 16, 0.55),
    0 2px 4px -2px rgba(26, 20, 16, 0.18) !important;
  border-left-color: var(--blood-soft);
}

/* ========== SECTION DIVIDERS ========== */
.section-title {
  font-family: Georgia, serif;
  font-weight: 700;
  font-size: 1.55rem;
  color: var(--ink);
  letter-spacing: 0.005em;
  margin: 40px 0 14px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--ink);
  text-transform: none;
  position: relative;
}
.section-title::after {
  content: ''; display: block;
  height: 1px; background: var(--ink);
  margin-top: 3px;
}

/* ========== HEAD CONTENT ========== */
.classification {
  font-family: Georgia, serif;
  font-weight: 900;
  font-size: 2.4rem;
  letter-spacing: -0.005em;
  line-height: 1.05;
  color: var(--ink);
  text-transform: uppercase;
}
.exec-summary {
  font-family: Georgia, serif;
  font-style: italic;
  font-size: 1.18rem;
  line-height: 1.55;
  color: var(--ink);
  border-left: 3px double var(--blood);
  padding: 4px 0 4px 18px;
  margin-top: 16px;
  background: transparent;
  border-radius: 0;
}
.kv {
  font-family: 'Courier New', monospace;
  color: var(--ink-soft);
  font-size: 0.84rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.kv b { color: var(--blood); font-weight: 400; }

/* ========== THREAT BLOCK — pull quote with drop quote ========== */
.threat-block {
  font-family: Georgia, serif;
  font-style: italic;
  font-size: 1.08rem;
  line-height: 1.6;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--paper-edge);
  border-left: 3px double var(--blood);
  padding: 16px 22px 14px 26px;
  margin: 8px 0;
  border-radius: 0;
  position: relative;
}
.threat-block::before {
  content: '\\201C';
  position: absolute;
  font-family: Georgia, serif;
  font-size: 4.5rem;
  color: var(--blood);
  opacity: 0.18;
  top: -14px; left: 8px;
  line-height: 1;
}

/* ========== FINDINGS — Roman numeral list ========== */
.finding-row {
  display: flex; gap: 16px;
  padding: 9px 0;
  border-bottom: 1px solid var(--rule);
  align-items: baseline;
}
.finding-num {
  font-family: Georgia, serif;
  color: var(--blood);
  font-weight: 700;
  min-width: 38px;
  font-size: 1.1rem;
  letter-spacing: 0.04em;
}
.finding-text {
  color: var(--ink); flex: 1;
  font-family: Georgia, serif;
  font-size: 1.04rem;
  line-height: 1.5;
}

.muted {
  color: var(--ash);
  font-family: Georgia, serif;
  font-size: 0.96rem;
  font-style: italic;
}

.placeholder-img {
  border: 1px dashed var(--paper-edge);
  background: var(--paper);
  padding: 60px 20px;
  text-align: center;
  color: var(--ash);
  font-family: 'Courier New', monospace;
  font-size: 0.85rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

/* ========== PRIORITY TARGET — RED STAMP ENVELOPE ========== */
.priority-card {
  background:
    linear-gradient(135deg, rgba(139, 26, 26, 0.05) 0%, transparent 50%),
    var(--paper-deep);
  border: 2px solid var(--blood);
  border-radius: 0;
  padding: 30px 36px 26px 36px;
  margin: 16px 0 30px 0;
  position: relative;
  box-shadow:
    0 0 0 6px var(--paper),
    0 0 0 7px var(--blood),
    0 14px 36px -18px rgba(26, 20, 16, 0.5);
}
.priority-card::before {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.95' numOctaves='2' seed='7'/><feColorMatrix values='0 0 0 0 0.55 0 0 0 0 0.10 0 0 0 0 0.10 0 0 0 0.5 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
  opacity: 0.06;
  mix-blend-mode: multiply;
}
.priority-tag {
  display: inline-block;
  font-family: 'Courier New', monospace;
  font-size: 0.78rem;
  letter-spacing: 0.2em;
  color: var(--blood);
  background: var(--paper);
  border: 2px solid var(--blood);
  padding: 5px 14px 4px 14px;
  border-radius: 0;
  text-transform: uppercase;
  margin-bottom: 14px;
  position: relative;
  transform: rotate(-1.2deg);
  box-shadow:
    0 0 0 1px var(--paper),
    0 1px 0 var(--paper-edge);
}

/* ========== THREAT CARD — desk memo ========== */
.threat-card {
  background: var(--paper-deep);
  border: 1px solid var(--paper-edge);
  border-top: 3px double var(--blood);
  border-radius: 0;
  padding: 18px 22px;
  margin: 6px 0;
  height: 100%;
  position: relative;
}
.rank-badge {
  display: inline-block;
  font-family: 'Courier New', monospace;
  font-size: 0.78rem;
  font-weight: 400;
  color: var(--blood);
  background: var(--paper);
  border: 1px solid var(--blood);
  padding: 2px 10px;
  border-radius: 0;
  margin-right: 8px;
}
.score-badge {
  display: inline-block;
  font-family: 'Courier New', monospace;
  font-size: 0.78rem;
  color: var(--ink);
  background: transparent;
  border: 1px solid var(--ink);
  border-bottom-width: 3px;
  padding: 2px 10px;
  border-radius: 0;
  margin-left: 6px;
}

/* ========== SIDEBAR — dossier index ========== */
section[data-testid="stSidebar"] {
  background:
    repeating-linear-gradient(0deg, transparent 0, transparent 36px, rgba(26, 20, 16, 0.03) 36px, rgba(26, 20, 16, 0.03) 37px),
    var(--paper-deep) !important;
  border-right: 1px solid var(--paper-edge) !important;
}
section[data-testid="stSidebar"] * {
  color: var(--ink) !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
  font-family: Georgia, serif;
  color: var(--ink) !important;
}

/* ========== METRICS — stamped paper card ========== */
[data-testid="stMetric"] {
  background: var(--paper);
  border: 1px solid var(--paper-edge);
  border-left: 3px solid var(--blood);
  border-radius: 0;
  padding: 12px 16px;
  position: relative;
}
[data-testid="stMetricValue"] {
  font-family: Georgia, serif;
  font-weight: 900 !important;
  color: var(--ink) !important;
  font-size: 2.2rem !important;
  line-height: 1 !important;
}
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] {
  font-family: 'Courier New', monospace !important;
  color: var(--ink-soft) !important;
  font-size: 0.74rem !important;
  letter-spacing: 0.14em !important;
  text-transform: uppercase !important;
}

/* ========== TABS — file tabs on a folder ========== */
.stTabs [data-baseweb="tab-list"] {
  border-bottom: 1px solid var(--ink);
  gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
  font-family: 'Courier New', monospace !important;
  font-size: 0.85rem !important;
  letter-spacing: 0.1em !important;
  color: var(--ink-soft) !important;
  background: transparent !important;
  border: 1px solid transparent !important;
  border-bottom: none !important;
  padding: 6px 14px !important;
  text-transform: uppercase;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--blood) !important;
  background: rgba(139, 26, 26, 0.04) !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
  color: var(--blood) !important;
  background: var(--paper) !important;
  border: 1px solid var(--ink) !important;
  border-bottom: 1px solid var(--paper) !important;
  position: relative;
  top: 1px;
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-border"] { display: none !important; }

/* ========== INPUTS ========== */
.stTextInput input,
.stTextInput input[type="text"] {
  background: var(--paper) !important;
  border: 1px solid var(--paper-edge) !important;
  border-bottom: 2px solid var(--ink) !important;
  border-radius: 0 !important;
  font-family: 'Courier New', monospace !important;
  color: var(--ink) !important;
  font-size: 0.92rem !important;
}
.stTextInput input::placeholder {
  color: var(--ash) !important;
  font-style: italic;
}

[data-baseweb="select"] > div {
  background: var(--paper) !important;
  border: 1px solid var(--paper-edge) !important;
  border-bottom: 2px solid var(--ink) !important;
  border-radius: 0 !important;
  font-family: Georgia, serif !important;
  color: var(--ink) !important;
}
[data-baseweb="select"] [role="listbox"] { background: var(--paper) !important; }
[data-baseweb="select"] [role="option"] {
  font-family: Georgia, serif !important;
  color: var(--ink) !important;
}
[data-baseweb="select"] [role="option"]:hover {
  background: rgba(139, 26, 26, 0.08) !important;
}

/* Toggle / checkbox text */
[data-testid="stCheckbox"] label, [data-testid="stToggle"] label,
[data-testid="stCheckbox"] *, [data-testid="stToggle"] * {
  color: var(--ink) !important;
  font-family: 'Courier New', monospace !important;
  font-size: 0.84rem !important;
  letter-spacing: 0.05em;
}

/* Captions — typewriter footnotes */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  color: var(--ink-soft) !important;
  font-family: 'Courier New', monospace !important;
  font-size: 0.76rem !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase;
}

/* Buttons — file-stamped */
.stButton button, button[kind="secondary"], button[kind="primary"] {
  background: var(--paper) !important;
  border: 1px solid var(--ink) !important;
  border-bottom-width: 3px !important;
  border-radius: 0 !important;
  font-family: 'Courier New', monospace !important;
  color: var(--ink) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.12em !important;
  font-size: 0.82rem !important;
}
.stButton button:hover {
  background: var(--blood) !important;
  color: var(--paper) !important;
  border-color: var(--blood) !important;
}

/* Expander */
[data-testid="stExpander"] {
  background: var(--paper-deep) !important;
  border: 1px solid var(--paper-edge) !important;
  border-radius: 0 !important;
  box-shadow: 0 1px 0 rgba(255, 252, 240, 0.5) inset;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary * {
  font-family: 'Courier New', monospace !important;
  color: var(--ink) !important;
  letter-spacing: 0.06em !important;
  text-transform: uppercase !important;
  font-size: 0.86rem !important;
}

/* Code */
pre, code, .stCode, [data-testid="stCodeBlock"] {
  font-family: 'Courier New', monospace !important;
  background: var(--paper) !important;
  color: var(--ink) !important;
  border: 1px solid var(--paper-edge) !important;
  border-radius: 0 !important;
}

/* Info / warning notification banners */
[data-baseweb="notification"], [data-testid="stNotification"], .stAlert {
  background: var(--paper) !important;
  border: 1.5px solid var(--blood) !important;
  border-left-width: 5px !important;
  border-radius: 0 !important;
  color: var(--ink) !important;
  font-family: Georgia, serif !important;
}
[data-baseweb="notification"] *, [data-testid="stNotification"] * {
  color: var(--ink) !important;
  font-family: Georgia, serif !important;
}

/* Streamlit's main toolbar / deploy bar — dim it down */
[data-testid="stHeader"] {
  background: transparent !important;
}
[data-testid="stToolbar"] {
  background: transparent !important;
}

/* JSON viewer */
[data-testid="stJson"] {
  background: var(--paper) !important;
  border: 1px solid var(--paper-edge) !important;
  border-radius: 0 !important;
  color: var(--ink) !important;
  font-family: 'Courier New', monospace !important;
}

/* Image-comparison slider — restyle handle to ink */
.image-comparison-slider .__rcs-handle {
  background: var(--ink) !important;
}

/* ========== ANIMATIONS — papers being placed ========== */
@keyframes paperFade {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes stampIn {
  from { opacity: 0; transform: rotate(-1.2deg) scale(1.08); }
  to   { opacity: 1; transform: rotate(-1.2deg) scale(1); }
}
@keyframes inkFade {
  from { opacity: 0; }
  to   { opacity: 1; }
}
.card { animation: paperFade 0.55s ease-out both; }
.priority-card {
  animation: paperFade 0.7s ease-out both;
  animation-delay: 0.05s;
}
.priority-tag { animation: stampIn 0.45s ease-out 0.4s both; }
.threat-card { animation: paperFade 0.5s ease-out both; }
.threat-card:nth-of-type(1) { animation-delay: 0.1s; }
.threat-card:nth-of-type(2) { animation-delay: 0.2s; }
.threat-card:nth-of-type(3) { animation-delay: 0.3s; }
.hero-title { animation: inkFade 0.8s ease-out both; }
.hero-sub { animation: inkFade 0.8s ease-out 0.2s both; }

/* Legend rows */
.legend-row {
  font-family: 'Courier New', monospace;
  font-size: 0.78rem;
  color: var(--ink-soft);
  margin: 4px 0;
  letter-spacing: 0.04em;
}

/* Ensure relative z-index for content above paper grain pseudo-elements */
[data-testid="stAppViewContainer"] > .main { position: relative; z-index: 1; }
.stApp > div { position: relative; z-index: 1; }
</style>
""",
    unsafe_allow_html=True,
)


# ---------- load data ----------

if not os.path.exists(DATA_PATH):
    st.error(f"No data file found at `{DATA_PATH}`. Run `python base_analyzer.py` first.")
    st.stop()

data = load_data(os.path.getmtime(DATA_PATH))

if not data:
    st.warning("`data/data.json` is empty. Run `python base_analyzer.py` to populate it.")
    st.stop()


# ---------- header ----------

st.markdown('<div class="hero-title">OSINT // GEOINT ANALYZER</div>', unsafe_allow_html=True)
last_update = datetime.fromtimestamp(os.path.getmtime(DATA_PATH)).strftime("%Y-%m-%d %H:%M")
st.markdown(
    f'<div class="hero-sub">CLASSIFIED // FOR DEMONSTRATION ONLY · DATA UPDATED {last_update}</div>',
    unsafe_allow_html=True,
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Bases analyzed", len(data))
m2.metric("Countries", len({b["country"] for b in data}))
m3.metric(
    "Analyst reports",
    sum(len(b["analysts"]) for b in data),
)
m4.metric(
    "Total findings",
    sum(len(a["analysis"].get("findings", [])) for b in data for a in b["analysts"]),
)


# ---------- sidebar filters ----------

with st.sidebar:
    st.markdown("### 🎯 Filters")

    search_query = st.text_input(
        "🔍 Search",
        placeholder="missile, hangar, naval...",
        help="Free-text match against findings, analysis, classifications, and detection labels.",
    )

    # Filter bases by query first, so country/base dropdowns only offer matching options.
    matching_data = [b for b in data if base_matches(b, search_query)] if search_query.strip() else data

    available_countries = sorted({b["country"] for b in matching_data})
    country_options = ["All countries"] + available_countries
    country_choice = st.selectbox("Country", country_options, index=0)

    if not matching_data:
        bases_in_scope = []
        selected_base = None
    elif country_choice == "All countries":
        bases_in_scope = matching_data
        selected_base = None
    else:
        bases_in_scope = [b for b in matching_data if b["country"] == country_choice]
        base_labels = [
            f"#{b['base_id']} — {b['commander_report']['facility_classification']} "
            f"({b['commander_report']['confidence']})"
            for b in bases_in_scope
        ]
        idx = st.selectbox(
            "Base",
            range(len(bases_in_scope)),
            format_func=lambda i: base_labels[i],
        )
        selected_base = bases_in_scope[idx]
    
    # Override with session state if a base was clicked from the overview
    if st.session_state.selected_base_id is not None:
        for b in data:
            if b['base_id'] == st.session_state.selected_base_id:
                selected_base = b
                break

    st.markdown("---")
    st.markdown("### Legend")
    st.markdown(
        f'<div class="legend-row">CONFIDENCE: '
        f'{confidence_pill("high")}{confidence_pill("medium")}{confidence_pill("low")}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="legend-row">ACTIONS: '
        f'{action_pill("zoom-in")}{action_pill("zoom-out")}'
        f'{action_pill("move-left")}{action_pill("finish")}</div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")
    show_raw_json = st.toggle("Show raw JSON")


# ---------- overview mode ----------

CONFIDENCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def threat_score(base: dict) -> int:
    cmd = base["commander_report"]
    weight = CONFIDENCE_WEIGHT.get(cmd.get("confidence", "low"), 1)
    return weight * len(cmd.get("key_findings", []))


def render_top_threats(bases: list, query: str = ""):
    if not bases:
        return
    ranked = sorted(bases, key=threat_score, reverse=True)

    st.markdown(
        '<div class="section-title">Top Threats · Ranked by Confidence × Findings</div>',
        unsafe_allow_html=True,
    )

    # Priority target — top 1, hero card with red accent.
    top = ranked[0]
    cmd = top["commander_report"]
    detection_count = sum(len(a["moondream_detections"]) for a in top["analysts"])
    st.markdown(
        f"""
<div class="priority-card">
  <div class="priority-tag">⚠ PRIORITY TARGET · RANK #01</div>
  <div class="kv">{country_label(top['country'])} · BASE #{top['base_id']} ·
    LAT {float(top['initial_latitude']):.4f}, LON {float(top['initial_longitude']):.4f}</div>
  <div style="display:flex;align-items:center;gap:12px;margin:10px 0 4px 0;flex-wrap:wrap;">
    <div class="classification">{hl(cmd['facility_classification'], query)}</div>
    {confidence_pill(cmd['confidence'])}
    <span class="score-badge">THREAT SCORE · {threat_score(top)}</span>
  </div>
  <div class="exec-summary">{hl(cmd['executive_summary'], query)}</div>
  <div class="muted" style="margin-top:12px;">
    {len(cmd.get('key_findings', []))} key findings ·
    {detection_count} detections ·
    {len(top['analysts'])} analysts
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if st.button("View Priority Target", key=f"view_priority_{top['base_id']}", use_container_width=True):
        st.session_state.selected_base_id = top['base_id']
        st.rerun()

    # Ranks 2-4 — compact threat cards in a row.
    next_tier = ranked[1:4]
    if next_tier:
        cols = st.columns(len(next_tier))
        for i, b in enumerate(next_tier):
            cmd_i = b["commander_report"]
            with cols[i]:
                st.markdown(
                    f"""
<div class="threat-card">
  <span class="rank-badge">#{i + 2:02d}</span>
  {confidence_pill(cmd_i['confidence'])}
  <div class="kv" style="margin-top:8px;">{country_label(b['country'])} · BASE #{b['base_id']}</div>
  <div class="classification" style="font-size:1.15rem;margin:6px 0;">{hl(cmd_i['facility_classification'], query)}</div>
  <div class="muted">score {threat_score(b)} ·
    {len(cmd_i.get('key_findings', []))} findings ·
    {sum(len(a['moondream_detections']) for a in b['analysts'])} detections
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )

    # Remaining bases — collapsible compact list.
    rest = ranked[4:]
    if rest:
        with st.expander(f"Other facilities ({len(rest)})"):
            for i, b in enumerate(rest, start=5):
                cmd_i = b["commander_report"]
                st.markdown(
                    f'<div class="kv" style="padding:6px 0;border-bottom:1px dashed var(--border);">'
                    f'<span class="rank-badge">#{i:02d}</span> '
                    f'{country_label(b["country"])} · BASE #{b["base_id"]} · '
                    f'<b>{hl(cmd_i["facility_classification"], query)}</b> · '
                    f'<span style="color:var(--muted);">score {threat_score(b)} · '
                    f'{cmd_i["confidence"]} confidence · '
                    f'{len(cmd_i.get("key_findings", []))} findings</span></div>',
                    unsafe_allow_html=True,
                )


def render_overview(bases: list, query: str = ""):
    render_top_threats(bases, query)
    st.markdown('<div style="margin-top: 32px; margin-bottom: 16px; border-top: 1px solid var(--paper-edge); padding-top: 24px;"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Global Distribution</div>', unsafe_allow_html=True)

    # Map of all bases
    if bases:
        map_points = [
            {
                "lat": float(b["initial_latitude"]),
                "lon": float(b["initial_longitude"]),
                "name": f"{b['country']} #{b['base_id']}",
                "classification": b["commander_report"]["facility_classification"],
                "confidence": b["commander_report"]["confidence"],
                "color": [
                    int(CONFIDENCE_COLORS.get(b["commander_report"]["confidence"], "#64748b")[1:3], 16),
                    int(CONFIDENCE_COLORS.get(b["commander_report"]["confidence"], "#64748b")[3:5], 16),
                    int(CONFIDENCE_COLORS.get(b["commander_report"]["confidence"], "#64748b")[5:7], 16),
                ],
            }
            for b in bases
        ]

        view = pdk.ViewState(
            latitude=sum(p["lat"] for p in map_points) / len(map_points),
            longitude=sum(p["lon"] for p in map_points) / len(map_points),
            zoom=2 if len({p["name"][:3] for p in map_points}) > 1 else 5,
            pitch=20,
        )
        layer = pdk.Layer(
            "ScatterplotLayer",
            data=map_points,
            get_position=["lon", "lat"],
            get_color="color",
            get_radius=120000,
            radius_min_pixels=8,
            radius_max_pixels=30,
            pickable=True,
            opacity=0.85,
        )
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view,
            map_style="light",
            tooltip={
                "html": "<b>{name}</b><br/>{classification}<br/><i>confidence: {confidence}</i>",
                "style": {"backgroundColor": "#f4ecd8", "color": "#1a1410", "fontFamily": "EB Garamond, serif", "border": "1px solid #1a1410"},
            },
        )
        st.pydeck_chart(deck, use_container_width=True)

    # Country-grouped cards
    by_country = {}
    for b in bases:
        by_country.setdefault(b["country"], []).append(b)

    for country, country_bases in by_country.items():
        st.markdown(
            f'<div class="section-title">{country_label(country)} '
            f'<span style="color:var(--muted);font-size:0.75rem;">'
            f'· {len(country_bases)} base(s)</span></div>',
            unsafe_allow_html=True,
        )
        cols = st.columns(min(3, len(country_bases)))
        for i, b in enumerate(country_bases):
            with cols[i % len(cols)]:
                cmd = b["commander_report"]
                card_html = f"""
<div class="clickable-card" style="cursor:pointer;" data-base-id="{b['base_id']}">
  <div class="card">
    <div class="kv"><b>BASE #{b['base_id']}</b></div>
    <div class="classification" style="margin:8px 0 6px 0;">{hl(cmd['facility_classification'], query)}</div>
    {confidence_pill(cmd['confidence'])}
    <div class="exec-summary">{hl(cmd['executive_summary'], query)}</div>
    <div class="muted" style="margin-top:10px;">
      {len(b['analysts'])} analysts ·
      {sum(len(a['moondream_detections']) for a in b['analysts'])} detections ·
      lat {float(b['initial_latitude']):.3f}, lon {float(b['initial_longitude']):.3f}
    </div>
  </div>
</div>
"""
                st.markdown(card_html, unsafe_allow_html=True)
                if st.button("View", key=f"view_base_{b['base_id']}", help=f"View BASE #{b['base_id']}", use_container_width=True):
                    st.session_state.selected_base_id = b['base_id']
                    st.rerun()


# ---------- base detail mode ----------

def render_base_detail(base: dict, query: str = ""):
    cmd = base["commander_report"]
    
    # Back button
    if st.button("← Back to overview"):
        st.session_state.selected_base_id = None
        st.rerun()

    # Hero card — text left, primary screenshot right
    hero_text, hero_image = st.columns([3, 2], gap="medium")
    with hero_text:
        st.markdown(
            f"""
<div class="card">
  <div class="kv">{country_label(base['country'])} · BASE #{base['base_id']} · LAT {float(base['initial_latitude']):.4f}, LON {float(base['initial_longitude']):.4f}</div>
  <div style="display:flex;align-items:center;gap:14px;margin-top:8px;flex-wrap:wrap;">
    <div class="classification">{hl(cmd['facility_classification'], query)}</div>
    {confidence_pill(cmd['confidence'])}
  </div>
  <div class="exec-summary">{hl(cmd['executive_summary'], query)}</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with hero_image:
        primary_path, primary_analyst = pick_primary_screenshot(base)
        if primary_path:
            st.image(primary_path, use_container_width=True)
            if primary_analyst:
                zoom = primary_analyst["state_when_analyzed"]["zoom"]
                annot_label = " · annotated" if primary_path.endswith("_annotated.jpg") else ""
                st.caption(f"View {primary_analyst['view_idx']} · zoom={int(zoom)}m{annot_label}")
        else:
            st.markdown(
                '<div class="placeholder-img">no preview available</div>',
                unsafe_allow_html=True,
            )

    # Stats strip
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Distinct views", len({a["view_idx"] for a in base["analysts"]}))
    s2.metric("Total findings", sum(len(a["analysis"].get("findings", [])) for a in base["analysts"]))
    s3.metric("Moondream detections", sum(len(a["moondream_detections"]) for a in base["analysts"]))
    s4.metric("Disagreements flagged", len(cmd.get("disagreements_or_uncertainties", [])))

    # Detection Profile — aggregated bar chart of class counts across all 8 analysts
    st.markdown(
        '<div class="section-title">Detection Profile · objects detected across 8 analysts</div>',
        unsafe_allow_html=True,
    )
    class_counts = Counter(
        d["label"]
        for a in base["analysts"]
        for d in a.get("moondream_detections", [])
    )
    if class_counts:
        chart_rows = [{"class": k, "count": v} for k, v in class_counts.most_common()]
        chart = (
            alt.Chart(alt.Data(values=chart_rows))
            .mark_bar(color="#8b1a1a", cornerRadiusEnd=0)
            .encode(
                x=alt.X(
                    "count:Q",
                    title="detections",
                    axis=alt.Axis(labelColor="#3d342c", titleColor="#3d342c", grid=False, domainColor="#1a1410", tickColor="#1a1410"),
                ),
                y=alt.Y(
                    "class:N",
                    sort="-x",
                    title=None,
                    axis=alt.Axis(labelColor="#1a1410", labelFontSize=13, labelFont="EB Garamond", domainColor="#1a1410"),
                ),
                tooltip=[
                    alt.Tooltip("class:N", title="class"),
                    alt.Tooltip("count:Q", title="detections"),
                ],
            )
            .properties(height=min(320, 26 * len(class_counts) + 40), background="transparent")
            .configure_view(strokeWidth=0)
            .configure_axis(domain=False)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.markdown(
            '<div class="muted">No Moondream detections logged for this base.</div>',
            unsafe_allow_html=True,
        )

    # Investigation trail map: PathLayer + numbered ScatterplotLayer + TextLayer
    st.markdown(
        '<div class="section-title">Investigation Trail · Camera Path Across 8 Analysts</div>',
        unsafe_allow_html=True,
    )

    trail_points = []
    for a in base["analysts"]:
        s = a["state_when_analyzed"]
        action = a["analysis"].get("action", "finish")
        color_hex = ACTION_COLORS.get(action, "#64748b")
        trail_points.append({
            "lat": float(s["lat"]),
            "lon": float(s["lon"]),
            "analyst": a["analyst_num"],
            "label": str(a["analyst_num"]),
            "zoom_m": int(s["zoom"]),
            "action": action,
            "color": [
                int(color_hex[1:3], 16),
                int(color_hex[3:5], 16),
                int(color_hex[5:7], 16),
                230,
            ],
        })

    path_data = [{"path": [[p["lon"], p["lat"]] for p in trail_points]}]

    path_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[139, 26, 26, 200],   # blood-red ink trail
        get_width=3,
        width_min_pixels=2,
        width_max_pixels=4,
    )

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=trail_points,
        get_position=["lon", "lat"],
        get_color="color",
        get_radius=60,
        radius_min_pixels=14,
        radius_max_pixels=22,
        pickable=True,
        stroked=True,
        get_line_color=[26, 20, 16, 240],  # ink outline on paper
        line_width_min_pixels=1.5,
    )

    text_layer = pdk.Layer(
        "TextLayer",
        data=trail_points,
        get_position=["lon", "lat"],
        get_text="label",
        get_size=15,
        get_color=[26, 20, 16, 255],     # ink-black numbers
        get_pixel_offset=[0, -22],
    )

    avg_lat = sum(p["lat"] for p in trail_points) / len(trail_points)
    avg_lon = sum(p["lon"] for p in trail_points) / len(trail_points)
    # Zoom heuristic: tighter spread → zoom in further. Egypt 147's stuck-at-one-coord
    # case still renders fine because the marker stack is visible at any zoom.
    span = max(
        max(p["lat"] for p in trail_points) - min(p["lat"] for p in trail_points),
        max(p["lon"] for p in trail_points) - min(p["lon"] for p in trail_points),
    )
    if span < 0.001:
        view_zoom = 16
    elif span < 0.01:
        view_zoom = 14
    elif span < 0.05:
        view_zoom = 12
    else:
        view_zoom = 10

    trail_deck = pdk.Deck(
        layers=[path_layer, scatter_layer, text_layer],
        initial_view_state=pdk.ViewState(
            latitude=avg_lat,
            longitude=avg_lon,
            zoom=view_zoom,
            pitch=35,
        ),
        map_style="light",
        tooltip={
            "html": "<b>Analyst {analyst}</b><br/>zoom: {zoom_m} m<br/>action chosen: <i>{action}</i>",
            "style": {"backgroundColor": "#f4ecd8", "color": "#1a1410", "fontFamily": "Special Elite, monospace", "border": "1px solid #1a1410"},
        },
    )
    st.pydeck_chart(trail_deck, use_container_width=True)
    st.markdown(
        '<div class="muted">Numbered markers = analyst sequence. Marker color = action that '
        'analyst chose for the next view (see legend in sidebar). Amber line = camera path.</div>',
        unsafe_allow_html=True,
    )

    # Commander section
    st.markdown('<div class="section-title">Commander Synthesis</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Key findings**")
        if cmd.get("key_findings"):
            for i, f in enumerate(cmd["key_findings"], 1):
                st.markdown(
                    f'<div class="finding-row"><div class="finding-num">{i:02d}</div>'
                    f'<div class="finding-text">{hl(f, query)}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="muted">No key findings reported.</div>', unsafe_allow_html=True)

        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.markdown("**Threat assessment**")
        st.markdown(
            f'<div class="threat-block">{hl(cmd.get("threat_assessment", "—"), query)}</div>',
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown("**Recommended next steps**")
        if cmd.get("recommended_next_steps"):
            for step in cmd["recommended_next_steps"]:
                st.markdown(f"• {hl(step, query)}", unsafe_allow_html=True)
        else:
            st.markdown('<div class="muted">None.</div>', unsafe_allow_html=True)

        with st.expander(
            f"⚠️ Disagreements / uncertainties ({len(cmd.get('disagreements_or_uncertainties', []))})"
        ):
            disagreements = cmd.get("disagreements_or_uncertainties", [])
            if disagreements:
                for d in disagreements:
                    st.markdown(f"• {hl(d, query)}", unsafe_allow_html=True)
            else:
                st.markdown('<div class="muted">Analysts converged — no disagreements logged.</div>', unsafe_allow_html=True)

    # Analyst journey
    st.markdown('<div class="section-title">Analyst Journey · 8 perspectives</div>', unsafe_allow_html=True)
    tabs = st.tabs([f"Analyst {a['analyst_num']}" for a in base["analysts"]])
    for tab, analyst in zip(tabs, base["analysts"]):
        with tab:
            render_analyst(analyst, query)


def render_analyst(a: dict, query: str = ""):
    state = a["state_when_analyzed"]
    analysis = a["analysis"]
    raw = screenshot_path(a.get("screenshot_file"))
    annotated = screenshot_path(a.get("annotated_screenshot_file"))

    # State + action chips row
    st.markdown(
        f'<div class="kv">VIEW #{a["view_idx"]} · '
        f'<b>lat</b> {state["lat"]:.5f} · <b>lon</b> {state["lon"]:.5f} · '
        f'<b>zoom</b> {state["zoom"]:.0f} m · '
        f'triaged: <b>{"YES" if a.get("triaged_in") else "NO"}</b></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="margin-top:6px;">action {action_pill(analysis["action"])}</div>'
        f'<div style="margin-top:6px;">{detection_pills(a["moondream_detections"])}</div>',
        unsafe_allow_html=True,
    )

    # Image: comparison slider when both raw + annotated exist; single image otherwise.
    if raw and annotated:
        st.caption(
            f"Drag the divider · left = satellite frame · right = Moondream annotated "
            f"({len(a['moondream_detections'])} object(s))"
        )
        # Display images side-by-side in full width
        col1, col2 = st.columns(2)
        with col1:
            st.image(raw, caption="Raw satellite frame", use_container_width=True)
        with col2:
            st.image(annotated, caption=f"Annotated ({len(a['moondream_detections'])} objects)", use_container_width=True)
    elif raw:
        st.caption("Satellite frame · (no Moondream annotations for this view)")
        st.image(raw, use_container_width=True)
    else:
        st.markdown(
            '<div class="placeholder-img">— image not found —</div>',
            unsafe_allow_html=True,
        )

    # Findings + analysis text
    f1, f2 = st.columns([3, 2])
    with f1:
        st.markdown("**Findings**")
        if analysis.get("findings"):
            for i, f in enumerate(analysis["findings"], 1):
                st.markdown(
                    f'<div class="finding-row"><div class="finding-num">{i:02d}</div>'
                    f'<div class="finding-text">{hl(f, query)}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="muted">No findings.</div>', unsafe_allow_html=True)

        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.markdown("**Analyst commentary**")
        st.markdown(
            f'<div class="threat-block">{hl(analysis.get("analysis", "—"), query)}</div>',
            unsafe_allow_html=True,
        )

    with f2:
        with st.expander("Things to continue analyzing", expanded=True):
            todos = analysis.get("things_to_continue_analyzing", [])
            if todos:
                for t in todos:
                    st.markdown(f"• {hl(t, query)}", unsafe_allow_html=True)
            else:
                st.markdown('<div class="muted">Nothing flagged for follow-up.</div>', unsafe_allow_html=True)

        st.caption(f"Source: `{a.get('screenshot_file')}`")


# ---------- dispatch ----------

q = search_query.strip()
if q:
    st.info(
        f"🔍 Showing **{len(bases_in_scope)}** of **{len(data)}** base(s) matching `{q}`",
        icon="🔍",
    )

# If a base was selected via clickable card, show it regardless of search/filter
if st.session_state.selected_base_id is not None and selected_base is not None:
    render_base_detail(selected_base, q)
elif not bases_in_scope:
    st.warning(f"No bases match `{q}`. Clear the search to see all data.")
elif selected_base is None:
    render_overview(bases_in_scope, q)
else:
    render_base_detail(selected_base, q)


# ---------- raw JSON ----------

if show_raw_json:
    st.markdown('<div class="section-title">Raw JSON</div>', unsafe_allow_html=True)
    if selected_base is None:
        st.json(bases_in_scope)
    else:
        st.json(selected_base)

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

CONFIDENCE_COLORS = {"high": "#22c55e", "medium": "#f59e0b", "low": "#ef4444"}
ACTION_COLORS = {
    "zoom-in": "#22c55e",
    "zoom-out": "#3b82f6",
    "move-left": "#f59e0b",
    "move-right": "#f59e0b",
    "finish": "#64748b",
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
    font = "ui-monospace, SFMono-Regular, monospace" if mono else "inherit"
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f'background:{color}22;color:{color};border:1px solid {color}66;'
        f'font-family:{font};font-size:0.78rem;font-weight:600;'
        f'letter-spacing:0.04em;text-transform:uppercase;margin:2px 4px 2px 0;">'
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
    page_title="OSINT GEOINT Analyzer",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
:root {
  --bg: #0b1220;
  --panel: #111a2e;
  --panel-2: #15203a;
  --accent: #f59e0b;
  --text: #e5e7eb;
  --muted: #94a3b8;
  --border: #1f2a44;
}
.stApp { background: linear-gradient(180deg, #0b1220 0%, #0e162a 100%); }
.hero-title {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 2.1rem; font-weight: 700; letter-spacing: 0.18em;
  color: var(--text);
  border-bottom: 2px solid var(--accent);
  padding-bottom: 6px; margin-bottom: 4px;
}
.hero-sub {
  font-family: ui-monospace, monospace; color: var(--muted);
  font-size: 0.85rem; letter-spacing: 0.1em; text-transform: uppercase;
  margin-bottom: 18px;
}
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 18px 22px;
  margin: 10px 0 18px 0;
}
.card h3, .card h4 { color: var(--text); margin-top: 0; }
.section-title {
  font-family: ui-monospace, monospace;
  font-size: 0.95rem; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--accent); margin: 24px 0 8px 0;
  border-bottom: 1px dashed var(--border); padding-bottom: 6px;
}
.classification {
  font-family: ui-monospace, monospace;
  font-size: 1.6rem; font-weight: 700; letter-spacing: 0.06em;
  color: var(--text);
}
.exec-summary {
  font-size: 1.02rem; line-height: 1.55; color: var(--text);
  border-left: 3px solid var(--accent);
  padding: 6px 14px; background: var(--panel-2); border-radius: 0 4px 4px 0;
  margin-top: 10px;
}
.kv { font-family: ui-monospace, monospace; color: var(--muted); font-size: 0.82rem; }
.kv b { color: var(--text); }
.threat-block {
  background: var(--panel-2); border: 1px solid var(--border);
  border-left: 3px solid #ef4444;
  padding: 12px 16px; border-radius: 4px; color: var(--text);
  font-style: italic; line-height: 1.55;
}
.finding-row {
  display: flex; gap: 10px; padding: 6px 0;
  border-bottom: 1px dashed var(--border);
}
.finding-num {
  font-family: ui-monospace, monospace; color: var(--accent);
  font-weight: 700; min-width: 32px;
}
.finding-text { color: var(--text); flex: 1; }
.muted { color: var(--muted); font-size: 0.85rem; }
.placeholder-img {
  border: 1px dashed var(--border); border-radius: 6px;
  padding: 60px 20px; text-align: center; color: var(--muted);
  font-family: ui-monospace, monospace;
}
section[data-testid="stSidebar"] {
  background: #0a1020; border-right: 1px solid var(--border);
}
[data-testid="stMetric"] {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 12px;
}
.legend-row { font-family: ui-monospace, monospace; font-size: 0.78rem; color: var(--muted); margin: 4px 0; }

/* Top threats leaderboard */
.priority-card {
  background: linear-gradient(135deg, #1a0f1a 0%, #2a1015 100%);
  border: 1px solid #ef4444;
  border-left: 4px solid #ef4444;
  border-radius: 8px;
  padding: 22px 26px;
  margin: 12px 0 22px 0;
  box-shadow: 0 0 24px rgba(239, 68, 68, 0.15);
}
.priority-tag {
  display: inline-block;
  font-family: ui-monospace, monospace;
  font-size: 0.72rem;
  letter-spacing: 0.18em;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid #ef4444;
  padding: 3px 10px;
  border-radius: 4px;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.threat-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 3px solid #f59e0b;
  border-radius: 6px;
  padding: 14px 18px;
  margin: 6px 0;
  height: 100%;
}
.rank-badge {
  display: inline-block;
  font-family: ui-monospace, monospace;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--accent);
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid var(--accent);
  padding: 2px 8px;
  border-radius: 4px;
  margin-right: 8px;
}
.score-badge {
  display: inline-block;
  font-family: ui-monospace, monospace;
  font-size: 0.74rem;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  padding: 3px 10px;
  border-radius: 4px;
  margin-left: 6px;
}
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
            map_style="dark",
            tooltip={
                "html": "<b>{name}</b><br/>{classification}<br/><i>confidence: {confidence}</i>",
                "style": {"backgroundColor": "#0b1220", "color": "#e5e7eb"},
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
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(
                        f"""
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
""",
                        unsafe_allow_html=True,
                    )
                with col2:
                    if st.button("→", key=f"view_base_{b['base_id']}", help=f"View BASE #{b['base_id']}"):
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
            .mark_bar(color="#f59e0b", cornerRadiusEnd=2)
            .encode(
                x=alt.X(
                    "count:Q",
                    title="detections",
                    axis=alt.Axis(labelColor="#94a3b8", titleColor="#94a3b8", grid=False),
                ),
                y=alt.Y(
                    "class:N",
                    sort="-x",
                    title=None,
                    axis=alt.Axis(labelColor="#e5e7eb", labelFontSize=12),
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
        get_color=[245, 158, 11, 180],
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
        get_line_color=[255, 255, 255, 220],
        line_width_min_pixels=1,
    )

    text_layer = pdk.Layer(
        "TextLayer",
        data=trail_points,
        get_position=["lon", "lat"],
        get_text="label",
        get_size=14,
        get_color=[255, 255, 255, 255],
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
        map_style="dark",
        tooltip={
            "html": "<b>Analyst {analyst}</b><br/>zoom: {zoom_m} m<br/>action chosen: <i>{action}</i>",
            "style": {"backgroundColor": "#0b1220", "color": "#e5e7eb", "fontFamily": "ui-monospace, monospace"},
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

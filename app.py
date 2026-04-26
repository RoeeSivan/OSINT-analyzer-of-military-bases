"""
OSINT GEOINT Analyzer — Streamlit GUI.

Reads data/data.json (cumulative pipeline output) and renders a per-base
intelligence dashboard with screenshots, Moondream detections, the 8-analyst
journey, and the commander synthesis. Group/filter by country.

Run:
    source venv/bin/activate
    streamlit run app.py
"""

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

import pydeck as pdk
import streamlit as st

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


# ---------- page config + global CSS ----------

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

    countries = sorted({b["country"] for b in data})
    country_options = ["All countries"] + countries
    country_choice = st.selectbox("Country", country_options, index=0)

    if country_choice == "All countries":
        bases_in_scope = data
        selected_base = None
    else:
        bases_in_scope = [b for b in data if b["country"] == country_choice]
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

def render_overview(bases: list):
    st.markdown('<div class="section-title">Strategic Overview</div>', unsafe_allow_html=True)

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
                st.markdown(
                    f"""
<div class="card">
  <div class="kv"><b>BASE #{b['base_id']}</b></div>
  <div class="classification" style="margin:8px 0 6px 0;">{cmd['facility_classification']}</div>
  {confidence_pill(cmd['confidence'])}
  <div class="exec-summary">{cmd['executive_summary']}</div>
  <div class="muted" style="margin-top:10px;">
    {len(b['analysts'])} analysts ·
    {sum(len(a['moondream_detections']) for a in b['analysts'])} detections ·
    lat {float(b['initial_latitude']):.3f}, lon {float(b['initial_longitude']):.3f}
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )


# ---------- base detail mode ----------

def render_base_detail(base: dict):
    cmd = base["commander_report"]

    # Hero card
    st.markdown(
        f"""
<div class="card">
  <div class="kv">{country_label(base['country'])} · BASE #{base['base_id']} · LAT {float(base['initial_latitude']):.4f}, LON {float(base['initial_longitude']):.4f}</div>
  <div style="display:flex;align-items:center;gap:14px;margin-top:8px;flex-wrap:wrap;">
    <div class="classification">{cmd['facility_classification']}</div>
    {confidence_pill(cmd['confidence'])}
  </div>
  <div class="exec-summary">{cmd['executive_summary']}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Stats strip
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Distinct views", len({a["view_idx"] for a in base["analysts"]}))
    s2.metric("Total findings", sum(len(a["analysis"].get("findings", [])) for a in base["analysts"]))
    s3.metric("Moondream detections", sum(len(a["moondream_detections"]) for a in base["analysts"]))
    s4.metric("Disagreements flagged", len(cmd.get("disagreements_or_uncertainties", [])))

    # Map
    st.markdown('<div class="section-title">Location</div>', unsafe_allow_html=True)
    deck = pdk.Deck(
        layers=[
            pdk.Layer(
                "ScatterplotLayer",
                data=[{"lat": float(base["initial_latitude"]), "lon": float(base["initial_longitude"])}],
                get_position=["lon", "lat"],
                get_color=[245, 158, 11, 230],
                get_radius=400,
                radius_min_pixels=10,
                radius_max_pixels=40,
            )
        ],
        initial_view_state=pdk.ViewState(
            latitude=float(base["initial_latitude"]),
            longitude=float(base["initial_longitude"]),
            zoom=10,
            pitch=30,
        ),
        map_style="dark",
    )
    st.pydeck_chart(deck, use_container_width=True)

    # Commander section
    st.markdown('<div class="section-title">Commander Synthesis</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Key findings**")
        if cmd.get("key_findings"):
            for i, f in enumerate(cmd["key_findings"], 1):
                st.markdown(
                    f'<div class="finding-row"><div class="finding-num">{i:02d}</div>'
                    f'<div class="finding-text">{f}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="muted">No key findings reported.</div>', unsafe_allow_html=True)

        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.markdown("**Threat assessment**")
        st.markdown(
            f'<div class="threat-block">{cmd.get("threat_assessment", "—")}</div>',
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown("**Recommended next steps**")
        if cmd.get("recommended_next_steps"):
            for step in cmd["recommended_next_steps"]:
                st.markdown(f"• {step}")
        else:
            st.markdown('<div class="muted">None.</div>', unsafe_allow_html=True)

        with st.expander(
            f"⚠️ Disagreements / uncertainties ({len(cmd.get('disagreements_or_uncertainties', []))})"
        ):
            disagreements = cmd.get("disagreements_or_uncertainties", [])
            if disagreements:
                for d in disagreements:
                    st.markdown(f"• {d}")
            else:
                st.markdown('<div class="muted">Analysts converged — no disagreements logged.</div>', unsafe_allow_html=True)

    # Analyst journey
    st.markdown('<div class="section-title">Analyst Journey · 8 perspectives</div>', unsafe_allow_html=True)
    tabs = st.tabs([f"Analyst {a['analyst_num']}" for a in base["analysts"]])
    for tab, analyst in zip(tabs, base["analysts"]):
        with tab:
            render_analyst(analyst)


def render_analyst(a: dict):
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

    # Image columns
    col_raw, col_annot = st.columns(2)
    with col_raw:
        st.caption("Satellite frame")
        if raw:
            st.image(raw, use_container_width=True)
        else:
            st.markdown(
                '<div class="placeholder-img">— image not found —</div>',
                unsafe_allow_html=True,
            )
    with col_annot:
        st.caption(f"Moondream annotated · {len(a['moondream_detections'])} object(s)")
        if annotated:
            st.image(annotated, use_container_width=True)
        else:
            st.markdown(
                '<div class="placeholder-img">— no annotations —</div>',
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
                    f'<div class="finding-text">{f}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="muted">No findings.</div>', unsafe_allow_html=True)

        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.markdown("**Analyst commentary**")
        st.markdown(
            f'<div class="threat-block">{analysis.get("analysis", "—")}</div>',
            unsafe_allow_html=True,
        )

    with f2:
        with st.expander("Things to continue analyzing", expanded=True):
            todos = analysis.get("things_to_continue_analyzing", [])
            if todos:
                for t in todos:
                    st.markdown(f"• {t}")
            else:
                st.markdown('<div class="muted">Nothing flagged for follow-up.</div>', unsafe_allow_html=True)

        st.caption(f"Source: `{a.get('screenshot_file')}`")


# ---------- dispatch ----------

if selected_base is None:
    render_overview(bases_in_scope)
else:
    render_base_detail(selected_base)


# ---------- raw JSON ----------

if show_raw_json:
    st.markdown('<div class="section-title">Raw JSON</div>', unsafe_allow_html=True)
    if selected_base is None:
        st.json(bases_in_scope)
    else:
        st.json(selected_base)

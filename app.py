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
    initial_sidebar_state="collapsed",
)

# Load external CSS
with open("styles.css", "r", encoding="utf-8") as f:
    css = f.read()

st.markdown(
    f"<style>{css}</style>",
    unsafe_allow_html=True,
)


# ---------- load data ----------


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


# ---------- top filter bar ----------

if "search_query_value" not in st.session_state:
    st.session_state.search_query_value = ""
if "country_choice_value" not in st.session_state:
    st.session_state.country_choice_value = "All countries"

# Pre-compute filter scope using current session-state values, so the count chip
# above the inputs reflects what the inputs will produce on this run.
_pending_query = st.session_state.search_query_value
_pending_country = st.session_state.country_choice_value
_pending_matching = (
    [b for b in data if base_matches(b, _pending_query)]
    if _pending_query.strip()
    else data
)
_pending_in_scope = (
    _pending_matching
    if _pending_country == "All countries"
    else [b for b in _pending_matching if b["country"] == _pending_country]
)
_pending_filters_active = bool(_pending_query.strip()) or _pending_country != "All countries"

_count_class = "filter-bar-count is-filtered" if _pending_filters_active else "filter-bar-count"
_count_label = (
    f"{len(_pending_in_scope)} OF {len(data)} BASES"
    if _pending_filters_active
    else f"{len(data)} BASES"
)
st.markdown(
    f'<div class="filter-bar-header">'
    f'<span class="filter-bar-title">Dossier Archive · Filter</span>'
    f'<span class="{_count_class}">{_count_label}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

fc1, fc2, fc3 = st.columns([3, 1, 0.6])
with fc1:
    search_query = st.text_input(
        "🔍 Search",
        placeholder="🔍  Search objects: missile, hangar, naval, runway...",
        label_visibility="collapsed",
        key="search_query_value",
        help="Free-text match against findings, analysis, classifications, and detection labels.",
    )
with fc2:
    matching_data = [b for b in data if base_matches(b, search_query)] if search_query.strip() else data
    available_countries = sorted({b["country"] for b in matching_data})
    country_options = ["All countries"] + available_countries
    if st.session_state.country_choice_value not in country_options:
        st.session_state.country_choice_value = "All countries"
    country_choice = st.selectbox(
        "Country",
        country_options,
        label_visibility="collapsed",
        key="country_choice_value",
    )

if not matching_data:
    bases_in_scope = []
elif country_choice == "All countries":
    bases_in_scope = matching_data
else:
    bases_in_scope = [b for b in matching_data if b["country"] == country_choice]

filters_active = bool(search_query.strip()) or country_choice != "All countries"

def _clear_filters():
    st.session_state.search_query_value = ""
    st.session_state.country_choice_value = "All countries"

with fc3:
    if filters_active:
        st.button(
            "Clear",
            key="clear_filters",
            on_click=_clear_filters,
            use_container_width=True,
        )

selected_base = None
if st.session_state.selected_base_id is not None:
    for b in data:
        if b["base_id"] == st.session_state.selected_base_id:
            selected_base = b
            break


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

    # Threat-weighted global map: radius and red-intensity scale with threat_score.
    if bases:
        scores = [threat_score(b) for b in bases]
        max_score = max(scores) or 1

        map_points = []
        for b in bases:
            score = threat_score(b)
            ratio = score / max_score
            map_points.append({
                "lat": float(b["initial_latitude"]),
                "lon": float(b["initial_longitude"]),
                "name": f"{b['country']} #{b['base_id']}",
                "classification": b["commander_report"]["facility_classification"],
                "confidence": b["commander_report"]["confidence"],
                "score": score,
                "radius": 60000 + int(ratio * 240000),
                "color": [
                    int(200 + (139 - 200) * ratio),
                    int(180 + (26 - 180) * ratio),
                    int(130 + (26 - 130) * ratio),
                    int(140 + ratio * 115),
                ],
            })

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
            get_radius="radius",
            radius_min_pixels=6,
            radius_max_pixels=42,
            pickable=True,
            opacity=0.85,
            stroked=True,
            get_line_color=[26, 20, 16, 180],
            line_width_min_pixels=1,
        )
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view,
            map_style="light",
            tooltip={
                "html": "<b>{name}</b><br/>{classification}<br/>"
                        "<i>confidence: {confidence}</i><br/>"
                        "<b style='color:#8b1a1a;'>threat score: {score}</b>",
                "style": {"backgroundColor": "#f4ecd8", "color": "#1a1410", "fontFamily": "EB Garamond, serif", "border": "1px solid #1a1410"},
            },
        )
        st.pydeck_chart(deck, use_container_width=True)
        st.caption(
            f"Dot size + redness ∝ threat score (confidence × findings). "
            f"Range: {min(scores)}–{max(scores)} across {len(bases)} base(s)."
        )

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
    <span class="card-corner-mark"></span>
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

    if raw and annotated:
        st.caption(
            f"Left = raw satellite frame · right = Moondream annotated "
            f"({len(a['moondream_detections'])} object(s))"
        )
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


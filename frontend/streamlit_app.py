"""
streamlit_app.py: Streamlit frontend for MediBuddy Weather-Advisory Support Bot.
Features vibrant modern UI styling, categorized preset chips, welcome empty state,
structured decision trace tabs, sidebar quick-lookup & SOP directory, and full error handling.
"""
import sys
import uuid
import random
import logging
from pathlib import Path
import streamlit as st

# Ensure app modules are importable
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.graph import create_advisory_graph
from app.geo_weather import geocode_location, fetch_weather

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("streamlit_app")

# Abuse protection caps
MAX_INPUT_LENGTH = 500
MAX_SESSION_MESSAGES = 20

PRESET_CATEGORIES = {
    "🏃 Outdoor Sports & Recreation": [
        {"label": "🚴 Cycling in Bhopal", "query": "Is it safe to go cycling in Bhopal, Madhya Pradesh today?"},
        {"label": "⚽ Outdoor Football in Delhi", "query": "Can we host a football match in Delhi, India this afternoon?"},
        {"label": "🏃 Morning Run in Bangalore", "query": "Is morning jogging recommended in Bangalore, Karnataka tomorrow?"},
    ],
    "👶 Vulnerable & Sensitive Groups": [
        {"label": "👶 Toddler Park Visit in Bhopal", "query": "Can I take my 3 year old toddler to the park in Bhopal, Madhya Pradesh today?"},
        {"label": "👴 Elderly Walk in Jaipur", "query": "Is it safe for senior citizens to take an evening walk in Jaipur, Rajasthan today?"},
    ],
    "🚘 Travel & Road Trips": [
        {"label": "🏔️ Leh Ladakh Road Trip", "query": "Taking a road trip to Leh, Ladakh today"},
        {"label": "🌧️ Cherrapunjee Monsoon Trip", "query": "Planning a road trip to Cherrapunjee, Meghalaya today"},
        {"label": "🚗 Manali Mountain Drive", "query": "Driving to Manali, Himachal Pradesh today, is the weather safe?"},
    ],
    "🌊 Water & Beach Activities": [
        {"label": "🏖️ Juhu Beach Picnic", "query": "Is it a good day for a family picnic at Juhu Beach, Mumbai midday?"},
        {"label": "🪂 Scuba Diving in Delhi", "query": "Can I go scuba diving in Delhi, India today?"},
    ]
}



ALL_PRESETS = [item for cat in PRESET_CATEGORIES.values() for item in cat]

SOP_DIRECTORY = [
    {"id": "SOP_HEAT_001", "name": "Heat Wave & High Heat Index Risk", "icon": "🔥"},
    {"id": "SOP_COLD_002", "name": "Extreme Cold & Hypothermia Risk", "icon": "❄️"},
    {"id": "SOP_WIND_003", "name": "High Wind & Storm Advisory", "icon": "💨"},
    {"id": "SOP_RAIN_004", "name": "Heavy Rain & Downpour Warning", "icon": "🌧️"},
    {"id": "SOP_STORM_005", "name": "Thunderstorm & Lightning Hazard", "icon": "⚡"},
    {"id": "SOP_AQI_006", "name": "Severe Air Pollution & High AQI", "icon": "😷"},
    {"id": "SOP_UV_007", "name": "Extreme UV & Sunstroke Advisory", "icon": "☀️"},
    {"id": "SOP_SNOW_008", "name": "Snow, Ice & Blizzard Hazard", "icon": "🏔️"},
    {"id": "SOP_FOG_009", "name": "Dense Fog & Visibility Advisory", "icon": "🌫️"},
    {"id": "SOP_TRAVEL_010", "name": "Road Trip & Mountain Highway Safety", "icon": "🚗"},
    {"id": "SOP_SENSITIVE_011", "name": "Toddlers, Children & Elderly Outdoor Guidance", "icon": "👶"},
    {"id": "SOP_SWIM_012", "name": "Outdoor Swimming & Beach Activity", "icon": "🏊"},
    {"id": "SOP_DIVING_013", "name": "Scuba Diving & Ocean Excursions", "icon": "🤿"},
    {"id": "SOP_CONCERT_014", "name": "Open-Air Events & Festivals", "icon": "🎪"},
    {"id": "SOP_MATCH_015", "name": "Outdoor Sports Match & Stadium Events", "icon": "⚽"},
]


@st.cache_resource
def get_graph_app():
    """Cache the compiled LangGraph workflow instance across reruns."""
    return create_advisory_graph()


def apply_custom_css():
    """Applies modern CSS styling for a state-of-the-art UI."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Plus Jakarta Sans', sans-serif;
        }

        /* Hero Banner */
        .hero-banner {
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 40%, #312e81 100%);
            padding: 28px 32px;
            border-radius: 20px;
            color: #ffffff;
            margin-bottom: 24px;
            box-shadow: 0 12px 30px -8px rgba(30, 27, 75, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .hero-title {
            font-size: 28px;
            font-weight: 800;
            margin: 0 0 8px 0;
            color: #ffffff;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .hero-subtitle {
            font-size: 15px;
            color: #c7d2fe;
            margin: 0;
            font-weight: 400;
            line-height: 1.5;
        }
        .hero-badges {
            display: flex;
            gap: 10px;
            margin-top: 16px;
            flex-wrap: wrap;
        }
        .hero-badge {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            padding: 6px 14px;
            border-radius: 30px;
            font-size: 12px;
            color: #e0e7ff;
            border: 1px solid rgba(255, 255, 255, 0.18);
            font-weight: 600;
        }

        /* Welcome Card */
        .welcome-card {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border: 1.5px dashed #cbd5e1;
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
            text-align: center;
        }
        .welcome-title {
            font-size: 18px;
            font-weight: 700;
            color: #1e293b;
            margin-bottom: 8px;
        }
        .welcome-desc {
            font-size: 14px;
            color: #64748b;
            max-width: 650px;
            margin: 0 auto 16px auto;
            line-height: 1.6;
        }

        /* Category Chips Styling */
        .category-header {
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: #475569;
            margin-top: 14px;
            margin-bottom: 8px;
        }

        /* Decision Trace Cards */
        .trace-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 14px;
            padding: 16px 20px;
            margin-top: 8px;
        }
        .trace-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin-bottom: 12px;
        }
        .trace-item {
            background: #ffffff;
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid #e2e8f0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
        }
        .trace-label {
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.4px;
        }
        .trace-val {
            font-size: 13.5px;
            color: #0f172a;
            font-weight: 600;
            margin-top: 2px;
        }

        /* Risk Badges */
        .badge-safe {
            background-color: #dcfce7;
            color: #15803d;
            border: 1px solid #bbf7d0;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 12px;
            display: inline-block;
        }
        .badge-warning {
            background-color: #fef3c7;
            color: #b45309;
            border: 1px solid #fde68a;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 12px;
            display: inline-block;
        }
        .badge-danger {
            background-color: #fee2e2;
            color: #b91c1c;
            border: 1px solid #fca5a5;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 12px;
            display: inline-block;
        }

        /* Button Customizations */
        div.stButton > button {
            border-radius: 12px !important;
            border: 1px solid #cbd5e1 !important;
            background: #ffffff !important;
            color: #334155 !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            padding: 8px 16px !important;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }
        div.stButton > button:hover {
            border-color: #6366f1 !important;
            color: #4338ca !important;
            background: #f5f3ff !important;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15) !important;
            transform: translateY(-1px);
        }

        /* Sidebar Styling */
        .sidebar-stat-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )


def render_header():
    """Renders hero header banner."""
    st.markdown(
        """
        <div class="hero-banner">
            <div class="hero-title">
                🌤️ MediBuddy Weather Advisory Support Bot
            </div>
            <div class="hero-subtitle">
                Deterministic, Policy-Grounded Weather Safety Assistant for Outdoor Suitability & Risk Advisory
            </div>
            <div class="hero-badges">
                <span class="hero-badge">🔒 100% Grounded Policy Engine</span>
                <span class="hero-badge">⚡ LangGraph State Machine</span>
                <span class="hero-badge">📡 Open-Meteo Live API</span>
                <span class="hero-badge">🛡️ Zero Advice Hallucination</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_welcome_card():
    """Renders interactive welcome state when chat history is empty."""
    st.markdown(
        """
        <div class="welcome-card">
            <div class="welcome-title">👋 Welcome to MediBuddy Weather Advisory Support!</div>
            <div class="welcome-desc">
                Ask any question regarding outdoor activities, road trips, vulnerable group safety (toddlers/seniors), or travel plans. 
                Our engine automatically fetches live weather data for the location and checks it against 15 strict health & safety SOPs.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def process_query(user_input: str):
    """Processes query through LangGraph state graph and updates session state."""
    if len(user_input) > MAX_INPUT_LENGTH:
        st.error(f"⚠️ Your question is too long ({len(user_input)} characters). Maximum allowed length is {MAX_INPUT_LENGTH} characters.")
        return

    # Add user message
    st.session_state["messages"].append({"role": "user", "content": user_input})

    # Process with LangGraph
    graph_app = get_graph_app()
    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}

    try:
        with st.spinner("🔍 Resolving location & analyzing live weather SOPs..."):
            result = graph_app.invoke(
                {"user_query": user_input},
                config=config
            )
        answer = result.get("answer", "I could not process your request at this time.")

        # Format trace metadata safely
        geo = result.get("geo") or {}
        primary = result.get("primary_sop") or {}
        secondaries = result.get("secondary_sops") or []
        trace_nodes = result.get("trace") or []
        agg_metrics = result.get("aggregated_metrics") or {}

        primary_evidence = primary.get("evidence_numbers", {}) if primary else {}

        trace_data = {
            "Resolved Location": geo.get("display_name", geo.get("name", "Unknown")),
            "Coordinates": f"{geo.get('latitude', 'N/A')}, {geo.get('longitude', 'N/A')}",
            "Graph Nodes Visited": trace_nodes,
            "Primary SOP Matched": primary.get("sop_id", "None") if primary else "None",
            "Primary SOP Title": primary.get("title", "None") if primary else "None",
            "Secondary SOPs": [s.get("sop_id") for s in secondaries] if secondaries else [],
            "Primary Evidence Numbers": primary_evidence,
            "Complete 150 Metric Payload": agg_metrics
        }

        # Save assistant message & trace
        asst_idx = len(st.session_state["messages"])
        st.session_state["messages"].append({"role": "assistant", "content": answer})
        st.session_state["decision_traces"][asst_idx] = trace_data

    except Exception as e:
        logger.error(f"Unhandled Streamlit error: {e}", exc_info=True)
        friendly_err = "An error occurred while evaluating your weather advisory request. Please try asking again or check your location."
        st.session_state["messages"].append({"role": "assistant", "content": friendly_err})


def main():
    st.set_page_config(
        page_title="MediBuddy Weather Advisory Support Bot",
        page_icon="🌤️",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    apply_custom_css()

    # Initialize session state variables
    if "thread_id" not in st.session_state:
        st.session_state["thread_id"] = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "decision_traces" not in st.session_state:
        st.session_state["decision_traces"] = {}
    if "pending_query" not in st.session_state:
        st.session_state["pending_query"] = None

    # Handle pending preset query click if present
    if st.session_state["pending_query"]:
        query_to_run = st.session_state["pending_query"]
        st.session_state["pending_query"] = None
        process_query(query_to_run)
        st.rerun()

    # Sidebar layout
    with st.sidebar:
        st.markdown("## 🌤️ MediBuddy Advisory")
        st.caption("Deterministic Weather Safety & Policy Assistant")

        st.markdown("---")

        # Session Status Card
        num_msgs = len(st.session_state["messages"])
        st.markdown(
            f"""
            <div class="sidebar-stat-card">
                <div style="font-size:11px; color:#64748b; font-weight:700; text-transform:uppercase;">Session Status</div>
                <div style="font-size:13px; font-weight:600; color:#1e293b; margin-top:4px;">ID: <code>{st.session_state['thread_id'][:8]}</code></div>
                <div style="font-size:12px; color:#475569; margin-top:4px;">Turn Memory: <b>{num_msgs} / {MAX_SESSION_MESSAGES}</b> msgs</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("🔄 New Session", use_container_width=True):
                st.session_state["thread_id"] = str(uuid.uuid4())
                st.session_state["messages"] = []
                st.session_state["decision_traces"] = {}
                st.session_state["pending_query"] = None
                st.rerun()
        with col_s2:
            if st.button("🎲 Random Test", use_container_width=True):
                rand_preset = random.choice(ALL_PRESETS)
                st.session_state["pending_query"] = rand_preset["query"]
                st.rerun()

        st.markdown("---")

        # Live Weather Quick Inspector Widget
        with st.expander("🌐 Quick City Weather Inspector"):
            st.caption("Directly lookup live weather metrics for any city via Open-Meteo:")
            insp_city = st.text_input("Enter city name:", value="Bhopal", key="quick_insp_city")
            if st.button("Check Weather Now", use_container_width=True):
                try:
                    geo_info = geocode_location(insp_city)
                    if geo_info:
                        w_data = fetch_weather(geo_info["latitude"], geo_info["longitude"], {"temperature_2m", "wind_speed_10m", "precipitation"})
                        curr = w_data.get("current", {}) if w_data else {}
                        st.success(f"**{geo_info['name']}**, {geo_info.get('country', '')}")
                        col_m1, col_m2 = st.columns(2)
                        col_m1.metric("Temperature", f"{curr.get('temperature_2m', 'N/A')} °C")
                        col_m2.metric("Wind Speed", f"{curr.get('wind_speed_10m', 'N/A')} km/h")
                        col_m3, col_m4 = st.columns(2)
                        col_m3.metric("Precipitation", f"{curr.get('precipitation', 'N/A')} mm")
                        col_m4.metric("Precip Prob", f"{curr.get('precipitation_probability', 'N/A')} %")
                    else:
                        st.error(f"Could not find weather data for '{insp_city}'.")
                except Exception as ex:
                    st.error(f"Error fetching weather: {ex}")

        st.markdown("---")

        # Active SOP Directory Expander
        with st.expander("📚 Active SOP Directory (15 Rules)"):
            st.caption("All outdoor recommendations strictly enforce parameters from these 15 SOP policies:")
            for sop_item in SOP_DIRECTORY:
                st.markdown(f"**{sop_item['icon']} `{sop_item['id']}`**: {sop_item['name']}")

        st.markdown("---")
        st.markdown(
            "### 🔒 Core Guardrails\n"
            "- **Policy Grounded**: 100% of advice comes strictly from written SOPs.\n"
            "- **LLM Constrained**: LLM is a phrasing engine; thresholds are deterministic.\n"
            "- **API Grounded**: Numbers verified against live Open-Meteo payload.\n"
            "- **Zero Advice Hallucination**: Failed validation triggers fallback response."
        )

    # Render Main Body
    render_header()

    # Show Welcome Card if no messages yet
    if len(st.session_state["messages"]) == 0:
        render_welcome_card()

    # Render Preset Sample Scenarios by Category
    st.markdown("<div style=\"font-size:14px; font-weight:700; color:#1e293b; margin-bottom:6px;\">💡 Instant Sample Scenarios (Click any card to ask)</div>", unsafe_allow_html=True)
    
    preset_tabs = st.tabs(list(PRESET_CATEGORIES.keys()))
    for tab, (cat_name, presets) in zip(preset_tabs, PRESET_CATEGORIES.items()):
        with tab:
            cols = st.columns(len(presets))
            for p_idx, preset in enumerate(presets):
                with cols[p_idx]:
                    if st.button(preset["label"], key=f"btn_{cat_name}_{p_idx}", use_container_width=True):
                        st.session_state["pending_query"] = preset["query"]
                        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # Render chat history
    for idx, msg in enumerate(st.session_state["messages"]):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Display decision trace expander for assistant messages if present
            if msg["role"] == "assistant" and idx in st.session_state["decision_traces"]:
                trace_info = st.session_state["decision_traces"][idx]
                
                with st.expander("🔍 Decision Trace & Policy Evidence"):
                    trace_tab1, trace_tab2, trace_tab3 = st.tabs([
                        "📋 SOP & Execution Path", 
                        "🎯 Verified Evidence Metrics", 
                        "📊 Raw Weather Payload (150 Metrics)"
                    ])

                    with trace_tab1:
                        loc = trace_info.get("Resolved Location", "Unknown")
                        coords = trace_info.get("Coordinates", "N/A")
                        p_sop = trace_info.get("Primary SOP Matched", "None")
                        p_title = trace_info.get("Primary SOP Title", "None")
                        s_sops = ", ".join(trace_info.get("Secondary SOPs", [])) or "None"
                        nodes = " ➔ ".join([str(n) for n in trace_info.get("Graph Nodes Visited", [])])

                        st.markdown(
                            f"""
                            <div class="trace-card">
                                <div class="trace-grid">
                                    <div class="trace-item"><div class="trace-label">Resolved Location</div><div class="trace-val">{loc}</div></div>
                                    <div class="trace-item"><div class="trace-label">GPS Coordinates</div><div class="trace-val">{coords}</div></div>
                                    <div class="trace-item"><div class="trace-label">Primary SOP ID</div><div class="trace-val"><code>{p_sop}</code></div></div>
                                    <div class="trace-item"><div class="trace-label">Primary SOP Title</div><div class="trace-val">{p_title}</div></div>
                                    <div class="trace-item"><div class="trace-label">Secondary SOPs</div><div class="trace-val"><code>{s_sops}</code></div></div>
                                </div>
                                <div class="trace-label" style="margin-top:8px;">Execution Path Visited</div>
                                <div style="font-family:monospace; font-size:12.5px; color:#334155; background:#ffffff; padding:8px 12px; border-radius:8px; border:1px solid #e2e8f0; margin-top:4px;">{nodes}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

                    with trace_tab2:
                        primary_ev = trace_info.get("Primary Evidence Numbers", {})
                        if primary_ev:
                            st.markdown("**Exact Weather Evidence Extracted for Policy Evaluation:**")
                            ev_cols = st.columns(min(len(primary_ev), 4) if primary_ev else 1)
                            for key_idx, (ev_key, ev_val) in enumerate(primary_ev.items()):
                                col_target = ev_cols[key_idx % len(ev_cols)]
                                col_target.metric(label=ev_key.replace(".", " ").title(), value=str(ev_val))
                            st.json(primary_ev)
                        else:
                            st.info("No specific primary SOP numerical threshold triggered (Out of scope or standard weather).")

                    with trace_tab3:
                        st.caption("Live pre-computed weather metrics aggregated across 8 time windows for exact SOP evaluation:")
                        st.json(trace_info.get("Complete 150 Metric Payload", {}))

    # Message limit check
    if len(st.session_state["messages"]) >= MAX_SESSION_MESSAGES:
        st.warning("⚠️ You have reached the maximum 20 messages for this chat session. Click **'🔄 New Session'** in the sidebar to start fresh.")
        return

    # Chat Input
    user_input = st.chat_input("Ask any outdoor activity, travel, or weather safety question...")
    if user_input:
        process_query(user_input)
        st.rerun()


if __name__ == "__main__":
    main()

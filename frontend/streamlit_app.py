"""
streamlit_app.py: Streamlit frontend for MediBuddy Weather-Advisory Support Bot.
Features conversational chat, thread session memory, collapsible Decision Trace expander,
input/session caps, st.secrets fallback, and clean error handling.
"""
import sys
import uuid
import logging
from pathlib import Path
import streamlit as st

# Ensure app modules are importable
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.graph import create_advisory_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("streamlit_app")

# Abuse protection caps
MAX_INPUT_LENGTH = 500
MAX_SESSION_MESSAGES = 20


@st.cache_resource
def get_graph_app():
    """Cache the compiled LangGraph workflow instance across reruns."""
    return create_advisory_graph()


def main():
    st.set_page_config(
        page_title="MediBuddy Weather Advisory Support Bot",
        page_icon="🌤️",
        layout="wide"
    )

    # Initialize session state variables
    if "thread_id" not in st.session_state:
        st.session_state["thread_id"] = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "decision_traces" not in st.session_state:
        st.session_state["decision_traces"] = {}

    # Sidebar layout
    with st.sidebar:
        st.title("🌤️ MediBuddy Advisory")
        st.caption("Policy-Driven Outdoor Weather Safety Assistant")

        st.markdown("---")
        st.write(f"**Session ID**: `{st.session_state['thread_id'][:8]}...`")
        st.write(f"**Messages**: {len(st.session_state['messages'])} / {MAX_SESSION_MESSAGES}")

        if st.button("🔄 New Session", use_container_width=True):
            st.session_state["thread_id"] = str(uuid.uuid4())
            st.session_state["messages"] = []
            st.session_state["decision_traces"] = {}
            st.rerun()

        st.markdown("---")
        st.markdown(
            "### 🔒 Safety Principles\n"
            "- **Policy Grounded**: 100% advice comes from written SOPs.\n"
            "- **LLM Constrained**: The model never invents advice or numbers.\n"
            "- **API Validated**: Weather figures are verified against Open-Meteo."
        )

    st.title("MediBuddy Weather-Advisory Support Bot")
    st.write("Ask any outdoor activity, travel, or event safety question (e.g. *'Is it safe to cycle in Bhopal today?'* or *'Can I take my kid to the park in Mumbai?'*).")

    # Render chat history
    for idx, msg in enumerate(st.session_state["messages"]):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            # Display decision trace expander for assistant messages if present
            if msg["role"] == "assistant" and idx in st.session_state["decision_traces"]:
                trace_info = st.session_state["decision_traces"][idx]
                with st.expander("🔍 Decision Trace & Policy Evidence"):
                    st.json(trace_info)

    # Message limit check
    if len(st.session_state["messages"]) >= MAX_SESSION_MESSAGES:
        st.warning("⚠️ You have reached the maximum 20 messages for this chat session. Please click **'New Session'** in the sidebar to start a fresh thread.")
        return

    # Chat Input
    user_input = st.chat_input("Type your outdoor activity safety question...")
    if user_input:
        # Abuse protection: Input length check
        if len(user_input) > MAX_INPUT_LENGTH:
            st.error(f"⚠️ Your question is too long ({len(user_input)} characters). Maximum allowed length is {MAX_INPUT_LENGTH} characters.")
            return

        # Add user message
        st.session_state["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Process with LangGraph graph
        graph_app = get_graph_app()
        config = {"configurable": {"thread_id": st.session_state["thread_id"]}}

        with st.chat_message("assistant"):
            with st.spinner("Fetching live weather and evaluating policy SOPs..."):
                try:
                    result = graph_app.invoke(
                        {"user_query": user_input},
                        config=config
                    )
                    answer = result.get("answer", "I could not process your request at this time.")

                    # Format trace metadata
                    geo = result.get("geo", {})
                    primary = result.get("primary_sop", {})
                    secondaries = result.get("secondary_sops", [])
                    trace_nodes = result.get("trace", [])
                    agg_metrics = result.get("aggregated_metrics", {})

                    trace_data = {
                        "Resolved Location": geo.get("display_name", geo.get("name", "Unknown")),
                        "Graph Nodes Visited": trace_nodes,
                        "Primary SOP Matched": primary.get("sop_id", "None") if primary else "None",
                        "Primary SOP Title": primary.get("title", "None") if primary else "None",
                        "Secondary SOPs": [s.get("sop_id") for s in secondaries] if secondaries else [],
                        "Raw Weather Numbers": primary.get("evidence_numbers", agg_metrics) if primary else agg_metrics,
                    }

                    st.markdown(answer)
                    with st.expander("🔍 Decision Trace & Policy Evidence"):
                        st.json(trace_data)

                    # Save assistant message & trace
                    asst_idx = len(st.session_state["messages"])
                    st.session_state["messages"].append({"role": "assistant", "content": answer})
                    st.session_state["decision_traces"][asst_idx] = trace_data

                except Exception as e:
                    logger.error(f"Unhandled Streamlit error: {e}", exc_info=True)
                    friendly_err = "An error occurred while evaluating your weather advisory request. Please try asking again or check your location."
                    st.error(friendly_err)
                    st.session_state["messages"].append({"role": "assistant", "content": friendly_err})


if __name__ == "__main__":
    main()

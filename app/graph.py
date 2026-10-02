"""
graph.py: LangGraph definition, nodes, conditional edges, and MemorySaver checkpointer.
Full branching workflow with explicit failure, clarification, no-trigger, retry, and fallback nodes.
"""
from typing import Dict, Any, List, Optional
import logging
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage, HumanMessage

from app.state import AdvisoryState, SessionContext
from app.config import SOPS_DIR
from app.sop_loader import (
    load_all_sops,
    get_required_weather_metrics,
    get_taxonomy_tags,
)
from app.geo_weather import geocode_location, fetch_weather, aggregate_metrics
from app.sop_engine import evaluate_threshold_sop, evaluate_fuzzy_sop
from app.resolver import resolve_sop_conflicts
from app.intent import parse_user_intent, get_llm
from app.compose import compose_answer_with_llm, deterministic_render_fallback, fill_guidance_placeholders
from app.validators import validate_number_grounding, validate_sop_citations

logger = logging.getLogger(__name__)


def parse_intent_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 1: Parse user intent into structured enums with context inheritance."""
    messages = state.get("messages", [])
    user_query = state.get("user_query")
    if not user_query and messages:
        user_query = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])

    trace = list(state.get("trace", []))
    trace.append("parse_intent")

    session_ctx = state.get("session_context", {})
    sops = load_all_sops(SOPS_DIR)
    activities, audiences = get_taxonomy_tags(sops)

    llm = get_llm()
    intent = parse_user_intent(
        user_query=user_query or "",
        available_activities=activities,
        available_audiences=audiences,
        session_context=session_ctx,
        llm=llm
    )

    return {
        "intent": intent.model_dump(),
        "user_query": user_query,
        "trace": trace,
    }


def route_after_intent(state: AdvisoryState) -> str:
    """Conditional edge after parse_intent."""
    intent = state.get("intent", {})
    in_scope = intent.get("in_scope", True)
    location_text = intent.get("location_text")
    activity_tag = intent.get("activity_tag")

    if not in_scope or not activity_tag:
        return "no_guidance"

    if not location_text or not location_text.strip():
        return "ask_clarification"

    return "geocode"


def geocode_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 3: Geocode location via Open-Meteo."""
    trace = list(state.get("trace", []))
    trace.append("geocode")

    intent = state.get("intent", {})
    location_text = intent.get("location_text", "")

    geo_result = geocode_location(location_text)
    if not geo_result:
        return {
            "geo": None,
            "error": "Geocoding failed or empty result",
            "trace": trace,
        }

    return {
        "geo": geo_result,
        "trace": trace,
    }


def route_after_geocode(state: AdvisoryState) -> str:
    """Conditional edge after geocode."""
    geo = state.get("geo")
    if not geo:
        return "failure_node"
    return "fetch_weather"


def fetch_weather_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 4: Dynamic weather fetch & window aggregation."""
    trace = list(state.get("trace", []))
    trace.append("fetch_weather")

    geo = state.get("geo", {})
    lat = geo.get("latitude")
    lon = geo.get("longitude")

    sops = load_all_sops(SOPS_DIR)
    required_metrics = get_required_weather_metrics(sops)

    raw_weather = fetch_weather(lat, lon, required_metrics)
    if not raw_weather:
        return {
            "weather": None,
            "error": "Weather API fetch failed or timed out",
            "trace": trace,
        }

    intent = state.get("intent", {})
    time_ref = intent.get("time_ref", "today")

    aggregated = aggregate_metrics(raw_weather, time_ref, required_metrics)

    return {
        "weather": raw_weather,
        "aggregated_metrics": aggregated,
        "trace": trace,
    }


def route_after_fetch(state: AdvisoryState) -> str:
    """Conditional edge after fetch_weather."""
    weather = state.get("weather")
    if not weather:
        return "failure_node"
    return "match_sops"


def match_sops_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 5: Filter & evaluate SOPs (threshold deterministically, fuzzy via LLM judge)."""
    trace = list(state.get("trace", []))
    trace.append("match_sops")

    intent = state.get("intent", {})
    act_tag = intent.get("activity_tag", "*")
    aud_tag = intent.get("audience_tag", "*")

    aggregated = state.get("aggregated_metrics", {})
    sops = load_all_sops(SOPS_DIR)
    llm = get_llm()

    evaluated: List[Dict[str, Any]] = []
    triggered: List[Dict[str, Any]] = []

    for sop in sops:
        sop_acts = sop.applies_to.activities
        sop_auds = sop.applies_to.audiences

        # Activity matching: "*" or exact match
        act_match = ("*" in sop_acts) or (act_tag in sop_acts)
        aud_match = ("*" in sop_auds) or (aud_tag in sop_auds) or (aud_tag is None)

        if not act_match or not aud_match:
            continue

        match_type = sop.match.get("type")
        if match_type == "threshold":
            res = evaluate_threshold_sop(sop, aggregated)
        elif match_type == "fuzzy":
            res = evaluate_fuzzy_sop(sop, aggregated, llm=llm)
        else:
            continue

        res["applies_to"] = sop.applies_to.model_dump()
        evaluated.append(res)
        if res.get("triggered") and res.get("valid_eval"):
            triggered.append(res)

    return {
        "evaluated_sops": evaluated,
        "triggered_sops": triggered,
        "trace": trace,
    }


def route_after_match(state: AdvisoryState) -> str:
    """Conditional edge after match_sops."""
    evaluated = state.get("evaluated_sops", [])
    triggered = state.get("triggered_sops", [])

    if not evaluated:
        return "no_guidance"

    if not triggered:
        return "no_trigger_node"

    return "resolve_conflicts"


def resolve_conflicts_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 7: Conflict resolution & ranking."""
    trace = list(state.get("trace", []))
    trace.append("resolve_conflicts")

    triggered = state.get("triggered_sops", [])
    intent = state.get("intent", {})
    act_tag = intent.get("activity_tag", "*")
    aud_tag = intent.get("audience_tag", "*")

    primary, secondaries = resolve_sop_conflicts(triggered, act_tag, aud_tag)

    return {
        "primary_sop": primary,
        "secondary_sops": secondaries,
        "trace": trace,
    }


def compose_answer_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 8: LLM answer composition."""
    trace = list(state.get("trace", []))
    trace.append("compose_answer")

    attempts = state.get("compose_attempts", 0) + 1

    primary = state.get("primary_sop", {})
    secondaries = state.get("secondary_sops", [])
    aggregated = state.get("aggregated_metrics", {})
    geo = state.get("geo", {})
    location_name = geo.get("display_name", geo.get("name", "your location"))

    intent = state.get("intent", {})
    time_ref = intent.get("time_ref", "today")
    session_ctx = state.get("session_context", {})

    llm = get_llm()
    answer_text = compose_answer_with_llm(
        primary_sop=primary,
        secondary_sops=secondaries,
        aggregated_metrics=aggregated,
        location_name=location_name,
        time_ref=time_ref,
        session_context=session_ctx,
        llm=llm
    )

    return {
        "answer": answer_text,
        "compose_attempts": attempts,
        "trace": trace,
    }


def validate_answer_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 9: Number grounding & citation validator node."""
    trace = list(state.get("trace", []))
    trace.append("validate_answer")

    answer = state.get("answer", "")
    aggregated = state.get("aggregated_metrics", {})
    primary = state.get("primary_sop", {})
    secondaries = state.get("secondary_sops", [])

    primary_id = primary.get("sop_id", "")
    matched_ids = [s.get("sop_id") for s in state.get("triggered_sops", [])]

    sops = load_all_sops(SOPS_DIR)
    all_known_ids = {s.id for s in sops}

    # Validate numbers
    num_valid, ungrounded = validate_number_grounding(answer, aggregated)
    # Validate citations
    cit_valid, cit_reason = validate_sop_citations(answer, primary_id, matched_ids, all_known_ids)

    is_valid = num_valid and cit_valid
    error_msg = None
    if not num_valid:
        error_msg = f"Ungrounded numbers detected: {ungrounded}"
    elif not cit_valid:
        error_msg = f"Citation validation failed: {cit_reason}"

    return {
        "error": error_msg,
        "trace": trace,
    }


def route_after_validation(state: AdvisoryState) -> str:
    """Conditional edge after validate_answer."""
    error = state.get("error")
    attempts = state.get("compose_attempts", 1)

    if not error:
        return "update_session"

    if attempts < 2:
        return "compose_answer"  # Retry composition once

    return "deterministic_render"  # Fallback on 2nd failure


def deterministic_render_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node for deterministic template fallback when LLM validation fails twice."""
    trace = list(state.get("trace", []))
    trace.append("deterministic_render")

    primary = state.get("primary_sop", {})
    secondaries = state.get("secondary_sops", [])
    aggregated = state.get("aggregated_metrics", {})
    geo = state.get("geo", {})
    location_name = geo.get("display_name", geo.get("name", "your location"))
    intent = state.get("intent", {})
    time_ref = intent.get("time_ref", "today")

    fallback_text = deterministic_render_fallback(
        primary_sop=primary,
        secondary_sops=secondaries,
        aggregated_metrics=aggregated,
        location_name=location_name,
        time_ref=time_ref
    )

    return {
        "answer": fallback_text,
        "trace": trace,
    }


def failure_node(state: AdvisoryState) -> Dict[str, Any]:
    """Deterministic failure node when geocoding or weather API fails."""
    trace = list(state.get("trace", []))
    trace.append("failure_node")

    ans = "I couldn't get live weather for that location. (no SOP applied: weather data unavailable)"
    return {
        "answer": ans,
        "trace": trace,
    }


def no_guidance_node(state: AdvisoryState) -> Dict[str, Any]:
    """Deterministic node when query is off-topic or activity is unmapped."""
    trace = list(state.get("trace", []))
    trace.append("no_guidance")

    ans = "We don't have guidance for that."
    return {
        "answer": ans,
        "trace": trace,
    }


def ask_clarification_node(state: AdvisoryState) -> Dict[str, Any]:
    """Deterministic node when location is missing."""
    trace = list(state.get("trace", []))
    trace.append("ask_clarification")

    ans = "Which city or location would you like the weather advisory for?"
    return {
        "answer": ans,
        "trace": trace,
    }


def no_trigger_node(state: AdvisoryState) -> Dict[str, Any]:
    """Deterministic node when activity is covered but 0 risk SOPs triggered."""
    trace = list(state.get("trace", []))
    trace.append("no_trigger_node")

    intent = state.get("intent", {})
    act = intent.get("activity_tag", "outdoor activities")
    geo = state.get("geo", {})
    location_name = geo.get("display_name", geo.get("name", "your location"))

    aggregated = state.get("aggregated_metrics", {})
    key_numbers = []
    for k in ["temperature_2m.max.today", "wind_speed_10m.max.today", "precipitation.sum.today", "precipitation_probability.max.today"]:
        if k in aggregated and aggregated[k] is not None:
            k_clean = k.split(".")[0]
            key_numbers.append(f"{k_clean}: {aggregated[k]}")

    numbers_str = ", ".join(key_numbers) if key_numbers else "current weather readings"

    ans = f"None of our SOPs flagged a risk for {act} in {location_name} at current readings: ({numbers_str}). That's not a guarantee of safety, please use your own judgment and check official alerts."
    return {
        "answer": ans,
        "trace": trace,
    }


def update_session_node(state: AdvisoryState) -> Dict[str, Any]:
    """Node 12: Updates session context for multi-turn conversational memory."""
    trace = list(state.get("trace", []))
    trace.append("update_session")

    intent = state.get("intent", {})
    geo = state.get("geo", {})
    primary = state.get("primary_sop", {})
    aggregated = state.get("aggregated_metrics", {})
    answer = state.get("answer", "")

    session_ctx = dict(state.get("session_context", {}))

    if geo:
        session_ctx["last_location"] = geo.get("name")
        session_ctx["last_coords"] = {"latitude": geo.get("latitude"), "longitude": geo.get("longitude")}
    if intent.get("activity_tag"):
        session_ctx["last_activity"] = intent.get("activity_tag")
    if intent.get("audience_tag"):
        session_ctx["last_audience"] = intent.get("audience_tag")
    if intent.get("time_ref"):
        session_ctx["last_time_ref"] = intent.get("time_ref")

    if primary:
        session_ctx["last_decision_log"] = {
            "primary_sop_id": primary.get("sop_id"),
            "severity": primary.get("severity"),
            "verdict": primary.get("verdict", "triggered"),
            "key_numbers": primary.get("evidence_numbers", {})
        }

    # Append assistant response to messages
    messages = list(state.get("messages", []))
    messages.append(AIMessage(content=answer))

    return {
        "session_context": session_ctx,
        "messages": messages,
        "trace": trace,
    }


def create_advisory_graph():
    """Builds and compiles the LangGraph StateGraph with MemorySaver checkpointer."""
    workflow = StateGraph(AdvisoryState)

    # Add Nodes
    workflow.add_node("parse_intent", parse_intent_node)
    workflow.add_node("geocode", geocode_node)
    workflow.add_node("fetch_weather", fetch_weather_node)
    workflow.add_node("match_sops", match_sops_node)
    workflow.add_node("resolve_conflicts", resolve_conflicts_node)
    workflow.add_node("compose_answer", compose_answer_node)
    workflow.add_node("validate_answer", validate_answer_node)
    workflow.add_node("deterministic_render", deterministic_render_node)
    workflow.add_node("failure_node", failure_node)
    workflow.add_node("no_guidance", no_guidance_node)
    workflow.add_node("ask_clarification", ask_clarification_node)
    workflow.add_node("no_trigger_node", no_trigger_node)
    workflow.add_node("update_session", update_session_node)

    # Set Edges
    workflow.add_edge(START, "parse_intent")

    workflow.add_conditional_edges(
        "parse_intent",
        route_after_intent,
        {
            "no_guidance": "no_guidance",
            "ask_clarification": "ask_clarification",
            "geocode": "geocode"
        }
    )

    workflow.add_conditional_edges(
        "geocode",
        route_after_geocode,
        {
            "failure_node": "failure_node",
            "fetch_weather": "fetch_weather"
        }
    )

    workflow.add_conditional_edges(
        "fetch_weather",
        route_after_fetch,
        {
            "failure_node": "failure_node",
            "match_sops": "match_sops"
        }
    )

    workflow.add_conditional_edges(
        "match_sops",
        route_after_match,
        {
            "no_guidance": "no_guidance",
            "no_trigger_node": "no_trigger_node",
            "resolve_conflicts": "resolve_conflicts"
        }
    )

    workflow.add_edge("resolve_conflicts", "compose_answer")
    workflow.add_edge("compose_answer", "validate_answer")

    workflow.add_conditional_edges(
        "validate_answer",
        route_after_validation,
        {
            "update_session": "update_session",
            "compose_answer": "compose_answer",
            "deterministic_render": "deterministic_render"
        }
    )

    workflow.add_edge("deterministic_render", "update_session")
    workflow.add_edge("failure_node", END)
    workflow.add_edge("no_guidance", END)
    workflow.add_edge("ask_clarification", END)
    workflow.add_edge("no_trigger_node", END)
    workflow.add_edge("update_session", END)

    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app


if __name__ == "__main__":
    # Command-line helper to print graph structure and mermaid diagram
    graph_app = create_advisory_graph()
    print("Graph Compiled Successfully!")
    try:
        print("\n--- MERMAID DIAGRAM ---")
        print(graph_app.get_graph().draw_mermaid())
    except Exception as e:
        print(f"Mermaid generation note: {e}")

"""
state.py: TypedDict State schema for LangGraph agent.
Tracks conversation history, session context, intermediate decision variables, trace, and validation state.
"""
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langgraph.graph.message import add_messages


class SessionContext(TypedDict, total=False):
    last_location: Optional[str]
    last_coords: Optional[Dict[str, float]]
    last_activity: Optional[str]
    last_audience: Optional[str]
    last_time_ref: Optional[str]
    last_decision_log: Optional[Dict[str, Any]]


class AdvisoryState(TypedDict, total=False):
    messages: Annotated[List[Any], add_messages]
    session_context: SessionContext
    user_query: str
    intent: Optional[Dict[str, Any]]
    geo: Optional[Dict[str, Any]]
    weather: Optional[Dict[str, Any]]
    aggregated_metrics: Optional[Dict[str, Any]]
    evaluated_sops: Optional[List[Dict[str, Any]]]
    triggered_sops: Optional[List[Dict[str, Any]]]
    primary_sop: Optional[Dict[str, Any]]
    secondary_sops: Optional[List[Dict[str, Any]]]
    answer: str
    trace: List[str]
    compose_attempts: int
    error: Optional[str]

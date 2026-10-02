"""
resolver.py: Conflict resolution and ranking engine for matched SOPs.
Ranks triggered SOPs deterministically by:
1. Overrides: "all"
2. Severity (danger > warning > caution > info)
3. Priority integer (higher wins)
4. Specificity (specific activity tag > wildcard "*")
"""
from typing import List, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

SEVERITY_RANK = {
    "danger": 4,
    "warning": 3,
    "caution": 2,
    "info": 1
}


def calculate_specificity(sop_result: Dict[str, Any], target_activity: str, target_audience: str) -> int:
    """Calculates specificity score (0 to 2) based on exact tag matches vs '*' wildcards."""
    score = 0
    applies_to = sop_result.get("applies_to", {})
    activities = applies_to.get("activities", ["*"]) if isinstance(applies_to, dict) else ["*"]
    audiences = applies_to.get("audiences", ["*"]) if isinstance(applies_to, dict) else ["*"]

    if target_activity and target_activity in activities and target_activity != "*":
        score += 1
    if target_audience and target_audience in audiences and target_audience != "*":
        score += 1
    return score


def sort_key_sop(sop: Dict[str, Any], activity: str = "*", audience: str = "*") -> Tuple[int, int, int, int]:
    """Generates sort tuple for ranking SOPs."""
    is_override = 1 if sop.get("overrides") == "all" else 0
    sev_score = SEVERITY_RANK.get(sop.get("severity", "info"), 1)
    priority = sop.get("priority", 50)
    spec_score = calculate_specificity(sop, activity, audience)

    return (is_override, sev_score, priority, spec_score)


def resolve_sop_conflicts(
    triggered_sops: List[Dict[str, Any]],
    target_activity: str = "*",
    target_audience: str = "*"
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Ranks triggered SOPs and separates them into Primary SOP and Secondary SOPs (up to 2).
    Returns (primary_sop, secondary_sops_list).
    """
    if not triggered_sops:
        raise ValueError("No triggered SOPs provided to resolver")

    # Sort in descending order of priority
    sorted_sops = sorted(
        triggered_sops,
        key=lambda s: sort_key_sop(s, target_activity, target_audience),
        reverse=True
    )

    primary_sop = sorted_sops[0]
    secondary_sops = sorted_sops[1:3]  # Up to 2 secondary SOPs

    return primary_sop, secondary_sops

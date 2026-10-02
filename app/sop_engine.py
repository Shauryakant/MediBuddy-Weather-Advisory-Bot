"""
sop_engine.py: Deterministic threshold condition evaluator and fuzzy LLM judge.
"""
from typing import Dict, Any, List, Tuple, Optional, Set
import logging
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from app.sop_loader import SOPModel
from app.config import LLM_PROVIDER, LLM_MODEL, get_secret_or_env

logger = logging.getLogger(__name__)


def compare_values(actual: Any, op: str, expected: Any) -> bool:
    """Evaluates comparison operator between actual value and expected value."""
    if actual is None:
        return False

    if op == ">":
        return float(actual) > float(expected)
    elif op == ">=":
        return float(actual) >= float(expected)
    elif op == "<":
        return float(actual) < float(expected)
    elif op == "<=":
        return float(actual) <= float(expected)
    elif op == "==":
        return float(actual) == float(expected)
    elif op == "in":
        if isinstance(expected, list):
            return actual in expected or int(actual) in [int(x) for x in expected if isinstance(x, (int, float, str)) and str(x).replace("-","").isdigit()]
        return actual == expected
    else:
        raise ValueError(f"Unsupported operator '{op}'")


def evaluate_condition_node(
    node: Dict[str, Any],
    aggregated_metrics: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], bool]:
    """
    Recursively evaluates a node in the threshold condition tree.
    Returns (triggered, evidence_dict, is_valid_eval).
    If a metric is missing/None, is_valid_eval is set to False.
    """
    evidence: Dict[str, Any] = {}

    if "metric" in node:
        metric = node["metric"]
        agg = node.get("agg", "value")
        window = node.get("window", "today")
        op = node.get("op", ">=")
        target_val = node["value"]

        key = f"{metric}.{agg}.{window}"
        actual_val = aggregated_metrics.get(key)

        if actual_val is None:
            # Metric missing or null in weather response
            return False, evidence, False

        evidence[key] = actual_val
        is_triggered = compare_values(actual_val, op, target_val)
        return is_triggered, evidence, True

    if "all_of" in node:
        children = node["all_of"]
        all_triggered = True
        all_valid = True
        for child in children:
            t, ev, v = evaluate_condition_node(child, aggregated_metrics)
            evidence.update(ev)
            if not v:
                all_valid = False
            if not t:
                all_triggered = False
        return (all_triggered and all_valid), evidence, all_valid

    if "any_of" in node:
        children = node["any_of"]
        any_triggered = False
        at_least_one_valid = False
        for child in children:
            t, ev, v = evaluate_condition_node(child, aggregated_metrics)
            evidence.update(ev)
            if v:
                at_least_one_valid = True
            if t and v:
                any_triggered = True
        return any_triggered, evidence, at_least_one_valid

    if "not" in node:
        t, ev, v = evaluate_condition_node(node["not"], aggregated_metrics)
        evidence.update(ev)
        if not v:
            return False, evidence, False
        return (not t), evidence, True

    return False, evidence, False


def evaluate_threshold_sop(
    sop: SOPModel,
    aggregated_metrics: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Evaluates a threshold SOP deterministically.
    Returns structured result dictionary.
    """
    match_tree = sop.match
    triggered, evidence, valid_eval = evaluate_condition_node(match_tree, aggregated_metrics)

    return {
        "sop_id": sop.id,
        "title": sop.title,
        "severity": sop.severity,
        "priority": sop.priority,
        "category": sop.category,
        "overrides": sop.overrides,
        "type": "threshold",
        "triggered": triggered,
        "valid_eval": valid_eval,
        "evidence_numbers": evidence,
        "guidance_template": sop.guidance,
    }


class FuzzyVerdictOutput(BaseModel):
    verdict: str  # "good", "mixed", or "poor"
    reason: str


def evaluate_fuzzy_sop(
    sop: SOPModel,
    aggregated_metrics: Dict[str, Any],
    llm: Any = None
) -> Dict[str, Any]:
    """
    Evaluates a fuzzy SOP using a schema-constrained LLM judge call.
    The LLM sees ONLY the rubric + evidence metrics and returns an enum verdict.
    """
    fuzzy_data = sop.match
    rubric = fuzzy_data.get("rubric", "")
    evidence_metrics = fuzzy_data.get("evidence_metrics", [])
    verdicts = fuzzy_data.get("verdicts", {})

    # Gather evidence numbers
    evidence: Dict[str, Any] = {}
    for k, v in aggregated_metrics.items():
        metric_name = k.split(".")[0]
        if metric_name in evidence_metrics:
            evidence[k] = v

    if not llm:
        # Fallback heuristic if LLM is not provided
        verdict = "mixed"
        reason = "Evaluated via default heuristic."
    else:
        judge_prompt = (
            "You are an impartial weather safety evaluator judging outdoor conditions against a strict rubric.\n"
            "You must output ONLY one of the following exact verdicts: 'good', 'mixed', or 'poor', along with a short reason.\n\n"
            f"RUBRIC:\n{rubric}\n\n"
            f"OBSERVED WEATHER EVIDENCE NUMBERS:\n{evidence}\n\n"
            "Evaluate the evidence against the rubric and select the appropriate verdict."
        )
        try:
            structured_llm = llm.with_structured_output(FuzzyVerdictOutput)
            response = structured_llm.invoke([SystemMessage(content=judge_prompt)])
            verdict = response.verdict.lower().strip()
            reason = response.reason
            if verdict not in verdicts:
                verdict = "mixed"
        except Exception as e:
            logger.warning(f"Structured output failed for {sop.id} ({e}), falling back to direct prompt parsing.")
            try:
                raw_resp = llm.invoke([SystemMessage(content=judge_prompt + "\n\nRespond clearly starting with your verdict word ('good', 'mixed', or 'poor') followed by a brief reason.")])
                content = str(raw_resp.content).lower().strip()
                if content.startswith("good") or "verdict: good" in content or "'good'" in content or '"good"' in content:
                    verdict = "good"
                elif content.startswith("poor") or "verdict: poor" in content or "'poor'" in content or '"poor"' in content:
                    verdict = "poor"
                else:
                    verdict = "mixed"
                reason = raw_resp.content.strip()
            except Exception as e2:
                logger.error(f"Fuzzy LLM judge fallback error for {sop.id}: {e2}")
                verdict = "mixed"
                reason = f"LLM evaluation fallback: {e2}"

    guidance_template = verdicts.get(verdict, list(verdicts.values())[0] if verdicts else sop.guidance)

    return {
        "sop_id": sop.id,
        "title": sop.title,
        "severity": sop.severity,
        "priority": sop.priority,
        "category": sop.category,
        "overrides": sop.overrides,
        "type": "fuzzy",
        "triggered": True,  # Fuzzy SOPs always produce a verdict & guidance
        "verdict": verdict,
        "reason": reason,
        "valid_eval": True,
        "evidence_numbers": evidence,
        "guidance_template": guidance_template,
    }

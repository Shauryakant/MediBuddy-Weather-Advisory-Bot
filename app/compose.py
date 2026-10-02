"""
compose.py: LLM answer composer and deterministic template fallback renderer.
Ensures responses are strictly grounded in policy guidance and Open-Meteo API numbers.
"""
from typing import Dict, Any, List, Optional
import logging
from langchain_core.messages import SystemMessage, HumanMessage
from app.intent import get_llm

logger = logging.getLogger(__name__)


def fill_guidance_placeholders(template: str, evidence_numbers: Dict[str, Any], aggregated_metrics: Dict[str, Any]) -> str:
    """
    Fills placeholders in guidance templates like {temperature_2m.max} or {precipitation.sum}
    with actual numbers from API metrics.
    """
    if not template:
        return ""

    filled = template
    merged = {}
    merged.update(evidence_numbers)
    merged.update(aggregated_metrics)

    for k, v in merged.items():
        if v is not None:
            k_short = ".".join(k.split(".")[:2]) if len(k.split(".")) >= 3 else k
            placeholder_exact = f"{{{k}}}"
            placeholder_short = f"{{{k_short}}}"

            filled = filled.replace(placeholder_exact, str(v))
            filled = filled.replace(placeholder_short, str(v))

    return filled


def deterministic_render_fallback(
    primary_sop: Dict[str, Any],
    secondary_sops: List[Dict[str, Any]],
    aggregated_metrics: Dict[str, Any],
    location_name: str,
    time_ref: str = "today"
) -> str:
    """
    Deterministic template-based response renderer used when LLM composition fails or fails validation.
    Builds reply strictly from YAML guidance text and API numbers without calling an LLM.
    """
    p_id = primary_sop.get("sop_id", "SOP-UNKNOWN")
    p_title = primary_sop.get("title", "")
    p_template = primary_sop.get("guidance_template", "")
    p_evidence = primary_sop.get("evidence_numbers", {})

    p_text = fill_guidance_placeholders(p_template, p_evidence, aggregated_metrics)

    lines = [
        f"For **{location_name}** ({time_ref}):",
        f"\n**[{p_id}] {p_title}**:\n{p_text}"
    ]

    if secondary_sops:
        lines.append("\n**Also applicable**:")
        for s in secondary_sops:
            s_id = s.get("sop_id")
            s_title = s.get("title")
            s_template = s.get("guidance_template", "")
            s_evidence = s.get("evidence_numbers", {})
            s_text = fill_guidance_placeholders(s_template, s_evidence, aggregated_metrics)
            lines.append(f"- **[{s_id}] {s_title}**: {s_text}")

    return "\n".join(lines)


def compose_answer_with_llm(
    primary_sop: Dict[str, Any],
    secondary_sops: List[Dict[str, Any]],
    aggregated_metrics: Dict[str, Any],
    location_name: str,
    time_ref: str = "today",
    session_context: Optional[Dict[str, Any]] = None,
    llm: Any = None
) -> str:
    """
    Phrases approved policy guidance and API numbers into a friendly answer using LLM.
    Raw user text is NOT passed into prompt.
    """
    if not llm:
        llm = get_llm()

    p_id = primary_sop.get("sop_id")
    p_title = primary_sop.get("title")
    p_template = primary_sop.get("guidance_template", "")
    p_evidence = primary_sop.get("evidence_numbers", {})
    p_guidance = fill_guidance_placeholders(p_template, p_evidence, aggregated_metrics)

    secondaries_formatted = []
    for s in secondary_sops:
        s_id = s.get("sop_id")
        s_title = s.get("title")
        s_template = s.get("guidance_template", "")
        s_evidence = s.get("evidence_numbers", {})
        s_text = fill_guidance_placeholders(s_template, s_evidence, aggregated_metrics)
        secondaries_formatted.append(f"[{s_id}] {s_title}: {s_text}")

    prior_decision_log = session_context.get("last_decision_log") if session_context else None

    # Filter numbers to keep prompt lightweight (< 400 tokens) for Groq/LLM TPM limits
    compact_numbers = {}
    compact_numbers.update(p_evidence)
    for s in secondary_sops:
        compact_numbers.update(s.get("evidence_numbers", {}))

    prompt_data = (
        "You are MediBuddy's Weather-Advisory Support Bot.\n"
        "Phrase a concise, helpful reply based ONLY on the approved policy guidance and API numbers below.\n\n"
        "STRICT REQUIREMENTS:\n"
        "1. You MUST cite the Primary SOP ID explicitly in your answer (e.g. '[SOP-TRV-001]').\n"
        "2. If secondary SOPs are listed, cite their SOP IDs under an 'Also applicable' section.\n"
        "3. Every numerical figure in your output MUST match numbers present in the provided policy guidance or allowed API metrics.\n"
        "4. DO NOT alter or replace numerical values present in the Primary Policy Guidance text (e.g., if guidance text says 33.4°C and 7.5, you MUST keep 33.4 and 7.5 exactly).\n"
        "5. Do NOT make up your own safety advice or numbers.\n"
        "6. If prior turn decision context is provided, ensure your response maintains consistency with prior turns.\n\n"
        f"LOCATION: {location_name}\n"
        f"TIME WINDOW: {time_ref}\n\n"
        f"PRIMARY POLICY GUIDANCE:\n"
        f"ID: {p_id}\n"
        f"Title: {p_title}\n"
        f"Guidance Text: {p_guidance}\n\n"
        f"SECONDARY POLICIES: {secondaries_formatted}\n\n"
        f"EVIDENCE NUMBERS: {compact_numbers}\n\n"
        f"PRIOR TURN DECISION LOG: {prior_decision_log}\n"
    )

    if not llm:
        return deterministic_render_fallback(primary_sop, secondary_sops, aggregated_metrics, location_name, time_ref)

    try:
        messages = [
            SystemMessage(content="You compose weather safety advice strictly from provided policy texts. Never invent facts."),
            HumanMessage(content=prompt_data)
        ]
        response = llm.invoke(messages)
        content = response.content.strip()
        return content
    except Exception as e:
        logger.error(f"Composer LLM exception: {e}")
        return deterministic_render_fallback(primary_sop, secondary_sops, aggregated_metrics, location_name, time_ref)

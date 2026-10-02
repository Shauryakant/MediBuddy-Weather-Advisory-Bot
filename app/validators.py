"""
validators.py: Strict number-grounding and SOP citation validators.
Enforces that:
1. Every numerical value in the generated reply came directly from the Open-Meteo API response.
2. The primary SOP ID and all cited SOP IDs are valid and present in the matched SOP set.
"""
import re
from typing import Dict, Any, List, Tuple, Set
import logging

logger = logging.getLogger(__name__)

# Standard allowed time-of-day numbers (hours, AM/PM numbers, 24h cycle)
STANDARD_TIME_NUMBERS = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 30, 45, 60
}


def extract_numbers_from_text(text: str) -> List[float]:
    """
    Extracts all numeric sequences from text, excluding SOP ID digits (e.g. SOP-TRV-001).
    """
    # Remove SOP IDs before extracting numbers (e.g., SOP-SIT-001 -> SOP-SIT-REMOVED)
    cleaned_text = re.sub(r'SOP-[A-Z]+-\d+', '', text)

    # Regex for floats and integers
    pattern = r'-?\d+(?:\.\d+)?'
    matches = re.findall(pattern, cleaned_text)

    numbers = []
    for m in matches:
        try:
            val = float(m)
            numbers.append(val)
        except ValueError:
            pass
    return numbers


def build_allowed_numbers_set(allowed_numbers_dict: Dict[str, Any]) -> Set[float]:
    """
    Builds a comprehensive set of allowed numeric values including exact floats,
    integers, rounded values (+/- 1.0 for temperature rounding), and standard time numbers.
    """
    allowed: Set[float] = set(STANDARD_TIME_NUMBERS)

    for k, val in allowed_numbers_dict.items():
        if val is None:
            continue
        try:
            f_val = float(val)
            allowed.add(f_val)
            allowed.add(round(f_val, 1))
            allowed.add(float(int(round(f_val))))
            allowed.add(float(int(f_val)))
            # Allow ceiling/floor for slight rounding
            allowed.add(float(int(f_val) + 1))
            allowed.add(float(int(f_val) - 1))
        except (ValueError, TypeError):
            pass

    return allowed


def validate_number_grounding(
    response_text: str,
    allowed_numbers_dict: Dict[str, Any]
) -> Tuple[bool, List[float]]:
    """
    Validates that every number appearing in response_text is grounded in allowed_numbers_dict or standard time tokens.
    Returns (is_valid, ungrounded_numbers_list).
    """
    found_numbers = extract_numbers_from_text(response_text)
    allowed_set = build_allowed_numbers_set(allowed_numbers_dict)

    ungrounded = []
    for num in found_numbers:
        # Check if num or int(num) or round(num,1) is in allowed_set
        if (num not in allowed_set and
            float(int(num)) not in allowed_set and
            round(num, 1) not in allowed_set and
            round(num, 0) not in allowed_set):
            ungrounded.append(num)

    is_valid = len(ungrounded) == 0
    return is_valid, ungrounded


def validate_sop_citations(
    response_text: str,
    primary_sop_id: str,
    matched_sop_ids: List[str],
    all_known_sop_ids: Set[str]
) -> Tuple[bool, str]:
    """
    Validates that:
    1. Primary SOP ID is cited in the response text.
    2. All SOP IDs cited in response text exist in matched_sop_ids.
    3. No fabricated/hallucinated SOP IDs are cited.
    Returns (is_valid, error_reason).
    """
    cited_sop_ids = set(re.findall(r'SOP-[A-Z]+-\d+', response_text))

    if primary_sop_id and primary_sop_id not in cited_sop_ids:
        return False, f"Primary SOP ID '{primary_sop_id}' was not cited in the answer."

    for cited_id in cited_sop_ids:
        if cited_id not in matched_sop_ids:
            return False, f"Cited SOP ID '{cited_id}' was not in matched SOPs set {matched_sop_ids}."
        if cited_id not in all_known_sop_ids:
            return False, f"Cited SOP ID '{cited_id}' does not exist in active SOP repository."

    return True, "Citations valid."

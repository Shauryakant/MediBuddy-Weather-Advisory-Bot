"""
test_validators.py: Unit tests for number grounding and citation validators.
"""
import pytest
from app.validators import validate_number_grounding, validate_sop_citations

def test_validate_number_grounding_valid():
    allowed_numbers = {
        "temperature_2m.max.today": 36.5,
        "wind_speed_10m.max.today": 42.0,
        "precipitation.sum.today": 12.0
    }
    # Standard time numbers (11, 4) and SOP ID (SOP-EXE-001) must be allowed
    text = "Under SOP-EXE-001, temperature is 36.5°C and wind speed is 42 km/h between 11 am and 4 pm."
    is_valid, ungrounded = validate_number_grounding(text, allowed_numbers)
    assert is_valid is True
    assert ungrounded == []

def test_validate_number_grounding_unallowed_number():
    allowed_numbers = {
        "temperature_2m.max.today": 30.0,
        "wind_speed_10m.max.today": 15.0
    }
    # 99.9 is not in allowed numbers or time tokens
    text = "Under SOP-EXE-001, temperature is 30°C but wind speed reached 99.9 km/h."
    is_valid, ungrounded = validate_number_grounding(text, allowed_numbers)
    assert is_valid is False
    assert 99.9 in ungrounded

def test_validate_sop_citations_valid():
    text = "Based on SOP-SIT-001 (Heavy Rain) and SOP-TRV-001 (Wind), please avoid cycling."
    primary_id = "SOP-SIT-001"
    matched_ids = ["SOP-SIT-001", "SOP-TRV-001"]
    all_ids = {"SOP-SIT-001", "SOP-TRV-001", "SOP-EXE-001"}

    is_valid, reason = validate_sop_citations(text, primary_id, matched_ids, all_ids)
    assert is_valid is True

def test_validate_sop_citations_missing_primary():
    text = "Based on SOP-TRV-001, wind is high."
    primary_id = "SOP-SIT-001"
    matched_ids = ["SOP-SIT-001", "SOP-TRV-001"]
    all_ids = {"SOP-SIT-001", "SOP-TRV-001"}

    is_valid, reason = validate_sop_citations(text, primary_id, matched_ids, all_ids)
    assert is_valid is False
    assert "Primary SOP ID 'SOP-SIT-001' was not cited" in reason

def test_validate_sop_citations_fabricated_sop():
    text = "According to SOP-777, outdoor exercise in storm is safe."
    primary_id = "SOP-777"
    matched_ids = ["SOP-SIT-001"]
    all_ids = {"SOP-SIT-001", "SOP-TRV-001"}

    is_valid, reason = validate_sop_citations(text, primary_id, matched_ids, all_ids)
    assert is_valid is False

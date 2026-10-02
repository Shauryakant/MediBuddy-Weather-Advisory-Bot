"""
test_resolver.py: Unit tests for conflict resolution ranking policy.
"""
import pytest
from app.resolver import resolve_sop_conflicts

def test_override_wins_outright():
    sops = [
        {"sop_id": "SOP-EXE-001", "severity": "danger", "priority": 80, "overrides": None},
        {"sop_id": "SOP-SIT-001", "severity": "danger", "priority": 100, "overrides": "all"},
        {"sop_id": "SOP-TRV-001", "severity": "warning", "priority": 70, "overrides": None},
    ]
    primary, secondaries = resolve_sop_conflicts(sops)
    assert primary["sop_id"] == "SOP-SIT-001"
    assert len(secondaries) == 2
    assert secondaries[0]["sop_id"] == "SOP-EXE-001"

def test_severity_ranking():
    sops = [
        {"sop_id": "SOP-INF-001", "severity": "info", "priority": 10},
        {"sop_id": "SOP-EXE-003", "severity": "warning", "priority": 60},
        {"sop_id": "SOP-EXE-002", "severity": "caution", "priority": 40},
    ]
    primary, secondaries = resolve_sop_conflicts(sops)
    assert primary["sop_id"] == "SOP-EXE-003"
    assert secondaries[0]["sop_id"] == "SOP-EXE-002"
    assert secondaries[1]["sop_id"] == "SOP-INF-001"

def test_priority_tiebreaker():
    sops = [
        {"sop_id": "SOP-A", "severity": "warning", "priority": 50},
        {"sop_id": "SOP-B", "severity": "warning", "priority": 70},
    ]
    primary, secondaries = resolve_sop_conflicts(sops)
    assert primary["sop_id"] == "SOP-B"

def test_max_two_secondaries():
    sops = [
        {"sop_id": "SOP-1", "severity": "danger", "priority": 90},
        {"sop_id": "SOP-2", "severity": "warning", "priority": 80},
        {"sop_id": "SOP-3", "severity": "warning", "priority": 70},
        {"sop_id": "SOP-4", "severity": "caution", "priority": 60},
    ]
    primary, secondaries = resolve_sop_conflicts(sops)
    assert primary["sop_id"] == "SOP-1"
    assert len(secondaries) == 2
    assert [s["sop_id"] for s in secondaries] == ["SOP-2", "SOP-3"]

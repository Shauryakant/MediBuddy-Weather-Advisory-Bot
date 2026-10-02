"""
test_evaluator.py: Unit tests for deterministic SOP condition evaluation, ops, aggs, and null handling.
"""
import pytest
from pathlib import Path
from app.sop_loader import load_sop_from_file
from app.sop_engine import (
    compare_values,
    evaluate_condition_node,
    evaluate_threshold_sop,
)

def test_compare_values():
    assert compare_values(45, ">", 40) is True
    assert compare_values(40, ">", 40) is False
    assert compare_values(40, ">=", 40) is True
    assert compare_values(35, "<", 40) is True
    assert compare_values(40, "<=", 40) is True
    assert compare_values(20, "==", 20) is True
    assert compare_values(95, "in", [95, 96, 99]) is True
    assert compare_values(50, "in", [95, 96, 99]) is False
    assert compare_values(None, ">", 10) is False

def test_evaluate_condition_node_all_of():
    tree = {
        "all_of": [
            {"metric": "temperature_2m", "agg": "max", "window": "today", "op": ">=", "value": 35.0},
            {"metric": "precipitation", "agg": "sum", "window": "today", "op": ">=", "value": 10.0},
        ]
    }
    metrics_match = {
        "temperature_2m.max.today": 36.5,
        "precipitation.sum.today": 12.0,
    }
    triggered, ev, valid = evaluate_condition_node(tree, metrics_match)
    assert valid is True
    assert triggered is True
    assert ev["temperature_2m.max.today"] == 36.5

    metrics_no_match = {
        "temperature_2m.max.today": 36.5,
        "precipitation.sum.today": 5.0,
    }
    triggered2, ev2, valid2 = evaluate_condition_node(tree, metrics_no_match)
    assert valid2 is True
    assert triggered2 is False

def test_evaluate_condition_node_delta():
    tree = {
        "metric": "pressure_msl",
        "agg": "delta",
        "window": "today",
        "op": "<=",
        "value": -4.0,
    }
    metrics = {"pressure_msl.delta.today": -5.2}
    triggered, ev, valid = evaluate_condition_node(tree, metrics)
    assert valid is True
    assert triggered is True
    assert ev["pressure_msl.delta.today"] == -5.2

def test_null_metric_handling():
    tree = {
        "metric": "cape",
        "agg": "max",
        "window": "today",
        "op": ">=",
        "value": 1000.0,
    }
    metrics_null = {"cape.max.today": None}
    triggered, ev, valid = evaluate_condition_node(tree, metrics_null)
    assert valid is False
    assert triggered is False

def test_sop_sit_001_evaluation():
    sops_dir = Path(__file__).resolve().parent.parent / "sops"
    sop_file = sops_dir / "sop_sit_001_heavy_rain.yaml"
    if sop_file.exists():
        sop = load_sop_from_file(sop_file)
        severe_metrics = {
            "precipitation.sum.today": 75.0,
            "precipitation.sum.morning": 45.0,
            "pressure_msl.delta.today": -6.0,
            "weather_code.value.now": 65,
        }
        res = evaluate_threshold_sop(sop, severe_metrics)
        assert res["triggered"] is True
        assert res["sop_id"] == "SOP-SIT-001"
        assert res["severity"] == "danger"
        assert res["overrides"] == "all"

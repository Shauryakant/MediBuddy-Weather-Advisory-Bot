"""
sop_loader.py: Schema definition, YAML loading, and dynamic metadata extraction for SOP policies.
"""
from typing import List, Dict, Any, Optional, Set, Tuple, Literal
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError, model_validator
import yaml
import logging

logger = logging.getLogger(__name__)

class AppliesTo(BaseModel):
    activities: List[str] = Field(default_factory=lambda: ["*"])
    audiences: List[str] = Field(default_factory=lambda: ["*"])

class SingleCondition(BaseModel):
    metric: str
    agg: Literal["value", "max", "min", "sum", "mean", "delta"] = "value"
    window: str = "today"
    op: Literal[">", ">=", "<", "<=", "==", "in"] = ">="
    value: Any

class ConditionGroup(BaseModel):
    all_of: Optional[List[Any]] = None
    any_of: Optional[List[Any]] = None
    not_: Optional[Any] = Field(None, alias="not")

class ThresholdMatch(BaseModel):
    type: Literal["threshold"] = "threshold"
    all_of: Optional[List[Any]] = None
    any_of: Optional[List[Any]] = None
    not_: Optional[Any] = Field(None, alias="not")

class FuzzyMatch(BaseModel):
    type: Literal["fuzzy"] = "fuzzy"
    rubric: str
    evidence_metrics: List[str] = Field(default_factory=list)
    verdicts: Dict[str, str]

class SOPModel(BaseModel):
    id: str
    title: str
    category: str
    severity: Literal["info", "caution", "warning", "danger"]
    priority: int = 50
    applies_to: AppliesTo
    match: Dict[str, Any]
    overrides: Optional[str] = None  # e.g., "all"
    guidance: str
    rationale: str
    owner: str = "Safety Team"
    version: str = "1.0.0"
    last_reviewed: str = "2026-10-01"

    @model_validator(mode="after")
    def validate_match_structure(self) -> "SOPModel":
        match_type = self.match.get("type")
        if match_type == "threshold":
            ThresholdMatch.model_validate(self.match)
        elif match_type == "fuzzy":
            FuzzyMatch.model_validate(self.match)
        else:
            raise ValueError(f"Unknown match type: '{match_type}' in SOP {self.id}")
        return self


def parse_condition_tree_metrics(node: Any) -> Set[str]:
    """Recursively collect metric names from a threshold condition tree."""
    metrics: Set[str] = set()
    if isinstance(node, dict):
        if "metric" in node:
            metrics.add(node["metric"])
        for k in ("all_of", "any_of"):
            if k in node and isinstance(node[k], list):
                for child in node[k]:
                    metrics.update(parse_condition_tree_metrics(child))
        if "not" in node:
            metrics.update(parse_condition_tree_metrics(node["not"]))
    elif isinstance(node, list):
        for child in node:
            metrics.update(parse_condition_tree_metrics(child))
    return metrics


def load_sop_from_file(file_path: Path) -> SOPModel:
    """Load and validate a single YAML SOP file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML structure in {file_path.name}")
    return SOPModel.model_validate(data)


def load_all_sops(sops_dir: Path) -> List[SOPModel]:
    """
    Loads all .yaml/.yml SOP files from sops_dir.
    Logs warnings for broken SOPs without breaking valid ones.
    """
    sops: List[SOPModel] = []
    if not sops_dir.exists():
        logger.warning(f"SOP directory {sops_dir} does not exist.")
        return sops

    for filepath in sorted(sops_dir.glob("*.yaml")) + sorted(sops_dir.glob("*.yml")):
        try:
            sop = load_sop_from_file(filepath)
            sops.append(sop)
        except (ValidationError, Exception) as e:
            logger.error(f"Failed to load SOP file {filepath.name}: {e}")

    return sops


def get_required_weather_metrics(sops: List[SOPModel]) -> Set[str]:
    """
    Computes the UNION of all weather metrics required across all active SOPs.
    This enables dynamic field fetching from Open-Meteo without code changes.
    """
    metrics: Set[str] = set()
    for sop in sops:
        match_data = sop.match
        match_type = match_data.get("type")
        if match_type == "threshold":
            metrics.update(parse_condition_tree_metrics(match_data))
        elif match_type == "fuzzy":
            evidence = match_data.get("evidence_metrics", [])
            metrics.update(evidence)
    # Default essential metrics if list is empty
    if not metrics:
        metrics = {"temperature_2m", "apparent_temperature", "wind_speed_10m", "precipitation"}
    return metrics


def get_taxonomy_tags(sops: List[SOPModel]) -> Tuple[List[str], List[str]]:
    """
    Extracts unique activity and audience tags across all active SOPs.
    Returns (activities, audiences).
    """
    activities: Set[str] = set()
    audiences: Set[str] = set()
    for sop in sops:
        for act in sop.applies_to.activities:
            if act != "*":
                activities.add(act)
        for aud in sop.applies_to.audiences:
            if aud != "*":
                audiences.add(aud)
    return sorted(list(activities)), sorted(list(audiences))

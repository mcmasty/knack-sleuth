"""Impact analysis: pinned risk bands and a golden file for the sample app.

The golden file holds generate_impact_analysis for every object and field in
the sample fixture. A change that alters it on purpose regenerates it with

    UPDATE_GOLDEN=1 uv run pytest tests/test_impact_analysis_golden.py

and the diff of the golden file shows exactly what moved.
"""

import json
import os
from pathlib import Path

import pytest

from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.sleuth import (
    FIELD_RISK_LOW_MAX,
    FIELD_RISK_MEDIUM_MAX,
    OBJECT_RISK_LOW_MAX,
    OBJECT_RISK_MEDIUM_MAX,
    KnackSleuth,
    _risk_level,
    _workflow_hints,
)

GOLDEN = Path(__file__).parent / "data" / "golden" / "impact_analysis_sample.json"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, "none"),
        (1, "low"),
        (OBJECT_RISK_LOW_MAX, "low"),
        (OBJECT_RISK_LOW_MAX + 1, "medium"),
        (OBJECT_RISK_MEDIUM_MAX, "medium"),
        (OBJECT_RISK_MEDIUM_MAX + 1, "high"),
    ],
)
def test_object_risk_bands(score, expected):
    assert _risk_level(score, OBJECT_RISK_LOW_MAX, OBJECT_RISK_MEDIUM_MAX) == expected


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, "none"),
        (FIELD_RISK_LOW_MAX, "low"),
        (FIELD_RISK_LOW_MAX + 1, "medium"),
        (FIELD_RISK_MEDIUM_MAX, "medium"),
        (FIELD_RISK_MEDIUM_MAX + 1, "high"),
    ],
)
def test_field_risk_bands(score, expected):
    assert _risk_level(score, FIELD_RISK_LOW_MAX, FIELD_RISK_MEDIUM_MAX) == expected


def test_band_thresholds():
    """The thresholds are part of the output contract; change them deliberately."""
    assert (OBJECT_RISK_LOW_MAX, OBJECT_RISK_MEDIUM_MAX) == (5, 15)
    assert (FIELD_RISK_LOW_MAX, FIELD_RISK_MEDIUM_MAX) == (3, 10)


def test_workflow_hints_follow_the_requested_order():
    direct = {"forms": [{}], "views": [], "connections": [{}], "formulas": [{}]}
    assert _workflow_hints(direct, ("forms", "views", "connections")) == [
        "User data entry forms",
        "Related data relationships",
    ]
    assert _workflow_hints(direct, ("formulas", "forms")) == [
        "Calculated fields and formulas",
        "User data entry forms",
    ]


def _all_impact_analyses(metadata: dict) -> dict:
    sleuth = KnackSleuth(KnackAppMetadata(**metadata))
    keys = [obj.key for obj in sleuth.app.objects]
    keys += [field.key for obj in sleuth.app.objects for field in obj.fields]
    keys += ["object_999999", "field_999999", "nonsense"]
    return {key: sleuth.generate_impact_analysis(key) for key in keys}


def test_matches_golden(sample_metadata_dict):
    actual = _all_impact_analyses(sample_metadata_dict)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN.read_text())
    assert actual == expected


def test_golden_covers_every_risk_band():
    levels = {
        analysis["risk_assessment"]["breaking_change_likelihood"]
        for analysis in json.loads(GOLDEN.read_text()).values()
        if "risk_assessment" in analysis
    }
    assert {"none", "low", "medium", "high"} <= levels

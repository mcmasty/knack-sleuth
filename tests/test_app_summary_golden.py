"""app-summary: golden files plus small hand-built cases for the rules.

The golden files hold generate_app_summary for the sample fixture and the
synthetic schema app. A deliberate output change regenerates them with

    UPDATE_GOLDEN=1 uv run pytest tests/test_app_summary_golden.py
"""

import json
import os
from pathlib import Path

import pytest

from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.sleuth import (
    KnackSleuth,
    _cohesion,
    _core_entity_keys,
    _score_importance,
)

DATA = Path(__file__).parent / "data"


@pytest.mark.parametrize(
    "fixture", ["sample_knack_app_meta.json", "schema_cases_meta.json"]
)
def test_matches_golden(fixture):
    metadata = json.loads((DATA / fixture).read_text())
    actual = KnackSleuth(KnackAppMetadata(**metadata)).generate_app_summary()
    golden = DATA / "golden" / f"app_summary_{fixture}"
    if os.environ.get("UPDATE_GOLDEN"):
        golden.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n")
    assert actual == json.loads(golden.read_text())


def summaries(*pairs: tuple[int, int]) -> list[dict]:
    """One summary per (record_count, total_connections), keyed obj_0, obj_1..."""
    return [
        {"object_key": f"obj_{i}", "record_count": records, "total_connections": links}
        for i, (records, links) in enumerate(pairs)
    ]


def test_importance_is_60_percent_volume_40_percent_connectivity():
    pool = summaries((100, 0), (0, 10), (50, 5), (0, 0))
    _score_importance(pool)
    assert [s["importance_score"] for s in pool] == pytest.approx([0.6, 0.4, 0.5, 0.0])


def test_importance_with_no_records_or_links_is_zero():
    pool = summaries((0, 0), (0, 0))
    _score_importance(pool)
    assert [s["importance_score"] for s in pool] == [0, 0]


@pytest.mark.parametrize(
    ("pool_size", "expected"),
    [(3, 3), (10, 4), (24, 4), (25, 5), (49, 9), (50, 10), (80, 10)],
)
def test_core_entity_count(pool_size, expected):
    """20% of the pool, at least 4 (or all of a smaller pool), at most 10."""
    pool = summaries(*[(n, 0) for n in range(pool_size)])
    _score_importance(pool)
    assert len(_core_entity_keys(pool)) == expected


def test_core_entities_are_the_most_important():
    pool = summaries(*[(n, 0) for n in range(10)])
    _score_importance(pool)
    assert _core_entity_keys(pool) == {"obj_9", "obj_8", "obj_7", "obj_6"}


@pytest.mark.parametrize(
    ("internal", "total", "expected"),
    [
        (0, 0, "low"),
        (4, 10, "low"),
        (5, 10, "medium"),
        (7, 10, "medium"),
        (8, 10, "high"),
    ],
)
def test_cohesion_bands(internal, total, expected):
    assert _cohesion(internal, total) == expected


def _app_with_links(links: list[tuple[str, str]], count: int) -> KnackSleuth:
    """Objects object_1..object_<count>, with one connection per (from, to)."""

    def conn(key, target):
        return {
            "key": key,
            "name": key,
            "object": target,
            "has": "one",
            "belongs_to": "many",
            "field": {"name": key},
        }

    objects = {
        f"object_{n}": {
            "key": f"object_{n}",
            "name": f"O{n}",
            "fields": [],
            "connections": {"outbound": [], "inbound": []},
        }
        for n in range(1, count + 1)
    }
    for i, (src, dst) in enumerate(links):
        key = f"field_{i + 1}"
        objects[src]["connections"]["outbound"].append(conn(key, dst))
        objects[dst]["connections"]["inbound"].append(conn(key, src))
    return KnackSleuth(
        KnackAppMetadata(
            application={
                "name": "Graph",
                "slug": "graph",
                "id": "graph",
                "home_scene": {"key": "scene_1", "slug": "home"},
                "objects": list(objects.values()),
            }
        )
    )


def test_cluster_takes_direct_and_shared_neighbours():
    # 1 links to 2 and 3; 4 links to 2 and 3 too, so it shares two of 1's
    # neighbours without linking to 1. 5 links only to 2: one shared, no join.
    sleuth = _app_with_links(
        [
            ("object_1", "object_2"),
            ("object_1", "object_3"),
            ("object_4", "object_2"),
            ("object_4", "object_3"),
            ("object_5", "object_2"),
        ],
        count=6,
    )
    [cluster] = sleuth._identify_clusters()
    assert cluster["object_keys"] == ["object_1", "object_2", "object_3", "object_4"]
    assert cluster["internal_connections"] == 4
    assert cluster["external_connections"] == 1
    assert cluster["cohesion"] == "high"


def test_object_with_one_neighbour_seeds_no_cluster():
    sleuth = _app_with_links([("object_1", "object_2")], count=2)
    assert sleuth._identify_clusters() == []

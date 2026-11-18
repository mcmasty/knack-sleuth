"""Field references outside views keep a field alive.

Other fields' definitions, object tasks and page rules all name fields. Before
these were indexed, find-orphans reported such fields as unused, and users
delete fields on that output.
"""

import re
from typing import Any

import pytest

from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.sleuth import KnackSleuth

TARGET = {"key": "field_1", "name": "Target", "type": "short_text"}


def sleuth_for(
    fields: list[dict],
    tasks: tuple[dict, ...] | list[dict] = (),
    scene_rules: tuple[dict, ...] | list[dict] = (),
) -> KnackSleuth:
    """A one-object, one-page app whose object holds TARGET plus `fields`."""
    return KnackSleuth(
        KnackAppMetadata(
            application={
                "name": "App",
                "slug": "app",
                "id": "app_1",
                "home_scene": {"key": "scene_1", "slug": "home"},
                "objects": [
                    {
                        "key": "object_1",
                        "name": "Things",
                        "fields": [TARGET, *fields],
                        "tasks": list(tasks),
                    }
                ],
                "scenes": [
                    {
                        "key": "scene_1",
                        "name": "Home",
                        "slug": "home",
                        "views": [],
                        "rules": list(scene_rules),
                    }
                ],
            }
        )
    )


def other(**definition: Any) -> dict:
    return {"key": "field_3", "name": "Other", "type": "short_text", **definition}


CRITERIA = [{"field": "field_1", "operator": "is", "value": "x"}]

CASES = {
    "connected-field equation": (
        [other(type="concatenation", format={"equation": "{field_2.field_1}"})],
        (),
        (),
        "field_reference",
        "format.equation",
    ),
    "equation stored as a list": (
        [other(type="equation", format={"equation": [{"field": "field_1"}]})],
        (),
        (),
        "field_reference",
        "format.equation.0.field",
    ),
    "sum field": (
        [other(type="sum", format={"field": {"key": "field_1"}})],
        (),
        (),
        "field_reference",
        "format.field.key",
    ),
    "count filter": (
        [other(type="count", format={"filters": CRITERIA})],
        (),
        (),
        "field_reference",
        "format.filters.0.field",
    ),
    "conditional rule value": (
        [other(rules=[{"criteria": [], "values": [{"input": "field_1"}]}])],
        (),
        (),
        "field_reference",
        "rules.0.values.0.input",
    ),
    "object task criteria": (
        [],
        [{"name": "Nightly", "action": {"criteria": CRITERIA}}],
        (),
        "object_reference",
        "tasks.0.action.criteria.0.field",
    ),
    "page rule criteria": (
        [],
        (),
        [{"criteria": CRITERIA}],
        "scene_reference",
        "rules.0.criteria.0.field",
    ),
}


@pytest.mark.parametrize(
    ("fields", "tasks", "scene_rules", "location_type", "path"),
    CASES.values(),
    ids=CASES.keys(),
)
def test_reference_keeps_field_alive(fields, tasks, scene_rules, location_type, path):
    sleuth = sleuth_for(fields, tasks, scene_rules)

    usages = sleuth.search_field("field_1")
    assert [(u.location_type, u.details["reference_path"]) for u in usages] == [
        (location_type, path)
    ]
    assert "field_1" not in {f.key for _, f in sleuth.find_orphaned_fields()}


def test_plain_equation_is_reported_once():
    sleuth = sleuth_for([other(type="equation", format={"equation": "{field_1}"})])
    assert [u.location_type for u in sleuth.search_field("field_1")] == [
        "field_equation"
    ]


def test_reference_to_itself_does_not_count():
    sleuth = sleuth_for(
        [other(rules=[{"criteria": [{"field": "field_3"}], "values": []}])]
    )
    assert sleuth.search_field("field_3") == []
    assert "field_3" in {f.key for _, f in sleuth.find_orphaned_fields()}


def test_unknown_field_keys_are_ignored():
    sleuth = sleuth_for([other(format={"filters": [{"field": "field_999"}]})])
    assert "field_999" not in sleuth.metadata_field_references


def test_callers_get_copies():
    sleuth = sleuth_for([other(format={"filters": CRITERIA})])
    sleuth.search_field("field_1")[0].details["reference_path"] = "edited"
    assert sleuth.search_field("field_1")[0].details["reference_path"] == (
        "format.filters.0.field"
    )


FIELD_KEY = re.compile(r"(?<![A-Za-z0-9_])(field_\d+)(?![A-Za-z0-9_])")


def _keys_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(
            *(FIELD_KEY.findall(str(k)) for k in value),
            *(_keys_in(v) for v in value.values()),
        )
    if isinstance(value, list):
        return set().union(*(_keys_in(v) for v in value))
    return set(FIELD_KEY.findall(value)) if isinstance(value, str) else set()


def test_no_orphan_is_named_anywhere_else(sample_metadata_dict):
    """Invariant: an orphan's key appears nowhere outside its own definition,
    except in views no page layout places."""
    app = sample_metadata_dict["application"]
    sleuth = KnackSleuth(KnackAppMetadata(**sample_metadata_dict))

    named: set[str] = set()
    for obj in app["objects"]:
        for field in obj["fields"]:
            named |= _keys_in(field) - {field["key"]}
        named |= _keys_in({k: v for k, v in obj.items() if k != "fields"})
    for scene in app["scenes"]:
        views = [
            v
            for v in scene.get("views", [])
            if v["key"] not in sleuth.orphaned_view_keys
        ]
        named |= _keys_in({**scene, "views": views})

    orphans = {f.key for _, f in sleuth.find_orphaned_fields()}
    assert {"field_154", "field_164"} <= named  # referenced in count filters
    assert orphans & named == set()

"""Every source of a field usage, in the order search_field reports them.

One synthetic app names two fields in every way the search knows. Deleting
or reordering any branch of the search fails these tests, which the sample
fixtures can't guarantee: no fixture has a form ``inputs`` entry, for one.
"""

from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.sleuth import KnackSleuth


def _view(key: str, **definition) -> dict:
    return {"key": key, "name": f"View {key}", "type": "table", **definition}


APP = {
    "name": "App",
    "slug": "app",
    "id": "app_1",
    "home_scene": {"key": "scene_1", "slug": "home"},
    "objects": [
        {
            "key": "object_1",
            "name": "Things",
            "identifier": "field_1",
            "sort": {"field": "field_1", "order": "asc"},
            "connections": {
                "outbound": [
                    {
                        "key": "field_2",
                        "name": "Owner",
                        "object": "object_2",
                        "has": "one",
                        "belongs_to": "many",
                        "field": {
                            "name": "Owner",
                            "inflections": {"plural": "Owners", "singular": "Owner"},
                        },
                    }
                ],
                "inbound": [],
            },
            "fields": [
                {"key": "field_1", "name": "Title", "type": "short_text"},
                {"key": "field_2", "name": "Owner", "type": "connection"},
                {
                    "key": "field_3",
                    "name": "Label",
                    "type": "equation",
                    "format": {"equation": "{field_1}"},
                },
                {
                    "key": "field_4",
                    "name": "Count",
                    "type": "count",
                    "format": {"filters": [{"field": "field_1"}]},
                },
            ],
            "tasks": [
                {"name": "Nightly", "action": {"criteria": [{"field": "field_1"}]}}
            ],
        },
        {"key": "object_2", "name": "Owners", "fields": []},
    ],
    "scenes": [
        {
            "key": "scene_1",
            "name": "Home",
            "slug": "home",
            "rules": [{"criteria": [{"field": "field_1"}]}],
            "groups": [{"columns": [{"keys": ["view_1", "view_2", "view_3"]}]}],
            "views": [
                _view(
                    "view_1",
                    columns=[{"field": {"key": "field_1"}, "header": "Title"}],
                    source={
                        "object": "object_1",
                        "sort": [{"field": "field_1", "order": "desc"}],
                    },
                ),
                _view(
                    "view_2",
                    type="form",
                    inputs=[{"key": "field_1"}],
                    source={
                        "object": "object_1",
                        "parent_source": {
                            "object": "object_2",
                            "connection": "field_2",
                        },
                        "connection_key": "field_2",
                    },
                ),
                _view("view_3", totals=[{"field": "field_1"}]),
            ],
        }
    ],
}


def usages(field_key: str) -> list[tuple[str, str | None]]:
    sleuth = KnackSleuth(KnackAppMetadata(application=APP))
    return [
        (
            u.location_type,
            u.details.get("view_key")
            or u.details.get("scene_key")
            or u.details.get("field_key")
            or u.details.get("object_key"),
        )
        for u in sleuth.search_field(field_key)
    ]


def test_every_source_of_a_plain_field_in_order():
    assert usages("field_1") == [
        ("object_sort", "object_1"),
        ("object_identifier", "object_1"),
        ("field_equation", "field_3"),
        ("view_column", "view_1"),
        ("view_sort", "view_1"),
        ("form_input", "view_2"),
        ("view_field_reference", "view_3"),
        ("field_reference", "field_4"),
        ("object_reference", "object_1"),
        ("scene_reference", "scene_1"),
    ]


def test_every_source_of_a_connection_field_in_order():
    assert usages("field_2") == [
        ("connection_field", "object_1"),
        ("view_parent_connection", "view_2"),
        ("view_connection_key", "view_2"),
    ]

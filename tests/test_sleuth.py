"""Tests for KnackSleuth orphan detection."""

import pytest

from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.sleuth import KnackSleuth


@pytest.fixture
def sleuth(sample_metadata_dict):
    """KnackSleuth built from the sample metadata."""
    return KnackSleuth(KnackAppMetadata(**sample_metadata_dict))


class TestOrphanDetection:
    def test_orphaned_fields_have_no_usages(self, sleuth):
        orphans = sleuth.find_orphaned_fields()
        # Spot-check: every reported orphan really has zero usages
        for _, field in orphans[:10]:
            assert sleuth.search_field(field.key) == []

    def test_counts_match_app_summary_debt_section(self, sleuth):
        """find_orphaned_* must stay in sync with app-summary's debt counts."""
        summary = sleuth.generate_app_summary()
        debt = summary["technical_debt_indicators"]

        assert debt["orphaned_fields"] == len(sleuth.find_orphaned_fields())
        assert debt["orphaned_objects"] == len(sleuth.find_orphaned_objects())
        assert debt["orphaned_views"] == len(sleuth.find_orphaned_views())
        assert debt["dangling_layout_keys"] == len(sleuth.find_dangling_layout_keys())
        assert debt["stale_view_rule_references"] == len(
            sleuth.find_stale_view_rule_references()
        )

    def test_orphaned_objects_exclude_user_profiles(self, sleuth):
        for obj in sleuth.find_orphaned_objects():
            assert not obj.profile_key

    def test_orphaned_objects_have_no_connections(self, sleuth):
        for obj in sleuth.find_orphaned_objects():
            if obj.connections:
                assert not obj.connections.inbound
                assert not obj.connections.outbound

    @pytest.mark.parametrize(
        ("view_metadata", "expected_path"),
        [
            (
                {"groups": [{"columns": [{"fields": [{"key": "field_1"}]}]}]},
                "groups.0.columns.0.fields.0.key",
            ),
            (
                {
                    "rules": [
                        {
                            "criteria": [{"field": "field_1"}],
                            "values": [{"value": "{field_1}"}],
                        }
                    ]
                },
                "rules.0.criteria.0.field",
            ),
            (
                {"totals": [{"field": "field_1"}]},
                "totals.0.field",
            ),
            (
                {"preset_filters": [{"field": "field_1"}]},
                "preset_filters.0.field",
            ),
            (
                {"calculations": [{"equation": "SUM({field_1})"}]},
                "calculations.0.equation",
            ),
            # The walk sees a view's model_dump, so any submodel that discards
            # unknown keys re-opens the blind spot this traversal exists to
            # close -- these three cover the typed source submodels.
            (
                {
                    "source": {
                        "object": "object_1",
                        "criteria": {
                            "match": "all",
                            "rules": [],
                            "custom_rule": {"field": "field_1"},
                        },
                    }
                },
                "source.criteria.custom_rule.field",
            ),
            (
                {
                    "source": {
                        "object": "object_1",
                        "sort": [
                            {
                                "field": "field_2",
                                "order": "asc",
                                "secondary_field": "field_1",
                            }
                        ],
                    }
                },
                "source.sort.0.secondary_field",
            ),
            (
                {
                    "source": {
                        "object": "object_1",
                        "parent_source": {
                            "object": "object_1",
                            "connection": "field_2",
                            "fallback_connection": "field_1",
                        },
                    }
                },
                "source.parent_source.fallback_connection",
            ),
        ],
    )
    def test_nested_view_reference_prevents_false_orphan(
        self,
        view_metadata,
        expected_path,
    ):
        metadata = KnackAppMetadata(
            application={
                "id": "app_1",
                "name": "Reference Test",
                "slug": "reference-test",
                "home_scene": {"key": "scene_1", "slug": "home"},
                "objects": [
                    {
                        "key": "object_1",
                        "name": "Thing",
                        "fields": [
                            {"key": "field_1", "name": "Value", "type": "short_text"}
                        ],
                    }
                ],
                "scenes": [
                    {
                        "key": "scene_1",
                        "name": "Home",
                        "slug": "home",
                        "views": [
                            {
                                "key": "view_1",
                                "name": "Reference View",
                                "type": "form",
                                **view_metadata,
                            }
                        ],
                    }
                ],
            }
        )
        nested_sleuth = KnackSleuth(metadata)

        usages = nested_sleuth.search_field("field_1")

        assert nested_sleuth.find_orphaned_fields() == []
        assert any(
            usage.location_type == "view_field_reference"
            and usage.details["reference_path"] == expected_path
            for usage in usages
        )

    def test_typed_reference_is_not_reported_twice(self):
        """A form input is already found by the typed check, so the generic
        walk must suppress it -- otherwise every typed reference doubles."""
        metadata = KnackAppMetadata(
            application={
                "id": "app_1",
                "name": "Dedup Test",
                "slug": "dedup-test",
                "home_scene": {"key": "scene_1", "slug": "home"},
                "objects": [
                    {
                        "key": "object_1",
                        "name": "Thing",
                        "fields": [
                            {"key": "field_1", "name": "Value", "type": "short_text"}
                        ],
                    }
                ],
                "scenes": [
                    {
                        "key": "scene_1",
                        "name": "Home",
                        "slug": "home",
                        "views": [
                            {
                                "key": "view_1",
                                "name": "Form",
                                "type": "form",
                                "inputs": [{"key": "field_1"}],
                            }
                        ],
                    }
                ],
            }
        )

        usages = KnackSleuth(metadata).search_field("field_1")

        assert [usage.location_type for usage in usages] == ["form_input"]

    def test_field_key_token_does_not_match_longer_field_key(self):
        metadata = KnackAppMetadata(
            application={
                "id": "app_1",
                "name": "Reference Test",
                "slug": "reference-test",
                "home_scene": {"key": "scene_1", "slug": "home"},
                "objects": [
                    {
                        "key": "object_1",
                        "name": "Thing",
                        "fields": [
                            {"key": "field_1", "name": "One", "type": "short_text"},
                            {"key": "field_10", "name": "Ten", "type": "short_text"},
                        ],
                    }
                ],
                "scenes": [
                    {
                        "key": "scene_1",
                        "name": "Home",
                        "slug": "home",
                        "views": [
                            {
                                "key": "view_1",
                                "name": "Rule View",
                                "type": "form",
                                "rules": [{"value": "{field_10}"}],
                            }
                        ],
                    }
                ],
            }
        )
        nested_sleuth = KnackSleuth(metadata)

        assert nested_sleuth.search_field("field_1") == []
        assert nested_sleuth.search_field("field_10")


def _app(scenes, objects=None):
    """Build KnackAppMetadata from bare scene/object dicts."""
    return KnackAppMetadata(
        application={
            "id": "app_1",
            "name": "Layout Test",
            "slug": "layout-test",
            "home_scene": {"key": "scene_1", "slug": "home"},
            "objects": objects or [],
            "scenes": scenes,
        }
    )


def _scene(key, views, layout=None, **extra):
    """Scene with an explicit layout (list of view keys in one column)."""
    groups = [{"columns": [{"keys": list(layout)}]}] if layout else []
    return {
        "key": key,
        "name": key.replace("_", " ").title(),
        "slug": key.replace("_", "-"),
        "views": views,
        "groups": groups,
        **extra,
    }


def _view(key, view_type="table", **extra):
    return {"key": key, "name": f"View {key}", "type": view_type, **extra}


class TestOrphanedViews:
    def test_view_missing_from_populated_layout_is_orphaned(self):
        sleuth = KnackSleuth(
            _app([_scene("scene_1", [_view("view_1"), _view("view_2")], ["view_1"])])
        )

        orphans = sleuth.find_orphaned_views()

        assert [(o.scene.key, o.view.key) for o in orphans] == [("scene_1", "view_2")]

    def test_login_views_are_never_orphaned(self):
        """48 of 49 login views in a real app sit outside the layout -- Knack
        renders them from scene chrome, so absence proves nothing."""
        sleuth = KnackSleuth(
            _app([_scene("scene_1", [_view("view_1"), _view("view_2", "login")], ["view_1"])])
        )

        assert sleuth.find_orphaned_views() == []

    def test_scene_with_empty_layout_reports_nothing(self):
        """Knack leaves `groups` empty on auto-generated child pages (Edit X,
        X Details). An empty layout is not a layout that excluded the view."""
        sleuth = KnackSleuth(
            _app([_scene("scene_1", [_view("view_1", "form")], layout=None, modal=True)])
        )

        assert sleuth.find_orphaned_views() == []

    def test_sample_app_has_no_orphaned_views(self, sleuth):
        assert sleuth.find_orphaned_views() == []


class TestDanglingLayoutKeys:
    def test_layout_key_with_no_view_anywhere_is_deleted(self):
        sleuth = KnackSleuth(
            _app([_scene("scene_1", [_view("view_1")], ["view_1", "view_9"])])
        )

        dangling = sleuth.find_dangling_layout_keys()

        assert [(d.scene.key, d.view_key, d.moved_to) for d in dangling] == [
            ("scene_1", "view_9", None)
        ]

    def test_layout_key_for_view_on_another_scene_is_moved(self):
        """scene_915 in a real app still lists 7 views that now live on
        scene_1015 -- a move leaves the old layout pointing across scenes."""
        sleuth = KnackSleuth(
            _app(
                [
                    _scene("scene_1", [_view("view_1")], ["view_1", "view_2"]),
                    _scene("scene_2", [_view("view_2")], ["view_2"]),
                ]
            )
        )

        dangling = sleuth.find_dangling_layout_keys()

        assert [(d.scene.key, d.view_key, d.moved_to) for d in dangling] == [
            ("scene_1", "view_2", "scene_2")
        ]

    def test_healthy_layout_reports_nothing(self):
        sleuth = KnackSleuth(
            _app([_scene("scene_1", [_view("view_1"), _view("view_2")], ["view_1", "view_2"])])
        )

        assert sleuth.find_dangling_layout_keys() == []


class TestStaleViewRuleReferences:
    def test_rule_targeting_missing_view_is_stale(self):
        scene = _scene("scene_1", [_view("view_1")], ["view_1"])
        scene["rules"] = [{"action": "hide_views", "view_keys": ["view_1", "view_9"]}]
        sleuth = KnackSleuth(_app([scene]))

        stale = sleuth.find_stale_view_rule_references()

        assert [(r.scene.key, r.view_key, r.reason) for r in stale] == [
            ("scene_1", "view_9", "missing")
        ]

    def test_rule_targeting_orphaned_view_is_stale(self):
        """scene_455 hides view_1377 -- a rule can still name a view that the
        layout dropped, so 'not in layout' does not mean 'unreferenced'."""
        scene = _scene("scene_1", [_view("view_1"), _view("view_2", "form")], ["view_1"])
        scene["rules"] = [{"action": "hide_views", "view_keys": ["view_2"]}]
        sleuth = KnackSleuth(_app([scene]))

        stale = sleuth.find_stale_view_rule_references()

        assert [(r.view_key, r.reason) for r in stale] == [("view_2", "orphaned")]

    def test_rule_targeting_a_laid_out_view_is_fine(self):
        scene = _scene("scene_1", [_view("view_1")], ["view_1"])
        scene["rules"] = [{"action": "hide_views", "view_keys": ["view_1"]}]
        sleuth = KnackSleuth(_app([scene]))

        assert sleuth.find_stale_view_rule_references() == []

    def test_rule_reference_records_its_path(self):
        scene = _scene("scene_1", [_view("view_1")], ["view_1"])
        scene["rules"] = [
            {"action": "hide_views", "view_keys": []},
            {"action": "hide_views", "view_keys": ["view_9"]},
        ]
        sleuth = KnackSleuth(_app([scene]))

        assert sleuth.find_stale_view_rule_references()[0].rule_path == "rules.1.view_keys"


class TestOrphanedViewsDoNotKeepFieldsAlive:
    @staticmethod
    def _app_with_orphan():
        """field_2 is referenced only by view_2, which is off the layout."""
        return _app(
            scenes=[
                _scene(
                    "scene_1",
                    [
                        _view("view_1", columns=[{"type": "field", "field": {"key": "field_1"}}]),
                        _view("view_2", columns=[{"type": "field", "field": {"key": "field_2"}}]),
                    ],
                    ["view_1"],
                )
            ],
            objects=[
                {
                    "key": "object_1",
                    "name": "Thing",
                    "fields": [
                        {"key": "field_1", "name": "Live", "type": "short_text"},
                        {"key": "field_2", "name": "Stale", "type": "short_text"},
                    ],
                }
            ],
        )

    def test_field_used_only_by_an_orphaned_view_is_orphaned(self):
        sleuth = KnackSleuth(self._app_with_orphan())

        orphaned = {field.key for _, field in sleuth.find_orphaned_fields()}

        assert "field_2" in orphaned
        assert "field_1" not in orphaned

    def test_the_usage_is_still_reported_but_tagged(self):
        """Excluding the reference from the orphan count must not hide it --
        the user still needs to see where the dead reference lives."""
        sleuth = KnackSleuth(self._app_with_orphan())

        usages = sleuth.search_field("field_2")

        assert [u.details["view_key"] for u in usages] == ["view_2"]
        assert usages[0].details["orphaned_view"] is True

    def test_live_view_usages_are_not_tagged(self):
        sleuth = KnackSleuth(self._app_with_orphan())

        usages = sleuth.search_field("field_1")

        assert all(not u.details.get("orphaned_view") for u in usages)

    def test_object_shown_only_in_an_orphaned_view_is_orphaned(self):
        sleuth = KnackSleuth(
            _app(
                scenes=[
                    _scene(
                        "scene_1",
                        [
                            _view("view_1", source={"object": "object_9"}),
                            _view("view_2", source={"object": "object_1"}),
                        ],
                        ["view_1"],
                    )
                ],
                objects=[{"key": "object_1", "name": "Thing", "fields": []}],
            )
        )

        assert [o.key for o in sleuth.find_orphaned_objects()] == ["object_1"]

    def test_untyped_reference_in_an_orphaned_view_also_stops_counting(self):
        """The generic walk catches references in containers with no typed
        schema. Those must be excluded too, or the exclusion has a hole
        exactly where the walk exists to look."""
        sleuth = KnackSleuth(
            _app(
                scenes=[
                    _scene(
                        "scene_1",
                        [
                            _view("view_1"),
                            _view(
                                "view_2",
                                rules=[{"criteria": [{"field": "field_1"}]}],
                            ),
                        ],
                        ["view_1"],
                    )
                ],
                objects=[
                    {
                        "key": "object_1",
                        "name": "Thing",
                        "fields": [{"key": "field_1", "name": "Stale", "type": "short_text"}],
                    }
                ],
            )
        )

        usages = sleuth.search_field("field_1")

        assert [u.location_type for u in usages] == ["view_field_reference"]
        assert usages[0].details["orphaned_view"] is True
        assert [f.key for _, f in sleuth.find_orphaned_fields()] == ["field_1"]

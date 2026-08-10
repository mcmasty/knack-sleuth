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

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

"""Tests for knack_sleuth.diff."""

import copy

import pytest

from knack_sleuth.diff import diff_applications, diff_to_markdown
from knack_sleuth.models import KnackAppMetadata


@pytest.fixture
def old_app(sample_metadata_dict):
    return KnackAppMetadata(**sample_metadata_dict).application


@pytest.fixture
def mutated_dict(sample_metadata_dict):
    """A copy of the sample metadata with one of every kind of change applied."""
    d = copy.deepcopy(sample_metadata_dict)
    app = d["application"]

    objects_by_key = {obj["key"]: obj for obj in app["objects"]}

    # Object renamed
    objects_by_key["object_12"]["name"] = "Object Twelve Renamed"

    # Field changed (type + required) inside object_12
    # (field_89 is required=True in the sample data, so flip it to False)
    for field in objects_by_key["object_12"]["fields"]:
        if field["key"] == "field_89":
            field["type"] = "paragraph_text"
            field["required"] = False

    # Field removed from object_12
    objects_by_key["object_12"]["fields"] = [
        f for f in objects_by_key["object_12"]["fields"] if f["key"] != "field_104"
    ]

    # Field added to object_12
    objects_by_key["object_12"]["fields"].append(
        {"key": "field_9999", "name": "New Field", "type": "short_text"}
    )

    # Object removed (noise rule: its fields must NOT appear as removed fields)
    app["objects"] = [o for o in app["objects"] if o["key"] != "object_23"]

    # Object added (noise rule: its fields must NOT appear as added fields)
    app["objects"].append(
        {
            "key": "object_999",
            "name": "Brand New Object",
            "fields": [
                {"key": "field_9001", "name": "Title", "type": "short_text"},
                {"key": "field_9002", "name": "Amount", "type": "number"},
            ],
        }
    )

    scenes = app["scenes"]

    # Scene renamed
    scenes[0]["name"] = scenes[0]["name"] + " (Renamed)"

    # Scene removed
    scenes.pop()

    # Scene added (noise rule: its views must NOT appear as added views)
    scenes.append(
        {
            "key": "scene_999",
            "name": "Brand New Scene",
            "slug": "brand-new",
            "views": [{"key": "view_9001", "name": "New View", "type": "table"}],
        }
    )

    # View added + view renamed, in the first remaining scene that has views
    for scene in scenes:
        if scene.get("views") and scene["key"] != "scene_999":
            scene["views"][0]["name"] = "Totally Renamed View"
            scene["views"].append(
                {"key": "view_9999", "name": "Added View", "type": "form"}
            )
            break

    return d


@pytest.fixture
def new_app(mutated_dict):
    return KnackAppMetadata(**mutated_dict).application


@pytest.fixture
def result(old_app, new_app):
    return diff_applications(old_app, new_app)


class TestNoChanges:
    def test_identical_snapshots(self, old_app):
        diff = diff_applications(old_app, old_app)
        assert diff["has_changes"] is False
        for section in ("objects", "fields", "scenes", "views"):
            assert all(not entries for entries in diff[section].values())

    def test_has_changes_flag_set(self, result):
        assert result["has_changes"] is True


class TestObjectDiffs:
    def test_added(self, result):
        added = {e["key"]: e for e in result["objects"]["added"]}
        assert added["object_999"]["name"] == "Brand New Object"
        assert added["object_999"]["field_count"] == 2

    def test_removed(self, result):
        assert "object_23" in {e["key"] for e in result["objects"]["removed"]}

    def test_renamed(self, result):
        renamed = {e["key"]: e for e in result["objects"]["renamed"]}
        assert renamed["object_12"]["old_name"] == "Object Name 12"
        assert renamed["object_12"]["new_name"] == "Object Twelve Renamed"


class TestFieldDiffs:
    def test_added(self, result):
        assert "field_9999" in {e["key"] for e in result["fields"]["added"]}

    def test_removed(self, result):
        assert "field_104" in {e["key"] for e in result["fields"]["removed"]}

    def test_changed_attributes(self, result):
        changed = {e["key"]: e for e in result["fields"]["changed"]}
        assert "field_89" in changed
        changes = changed["field_89"]["changes"]
        assert changes["type"]["new"] == "paragraph_text"
        assert changes["required"] == {"old": True, "new": False}

    def test_removed_object_fields_not_listed(self, result, old_app):
        """Noise rule: removing object_23 must not spam the removed-fields list."""
        removed_obj = next(o for o in old_app.objects if o.key == "object_23")
        removed_field_keys = {f.key for f in removed_obj.fields}
        listed = {e["key"] for e in result["fields"]["removed"]}
        assert not (removed_field_keys & listed)

    def test_added_object_fields_not_listed(self, result):
        """Noise rule: adding object_999 must not spam the added-fields list."""
        listed = {e["key"] for e in result["fields"]["added"]}
        assert "field_9001" not in listed
        assert "field_9002" not in listed


class TestSceneAndViewDiffs:
    def test_scene_added(self, result):
        assert "scene_999" in {e["key"] for e in result["scenes"]["added"]}

    def test_scene_removed(self, result, old_app):
        assert old_app.scenes[-1].key in {e["key"] for e in result["scenes"]["removed"]}

    def test_scene_renamed(self, result, old_app):
        renamed = {e["key"]: e for e in result["scenes"]["renamed"]}
        assert old_app.scenes[0].key in renamed

    def test_view_added(self, result):
        assert "view_9999" in {e["key"] for e in result["views"]["added"]}

    def test_view_renamed(self, result, old_app):
        # The mutation renames the first view of the first remaining scene
        # that has views — recompute which one that was.
        target_scene = next(s for s in old_app.scenes[:-1] if s.views)
        renamed_view_key = target_scene.views[0].key

        changed = {e["key"]: e for e in result["views"]["changed"]}
        assert renamed_view_key in changed
        assert changed[renamed_view_key]["changes"]["name"]["new"] == "Totally Renamed View"

    def test_added_scene_views_not_listed(self, result):
        """Noise rule: adding scene_999 must not spam the added-views list."""
        assert "view_9001" not in {e["key"] for e in result["views"]["added"]}


class TestMarkdownReport:
    def test_contains_all_sections(self, result):
        md = diff_to_markdown(result)
        assert "# Metadata Diff" in md
        assert "## Objects Added (1)" in md
        assert "## Objects Removed (1)" in md
        assert "field_9999" in md
        assert "Object Twelve Renamed" in md

    def test_no_changes_report(self, old_app):
        md = diff_to_markdown(diff_applications(old_app, old_app))
        assert "No structural changes" in md

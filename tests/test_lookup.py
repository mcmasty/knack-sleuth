"""Tests for knack_sleuth.lookup resolution helpers."""

import copy

import pytest

from knack_sleuth.lookup import (
    resolve_fields,
    resolve_object,
    suggest_field_names,
    suggest_object_names,
)
from knack_sleuth.models import KnackAppMetadata


@pytest.fixture
def app(sample_metadata_dict):
    """Parsed Application from the sample metadata."""
    return KnackAppMetadata(**sample_metadata_dict).application


class TestResolveObject:
    def test_by_key(self, app):
        obj = resolve_object(app, "object_12")
        assert obj is not None
        assert obj.key == "object_12"

    def test_by_key_case_insensitive(self, app):
        obj = resolve_object(app, "OBJECT_12")
        assert obj is not None
        assert obj.key == "object_12"

    def test_by_name_case_insensitive(self, app):
        expected = app.objects[0]
        obj = resolve_object(app, expected.name.upper())
        assert obj is not None
        assert obj.key == expected.key

    def test_unknown_returns_none(self, app):
        assert resolve_object(app, "no-such-object") is None


class TestResolveFields:
    def test_by_key_returns_single_match(self, app):
        matches = resolve_fields(app, "field_88")
        assert len(matches) == 1
        obj, field = matches[0]
        assert field.key == "field_88"
        assert any(f.key == "field_88" for f in obj.fields)

    def test_by_key_case_insensitive(self, app):
        matches = resolve_fields(app, "FIELD_88")
        assert len(matches) == 1
        assert matches[0][1].key == "field_88"

    def test_by_name_can_be_ambiguous(self, app):
        # "Name" exists on many objects in the sample app
        matches = resolve_fields(app, "Name")
        assert len(matches) > 1
        assert all(field.name.lower() == "name" for _, field in matches)

    def test_unknown_returns_empty(self, app):
        assert resolve_fields(app, "no-such-field") == []


class TestSuggestions:
    def test_object_suggestions_for_typo(self, app):
        suggestions = suggest_object_names(app, "Ref Data Categry")
        assert "Ref Data Category" in suggestions

    def test_field_suggestions_for_typo(self, app):
        suggestions = suggest_field_names(app, "Namee")
        assert "Name" in suggestions

    def test_no_suggestions_for_gibberish(self, app):
        assert suggest_object_names(app, "zzzzqqqqxxxx") == []


class TestWhitespace:
    """A name saved with a stray space must still be found by what is visible."""

    @pytest.fixture
    def spaced(self, sample_metadata_dict):
        data = copy.deepcopy(sample_metadata_dict)
        obj = data["application"]["objects"][0]
        obj["name"] = "  Work   Orders "
        obj["fields"][0]["name"] = "Status "
        return KnackAppMetadata(**data).application

    @pytest.mark.parametrize("typed", ["Work Orders", "work orders", " Work  Orders"])
    def test_object_name_ignores_stray_whitespace(self, spaced, typed):
        assert resolve_object(spaced, typed) is spaced.objects[0]

    @pytest.mark.parametrize("typed", ["Status", "status ", "Status "])
    def test_field_name_ignores_stray_whitespace(self, spaced, typed):
        matches = resolve_fields(spaced, typed)
        assert (spaced.objects[0], spaced.objects[0].fields[0]) in matches

    def test_key_ignores_surrounding_whitespace(self, spaced):
        key = spaced.objects[0].key
        assert resolve_object(spaced, f" {key} ") is spaced.objects[0]

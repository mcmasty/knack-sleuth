"""Knack writes null where a value is absent; one null shouldn't stop every command.

A null in a field with a default takes the default, and a null display name
falls back to the key. Keys, types and connection targets stay required, and
when one is null the CLI says where in one line.
"""

import copy
import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from knack_sleuth.cli import cli
from knack_sleuth.cli._common import describe_validation_error
from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.security import generate_security_report
from knack_sleuth.sleuth import KnackSleuth


@pytest.fixture
def metadata(sample_metadata_dict):
    return copy.deepcopy(sample_metadata_dict)


def _first_view(metadata: dict) -> dict:
    return next(s for s in metadata["application"]["scenes"] if s.get("views"))[
        "views"
    ][0]


def test_null_names_fall_back_to_the_key(metadata):
    app = metadata["application"]
    view = _first_view(metadata)
    app["objects"][0]["name"] = None
    app["objects"][0]["fields"][0]["name"] = None
    app["scenes"][0]["name"] = None
    app["scenes"][0]["slug"] = None
    view["name"] = None

    parsed = KnackAppMetadata(**metadata).application
    assert parsed.objects[0].name == parsed.objects[0].key
    assert parsed.objects[0].fields[0].name == parsed.objects[0].fields[0].key
    assert parsed.scenes[0].name == parsed.scenes[0].slug == parsed.scenes[0].key
    views = [v for s in parsed.scenes for v in s.views]
    assert views[0].name == views[0].key


def test_null_with_a_default_takes_the_default(metadata):
    app = metadata["application"]
    app["description"] = None
    field = app["objects"][0]["fields"][0]
    field["required"] = None
    field["rules"] = None
    app["scenes"][0]["views"] = None
    first_count = next(iter(app["counts"]))
    app["counts"][first_count] = None

    parsed = KnackAppMetadata(**metadata).application
    assert parsed.description == ""
    assert parsed.objects[0].fields[0].required is False
    assert parsed.objects[0].fields[0].rules == []
    assert parsed.scenes[0].views == []
    assert first_count not in parsed.counts


def test_a_null_key_is_still_an_error(metadata):
    _first_view(metadata)["key"] = None
    with pytest.raises(ValidationError):
        KnackAppMetadata(**metadata)


def test_analyses_run_on_metadata_with_null_names(metadata):
    _first_view(metadata)["name"] = None
    metadata["application"]["objects"][0]["name"] = None
    parsed = KnackAppMetadata(**metadata)
    sleuth = KnackSleuth(parsed)
    sleuth.find_orphaned_fields()
    sleuth.generate_app_summary()
    generate_security_report(parsed.application)


def test_null_profile_key_restricts_nothing(metadata):
    view = _first_view(metadata)
    view["allowed_profiles"] = [None]
    view["limit_profile_access"] = True
    report = generate_security_report(KnackAppMetadata(**metadata).application)
    assert all(None not in scene.allowed_profiles for scene in report.scene_analyses)


def test_validation_error_is_one_line_with_the_path(metadata):
    _first_view(metadata)["key"] = None
    with pytest.raises(ValidationError) as caught:
        KnackAppMetadata(**metadata)
    message = describe_validation_error(caught.value)
    assert "\n" not in message
    assert message.startswith("Invalid metadata at application.scenes[")
    assert message.endswith("views[0].key: Input should be a valid string, got null")


def test_cli_reports_bad_metadata_in_one_line(metadata, tmp_path):
    _first_view(metadata)["key"] = None
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(metadata))
    result = CliRunner().invoke(cli, ["find-orphans", str(path)])
    assert result.exit_code == 1
    assert "Invalid metadata at application.scenes[" in result.output
    assert "errors.pydantic.dev" not in result.output


def test_missing_key_message_names_no_input():
    with pytest.raises(ValidationError) as caught:
        KnackAppMetadata.model_validate({})
    assert describe_validation_error(caught.value) == (
        "Invalid metadata at application: Field required"
    )

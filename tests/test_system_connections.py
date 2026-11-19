"""Knack's own audit connections are not part of an app's data model.

Knack adds Created By, Updated By and Owned By to every object, each a
connection to the Accounts object and each marked ``isSystemField``. These
tests add those fields to the sample app and check that relationship
analysis is the same as without them, unless they are asked for.
"""

import copy
import json

import pytest
from typer.testing import CliRunner

from knack_sleuth.cli import cli
from knack_sleuth.models import KnackAppMetadata
from knack_sleuth.sleuth import KnackSleuth
from knack_sleuth.system_fields import (
    system_connection_keys,
    without_system_connections,
)

runner = CliRunner()
ENV = {"COLUMNS": "200", "KNACK_APP_ID": ""}
AUDIT = ("Created By", "Updated By", "Owned By")


def with_audit_fields(metadata: dict) -> tuple[dict, int]:
    """The app with Knack's three audit connections on every object, and how
    many were added. They point at the first user object, as Knack's do."""
    data = copy.deepcopy(metadata)
    objects = data["application"]["objects"]
    accounts = next(o for o in objects if o.get("user"))
    added = 0
    for obj in objects:
        for name in AUDIT:
            key = f"field_9{added:03d}"
            added += 1
            obj["fields"].append(
                {
                    "key": key,
                    "name": name,
                    "type": "connection",
                    "isSystemField": True,
                    "immutable": True,
                    "relationship": {
                        "has": "one",
                        "object": accounts["key"],
                        "belongs_to": "many",
                    },
                }
            )
            link = {"key": key, "name": name, "has": "one", "belongs_to": "many"}
            obj["connections"]["outbound"].append(
                {**link, "object": accounts["key"], "field": {"name": name}}
            )
            accounts["connections"]["inbound"].append(
                {**link, "object": obj["key"], "field": {"name": name}}
            )
    return data, added


@pytest.fixture
def audited(sample_metadata_dict):
    return with_audit_fields(sample_metadata_dict)


@pytest.fixture
def files(tmp_path, sample_metadata_dict, audited):
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps(sample_metadata_dict))
    with_audit = tmp_path / "audited.json"
    with_audit.write_text(json.dumps(audited[0]))
    return plain, with_audit


def test_view_drops_the_audit_connections_and_nothing_else(
    sample_metadata_dict, audited
):
    data, added = audited
    assert added == 19 * 3
    app = KnackAppMetadata(**data).application
    plain = KnackAppMetadata(**sample_metadata_dict).application

    assert len(system_connection_keys(app)) == added
    view, removed = without_system_connections(app)

    assert removed == added
    for seen, original, audited_obj in zip(
        view.objects, plain.objects, app.objects, strict=True
    ):
        assert seen.connections == original.connections
        # The fields are still fields; only the relationships are hidden.
        assert seen.fields == audited_obj.fields
    # The app it was built from is not changed.
    outbound = sum(len(o.connections.outbound) for o in app.objects if o.connections)
    assert outbound == 31 + added


def test_app_without_system_connections_is_returned_as_it_is(sample_metadata_dict):
    app = KnackAppMetadata(**sample_metadata_dict).application
    view, removed = without_system_connections(app)
    assert (view is app, removed) == (True, 0)


def test_a_system_field_that_is_not_a_connection_stays(sample_metadata_dict):
    data = copy.deepcopy(sample_metadata_dict)
    data["application"]["objects"][0]["fields"].append(
        {
            "key": "field_9999",
            "name": "Record ID",
            "type": "short_text",
            "isSystemField": True,
        }
    )
    assert system_connection_keys(KnackAppMetadata(**data).application) == set()


def test_app_summary_relationships_ignore_audit_connections(
    sample_metadata_dict, audited
):
    data, added = audited
    plain = KnackSleuth(KnackAppMetadata(**sample_metadata_dict)).generate_app_summary()
    summary = KnackSleuth(KnackAppMetadata(**data)).generate_app_summary()

    metrics = summary["application"]["complexity_metrics"]
    assert metrics["system_connections_excluded"] == added
    assert (
        metrics["connection_density"]
        == plain["application"]["complexity_metrics"]["connection_density"]
    )
    for section in ("relationship_map", "extensibility_assessment"):
        assert summary[section] == plain[section]
    debt, plain_debt = (
        summary["technical_debt_indicators"],
        plain["technical_debt_indicators"],
    )
    assert debt["bottleneck_objects"] == plain_debt["bottleneck_objects"]
    assert debt["high_fan_out_objects"] == plain_debt["high_fan_out_objects"]
    # Orphans are counted on the app as it is: an audit field is in use
    # because of its connection, so hiding the connection must not orphan it.
    assert debt["orphaned_fields"] == plain_debt["orphaned_fields"]


def test_app_summary_can_include_them(audited):
    data, added = audited
    summary = KnackSleuth(KnackAppMetadata(**data)).generate_app_summary(
        include_system_connections=True
    )

    assert (
        summary["application"]["complexity_metrics"]["system_connections_excluded"] == 0
    )
    assert (
        summary["relationship_map"]["connection_graph"]["total_connections"]
        == 31 + added
    )
    # Every object now reaches Accounts, so the app reads as one cluster.
    clusters = summary["relationship_map"]["dependency_clusters"]
    assert [len(c["object_keys"]) for c in clusters] == [19]


def _json(*args):
    result = runner.invoke(cli, [str(a) for a in args], env=ENV)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout), result.stderr


def test_list_objects_counts_real_connections_and_says_what_it_left_out(files):
    plain, with_audit = files
    expected, _ = _json("list-objects", plain, "--format", "json")
    actual, stderr = _json("list-objects", with_audit, "--format", "json")

    assert actual["totals"]["system_connections_excluded"] == 57
    assert actual["totals"]["connections"] == expected["totals"]["connections"] == 31
    for mine, theirs in zip(actual["objects"], expected["objects"], strict=True):
        assert (mine["ca"], mine["ce"]) == (theirs["ca"], theirs["ce"])
        assert mine["fields"] == theirs["fields"] + 3
    assert "57 system audit connections" in stderr
    assert "--include-system-connections" in stderr

    included, stderr = _json(
        "list-objects", with_audit, "--format", "json", "--include-system-connections"
    )
    assert included["totals"]["connections"] == 31 + 57
    assert included["totals"]["system_connections_excluded"] == 0
    assert "system audit connections" not in stderr


def test_show_coupling_hides_them_by_default(files):
    plain, with_audit = files
    expected, _ = _json("show-coupling", "object_13", plain, "--format", "json")
    actual, _ = _json("show-coupling", "object_13", with_audit, "--format", "json")

    assert actual["system_connections_excluded"] == 57
    assert (actual["ca"], actual["ce"]) == (expected["ca"], expected["ce"])
    assert actual["outbound"] == expected["outbound"]

    included, _ = _json(
        "show-coupling",
        "object_13",
        with_audit,
        "--format",
        "json",
        "--include-system-connections",
    )
    assert included["ce"] == expected["ce"] + 3
    assert {c["connection_name"] for c in included["outbound"]} >= set(AUDIT)


@pytest.mark.parametrize("fmt", ["mermaid", "dbml", "yaml", "json"])
def test_schema_export_draws_no_audit_relationships(files, tmp_path, fmt):
    _, with_audit = files

    def relationships(source, *extra):
        out = tmp_path / f"{source.stem}{len(extra)}.{fmt}"
        result = runner.invoke(
            cli,
            [
                "export-db-schema",
                str(source),
                "--format",
                fmt,
                "--detail",
                "minimal",
                "-o",
                str(out),
                *extra,
            ],
            env=ENV,
        )
        assert result.exit_code == 0, result.output
        text = out.read_text()
        return sum(text.count(name) for name in AUDIT), text

    by_default, text = relationships(with_audit)
    asked_for, _ = relationships(with_audit, "--include-system-connections")
    assert asked_for > by_default
    if fmt in ("mermaid", "dbml"):
        # In these two a connection's name appears only on its relationship
        # line at this detail level; the columns carry field keys.
        marker = ' : "' if fmt == "mermaid" else "Ref:"
        lines = [line for line in text.splitlines() if marker in line]
        assert lines
        assert not [line for line in lines if any(name in line for name in AUDIT)]
